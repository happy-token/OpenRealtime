"""Provider-neutral lifecycle for externally supplied speech text."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from server.realtime.protocol.commands import (
    AppendSpeechText,
    CancelSpeech,
    CommitSpeech,
    ReportPlaybackProgress,
    StartSpeech,
)
from server.realtime.protocol.events import (
    SpeechCancelled,
    SpeechPlaybackProgress,
    SpeechStarted,
    SpeechTextAccepted,
    SpeechTextCommitted,
)
from server.realtime.speech.delivery import (
    InMemorySpeechDeliveryStore,
    SpeechDeliveryRecord,
    SpeechDeliveryStatus,
    SpeechDeliveryStore,
)


class SpeechLifecycle:
    """Validate speech commands and persist intended/delivered speech facts."""

    def __init__(self, deliveries: SpeechDeliveryStore | None = None) -> None:
        self._deliveries = deliveries or InMemorySpeechDeliveryStore()
        self._used_ids: set[str] = set()
        self._text_open_ids: set[str] = set()
        self._unsettled_ids: set[str] = set()
        self._next_text_sequence: dict[str, int] = {}
        self._text_parts: dict[str, list[str]] = {}

    async def start(
        self, command: StartSpeech, *, sequence: Callable[[], int]
    ) -> SpeechStarted:
        if command.speech_id in self._used_ids:
            raise ValueError("speech output identity was already used")
        await self._deliveries.start(
            SpeechDeliveryRecord(
                speech_id=command.speech_id,
                context=command.context,
                source_item_id=command.source_item_id,
                context_policy=command.context_policy,
                interrupted_context_policy=command.interrupted_context_policy,
            )
        )
        self._used_ids.add(command.speech_id)
        self._text_open_ids.add(command.speech_id)
        self._unsettled_ids.add(command.speech_id)
        self._next_text_sequence[command.speech_id] = 1
        self._text_parts[command.speech_id] = []
        return SpeechStarted(
            event_id=str(uuid.uuid4()),
            context=command.context,
            conversation_sequence=sequence(),
            occurred_at=datetime.now(UTC),
            speech_id=command.speech_id,
            source_item_id=command.source_item_id,
            context_policy=command.context_policy,
            interrupted_context_policy=command.interrupted_context_policy,
        )

    async def append(
        self,
        command: AppendSpeechText,
        *,
        sequence: Callable[[], int],
    ) -> SpeechTextAccepted:
        self._require_text_open(command.speech_id)
        expected = self._next_text_sequence[command.speech_id]
        if command.text_sequence != expected:
            raise ValueError(
                f"expected speech text sequence {expected}, received {command.text_sequence}"
            )
        await self._deliveries.append_text(command.speech_id, command.delta)
        self._next_text_sequence[command.speech_id] = expected + 1
        self._text_parts[command.speech_id].append(command.delta)
        return SpeechTextAccepted(
            event_id=str(uuid.uuid4()),
            context=command.context,
            conversation_sequence=sequence(),
            occurred_at=datetime.now(UTC),
            speech_id=command.speech_id,
            text_sequence=command.text_sequence,
            delta=command.delta,
        )

    async def commit(
        self,
        command: CommitSpeech,
        *,
        sequence: Callable[[], int],
    ) -> SpeechTextCommitted:
        self._require_text_open(command.speech_id)
        spoken_text = "".join(self._text_parts[command.speech_id])
        if not spoken_text:
            raise ValueError("cannot commit speech without accepted text")
        await self._deliveries.commit_text(command.speech_id)
        self._text_open_ids.remove(command.speech_id)
        return SpeechTextCommitted(
            event_id=str(uuid.uuid4()),
            context=command.context,
            conversation_sequence=sequence(),
            occurred_at=datetime.now(UTC),
            speech_id=command.speech_id,
            spoken_text=spoken_text,
        )

    async def report(
        self,
        command: ReportPlaybackProgress,
        *,
        sequence: Callable[[], int],
    ) -> SpeechPlaybackProgress:
        if command.speech_id not in self._unsettled_ids:
            record = await self._deliveries.get(command.speech_id)
            if record is None or record.status is not SpeechDeliveryStatus.INTERRUPTED:
                raise ValueError("speech output is already settled")
        record = await self._deliveries.report_progress(
            command.speech_id,
            delivered_text_end=command.delivered_text_end,
            played_audio_end_us=command.played_audio_end_us,
            precision=command.precision,
            completed=command.completed,
        )
        if command.completed:
            self._unsettled_ids.discard(command.speech_id)
        return SpeechPlaybackProgress(
            event_id=str(uuid.uuid4()),
            context=command.context,
            conversation_sequence=sequence(),
            occurred_at=datetime.now(UTC),
            speech_id=command.speech_id,
            delivered_text_end=command.delivered_text_end,
            delivered_speech_transcript=record.delivered_speech_transcript,
            played_audio_end_us=command.played_audio_end_us,
            precision=command.precision,
            completed=command.completed,
        )

    async def cancel(
        self,
        command: CancelSpeech,
        *,
        sequence: Callable[[], int],
    ) -> SpeechCancelled:
        self._require_unsettled(command.speech_id)
        accepted_text = "".join(self._text_parts[command.speech_id])
        await self._deliveries.cancel(command.speech_id, reason=command.reason)
        self._text_open_ids.discard(command.speech_id)
        self._unsettled_ids.remove(command.speech_id)
        return SpeechCancelled(
            event_id=str(uuid.uuid4()),
            context=command.context,
            conversation_sequence=sequence(),
            occurred_at=datetime.now(UTC),
            speech_id=command.speech_id,
            accepted_text=accepted_text,
            reason=command.reason,
        )

    async def fail(self, speech_id: str, *, reason: str) -> None:
        self._require_unsettled(speech_id)
        await self._deliveries.fail(speech_id, reason=reason)
        self._text_open_ids.discard(speech_id)
        self._unsettled_ids.remove(speech_id)

    async def close(self) -> None:
        for speech_id in tuple(self._unsettled_ids):
            await self._deliveries.mark_uncertain(
                speech_id,
                reason="conversation_closed_before_playback_terminal",
            )
        self._text_open_ids.clear()
        self._unsettled_ids.clear()

    def _require_text_open(self, speech_id: str) -> None:
        if speech_id not in self._text_open_ids:
            raise ValueError("speech output is not active")

    def _require_unsettled(self, speech_id: str) -> None:
        if speech_id not in self._unsettled_ids:
            raise ValueError("speech delivery is not active")
