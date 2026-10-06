"""Authoritative speech-delivery facts, separate from intended response content."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, TypedDict, Unpack

from server.core.interaction_context import InteractionContext
from server.realtime.protocol.commands import (
    InterruptedContextPolicy,
    OutputStopFact,
    PlaybackPrecision,
    SpeechContextPolicy,
)
from server.realtime.scope import conversation_scope


class SpeechDeliveryStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    UNCERTAIN = "uncertain"

    @property
    def terminal(self) -> bool:
        return self is not SpeechDeliveryStatus.ACTIVE


class _DeliveryChanges(TypedDict, total=False):
    intended_spoken_content: str
    delivered_speech_transcript: str
    played_audio_end_us: int
    status: SpeechDeliveryStatus
    precision: PlaybackPrecision
    text_committed: bool
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechDeliveryRecord:
    speech_id: str
    context: InteractionContext
    source_item_id: str | None
    context_policy: SpeechContextPolicy
    interrupted_context_policy: InterruptedContextPolicy
    intended_spoken_content: str = ""
    delivered_speech_transcript: str = ""
    played_audio_end_us: int = 0
    status: SpeechDeliveryStatus = SpeechDeliveryStatus.ACTIVE
    precision: PlaybackPrecision | None = None
    text_committed: bool = False
    reason: str | None = None
    revision: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=UTC))

    def __post_init__(self) -> None:
        if not self.speech_id:
            raise ValueError("speech delivery identity must be non-empty")
        if self.source_item_id == "":
            raise ValueError("source item identity must be non-empty when provided")
        if self.played_audio_end_us < 0 or self.revision < 1:
            raise ValueError("speech delivery counters must be non-negative")
        if not self.intended_spoken_content.startswith(self.delivered_speech_transcript):
            raise ValueError("delivered speech must be a prefix of intended speech")
        if self.updated_at.tzinfo is None:
            raise ValueError("speech delivery timestamp must be timezone-aware")


class SpeechDeliveryStore(Protocol):
    @property
    def output_stop_durable(self) -> bool: ...

    async def record_output_stop(self, fact: OutputStopFact) -> OutputStopFact: ...

    async def get_output_stop(
        self, context: InteractionContext, stop_command_id: str
    ) -> OutputStopFact | None: ...

    async def delete_output_stop_facts(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        voice_session_id: str,
    ) -> int: ...

    async def start(self, record: SpeechDeliveryRecord) -> SpeechDeliveryRecord: ...

    async def append_text(self, speech_id: str, delta: str) -> SpeechDeliveryRecord: ...

    async def commit_text(self, speech_id: str) -> SpeechDeliveryRecord: ...

    async def report_progress(
        self,
        speech_id: str,
        *,
        delivered_text_end: int,
        played_audio_end_us: int,
        precision: PlaybackPrecision,
        completed: bool,
    ) -> SpeechDeliveryRecord: ...

    async def cancel(self, speech_id: str, *, reason: str) -> SpeechDeliveryRecord: ...

    async def fail(self, speech_id: str, *, reason: str) -> SpeechDeliveryRecord: ...

    async def mark_uncertain(self, speech_id: str, *, reason: str) -> SpeechDeliveryRecord: ...

    async def get(self, speech_id: str) -> SpeechDeliveryRecord | None: ...

    async def latest_for_item(self, item_id: str) -> SpeechDeliveryRecord | None: ...


class InMemorySpeechDeliveryStore:
    def __init__(self) -> None:
        self._records: dict[str, SpeechDeliveryRecord] = {}
        self._lock = asyncio.Lock()
        self._output_stops: dict[tuple[str, ...], OutputStopFact] = {}

    @property
    def output_stop_durable(self) -> bool:
        return False

    async def record_output_stop(self, fact: OutputStopFact) -> OutputStopFact:
        key = (*conversation_scope(fact.context), fact.stop_command_id)
        async with self._lock:
            existing = self._output_stops.get(key)
            saved = transition_output_stop_fact(existing, fact)
            self._output_stops[key] = saved
            return saved

    async def get_output_stop(
        self, context: InteractionContext, stop_command_id: str
    ) -> OutputStopFact | None:
        if not stop_command_id:
            raise ValueError("stop operation identity must be non-empty")
        async with self._lock:
            return self._output_stops.get((*conversation_scope(context), stop_command_id))

    async def delete_output_stop_facts(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        voice_session_id: str,
    ) -> int:
        scope = (tenant_id, user_id, thread_id, voice_session_id)
        validate_output_stop_deletion_scope(scope)
        async with self._lock:
            keys = [key for key in self._output_stops if (key[0], key[1], key[4], key[3]) == scope]
            for key in keys:
                del self._output_stops[key]
            return len(keys)

    async def start(self, record: SpeechDeliveryRecord) -> SpeechDeliveryRecord:
        async with self._lock:
            existing = self._records.get(record.speech_id)
            if existing is not None:
                if not _same_delivery_identity(existing, record):
                    raise ValueError("speech delivery identity was reused")
                return existing
            started = replace(record, updated_at=datetime.now(UTC))
            self._records[started.speech_id] = started
            return started

    async def append_text(self, speech_id: str, delta: str) -> SpeechDeliveryRecord:
        if not delta:
            raise ValueError("speech text delta must be non-empty")
        async with self._lock:
            record = self._active(speech_id)
            if record.text_committed:
                raise ValueError("speech text is already committed")
            return self._save(
                record,
                intended_spoken_content=record.intended_spoken_content + delta,
            )

    async def commit_text(self, speech_id: str) -> SpeechDeliveryRecord:
        async with self._lock:
            record = self._active(speech_id)
            if not record.intended_spoken_content:
                raise ValueError("cannot commit speech without accepted text")
            if record.text_committed:
                return record
            return self._save(record, text_committed=True)

    async def report_progress(
        self,
        speech_id: str,
        *,
        delivered_text_end: int,
        played_audio_end_us: int,
        precision: PlaybackPrecision,
        completed: bool,
    ) -> SpeechDeliveryRecord:
        async with self._lock:
            record = self._records.get(speech_id)
            if record is None:
                raise KeyError(speech_id)
            if record.status not in {
                SpeechDeliveryStatus.ACTIVE,
                SpeechDeliveryStatus.INTERRUPTED,
            }:
                raise ValueError("speech delivery does not accept playback progress")
            if record.status is SpeechDeliveryStatus.INTERRUPTED and completed:
                raise ValueError("interrupted playback cannot later complete")
            if delivered_text_end < len(record.delivered_speech_transcript):
                raise ValueError("delivered speech progress must be monotonic")
            if delivered_text_end > len(record.intended_spoken_content):
                raise ValueError("playback cannot exceed accepted speech text")
            if played_audio_end_us < record.played_audio_end_us:
                raise ValueError("played audio progress must be monotonic")
            if completed and (
                not record.text_committed
                or delivered_text_end != len(record.intended_spoken_content)
            ):
                raise ValueError("completed playback must include all committed speech text")
            return self._save(
                record,
                delivered_speech_transcript=record.intended_spoken_content[:delivered_text_end],
                played_audio_end_us=played_audio_end_us,
                precision=precision,
                status=(SpeechDeliveryStatus.COMPLETED if completed else record.status),
            )

    async def cancel(self, speech_id: str, *, reason: str) -> SpeechDeliveryRecord:
        if not reason:
            raise ValueError("speech cancellation reason must be non-empty")
        async with self._lock:
            record = self._active(speech_id)
            return self._save(
                record,
                status=SpeechDeliveryStatus.INTERRUPTED,
                reason=reason,
            )

    async def fail(self, speech_id: str, *, reason: str) -> SpeechDeliveryRecord:
        if not reason:
            raise ValueError("speech failure reason must be non-empty")
        async with self._lock:
            record = self._active(speech_id)
            return self._save(
                record,
                status=SpeechDeliveryStatus.FAILED,
                reason=reason,
            )

    async def mark_uncertain(self, speech_id: str, *, reason: str) -> SpeechDeliveryRecord:
        if not reason:
            raise ValueError("uncertain delivery reason must be non-empty")
        async with self._lock:
            record = self._active(speech_id)
            return self._save(
                record,
                status=SpeechDeliveryStatus.UNCERTAIN,
                reason=reason,
            )

    async def get(self, speech_id: str) -> SpeechDeliveryRecord | None:
        async with self._lock:
            return self._records.get(speech_id)

    async def latest_for_item(self, item_id: str) -> SpeechDeliveryRecord | None:
        if not item_id:
            raise ValueError("Conversation Item identity must be non-empty")
        async with self._lock:
            matches = (
                record for record in self._records.values() if record.source_item_id == item_id
            )
            return max(matches, key=lambda record: record.updated_at, default=None)

    def _active(self, speech_id: str) -> SpeechDeliveryRecord:
        record = self._records.get(speech_id)
        if record is None:
            raise KeyError(speech_id)
        if record.status.terminal:
            raise ValueError("speech delivery is already terminal")
        return record

    def _save(
        self, record: SpeechDeliveryRecord, **changes: Unpack[_DeliveryChanges]
    ) -> SpeechDeliveryRecord:
        updated = replace(
            record,
            **changes,
            revision=record.revision + 1,
            updated_at=datetime.now(UTC),
        )
        self._records[record.speech_id] = updated
        return updated


def _same_delivery_identity(
    left: SpeechDeliveryRecord,
    right: SpeechDeliveryRecord,
) -> bool:
    return (
        left.speech_id,
        left.context,
        left.source_item_id,
        left.context_policy,
        left.interrupted_context_policy,
    ) == (
        right.speech_id,
        right.context,
        right.source_item_id,
        right.context_policy,
        right.interrupted_context_policy,
    )


def transition_output_stop_fact(
    current: OutputStopFact | None, candidate: OutputStopFact
) -> OutputStopFact:
    """Preserve first terminal evidence and fence every operation's immutable target."""
    if current is None:
        return candidate
    if (
        current.context,
        current.stop_command_id,
        current.output_epoch,
        current.speech_id,
        current.reason,
        current.requested_at,
    ) != (
        candidate.context,
        candidate.stop_command_id,
        candidate.output_epoch,
        candidate.speech_id,
        candidate.reason,
        candidate.requested_at,
    ):
        raise ValueError("stop operation identity was reused with different content")
    if candidate.state == "STOP_REQUESTED":
        return current
    if current.state == "STOP_REQUESTED":
        return candidate
    if (
        current.state,
        current.receipt_outcome,
        current.played_position_samples,
        current.failure_reason,
    ) != (
        candidate.state,
        candidate.receipt_outcome,
        candidate.played_position_samples,
        candidate.failure_reason,
    ):
        raise ValueError("terminal stop evidence cannot be rewritten")
    return current


def validate_output_stop_deletion_scope(scope: tuple[str, str, str, str]) -> None:
    if any(not isinstance(value, str) or not value for value in scope):
        raise ValueError("stop fact deletion requires a complete session scope")
