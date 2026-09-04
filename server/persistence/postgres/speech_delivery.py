"""PostgreSQL SpeechDeliveryStore with fenced row transitions."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from server.core.interaction_context import InteractionContext
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name
from server.realtime.protocol.commands import (
    InterruptedContextPolicy,
    PlaybackPrecision,
    SpeechContextPolicy,
)
from server.realtime.speech import SpeechDeliveryRecord, SpeechDeliveryStatus


class PostgresSpeechDeliveryStore:
    def __init__(self, executor: Any, *, schema: str = "voiceagent") -> None:
        self._executor = executor
        self._table = f'"{validate_schema_name(schema)}".speech_delivery_records'

    async def start(self, record: SpeechDeliveryRecord) -> SpeechDeliveryRecord:
        now = datetime.now(UTC)
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                INSERT INTO {self._table} (
                    speech_id, context, source_item_id, context_policy,
                    interrupted_context_policy, intended_spoken_content,
                    delivered_speech_transcript, played_audio_end_us, status,
                    precision, text_committed, reason, revision, created_at, updated_at
                ) VALUES (
                    $1, $2::jsonb, $3, $4, $5, $6, $7, $8, $9,
                    $10, $11, $12, $13, $14, $14
                )
                ON CONFLICT (speech_id) DO NOTHING
                RETURNING *
                """,
                record.speech_id,
                _json(_context_payload(record.context)),
                record.source_item_id,
                record.context_policy.value,
                record.interrupted_context_policy.value,
                record.intended_spoken_content,
                record.delivered_speech_transcript,
                record.played_audio_end_us,
                record.status.value,
                record.precision.value if record.precision is not None else None,
                record.text_committed,
                record.reason,
                record.revision,
                now,
            )
            persisted = (
                self._record(row)
                if row is not None
                else await self._get(connection, record.speech_id)
            )
        if not _same_identity(persisted, record):
            raise ValueError("speech delivery identity was reused")
        return persisted

    async def append_text(self, speech_id: str, delta: str) -> SpeechDeliveryRecord:
        if not delta:
            raise ValueError("speech text delta must be non-empty")

        def transition(record: SpeechDeliveryRecord) -> SpeechDeliveryRecord:
            _require_active(record)
            if record.text_committed:
                raise ValueError("speech text is already committed")
            return replace(
                record,
                intended_spoken_content=record.intended_spoken_content + delta,
            )

        return await self._mutate(speech_id, transition)

    async def commit_text(self, speech_id: str) -> SpeechDeliveryRecord:
        def transition(record: SpeechDeliveryRecord) -> SpeechDeliveryRecord:
            _require_active(record)
            if not record.intended_spoken_content:
                raise ValueError("cannot commit speech without accepted text")
            return replace(record, text_committed=True)

        return await self._mutate(speech_id, transition)

    async def report_progress(
        self,
        speech_id: str,
        *,
        delivered_text_end: int,
        played_audio_end_us: int,
        precision: PlaybackPrecision,
        completed: bool,
    ) -> SpeechDeliveryRecord:
        def transition(record: SpeechDeliveryRecord) -> SpeechDeliveryRecord:
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
            return replace(
                record,
                delivered_speech_transcript=record.intended_spoken_content[:delivered_text_end],
                played_audio_end_us=played_audio_end_us,
                precision=precision,
                status=(
                    SpeechDeliveryStatus.COMPLETED
                    if completed
                    else record.status
                ),
            )

        return await self._mutate(speech_id, transition)

    async def cancel(self, speech_id: str, *, reason: str) -> SpeechDeliveryRecord:
        if not reason:
            raise ValueError("speech cancellation reason must be non-empty")
        return await self._mutate(
            speech_id,
            lambda record: _settle(record, SpeechDeliveryStatus.INTERRUPTED, reason),
        )

    async def fail(self, speech_id: str, *, reason: str) -> SpeechDeliveryRecord:
        if not reason:
            raise ValueError("speech failure reason must be non-empty")
        return await self._mutate(
            speech_id,
            lambda record: _settle(record, SpeechDeliveryStatus.FAILED, reason),
        )

    async def mark_uncertain(self, speech_id: str, *, reason: str) -> SpeechDeliveryRecord:
        if not reason:
            raise ValueError("uncertain delivery reason must be non-empty")
        return await self._mutate(
            speech_id,
            lambda record: _settle(record, SpeechDeliveryStatus.UNCERTAIN, reason),
        )

    async def get(self, speech_id: str) -> SpeechDeliveryRecord | None:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"SELECT * FROM {self._table} WHERE speech_id = $1",
                speech_id,
            )
        return self._record(row) if row is not None else None

    async def latest_for_item(self, item_id: str) -> SpeechDeliveryRecord | None:
        if not item_id:
            raise ValueError("Conversation Item identity must be non-empty")
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._table}
                WHERE source_item_id = $1
                ORDER BY updated_at DESC, speech_id DESC
                LIMIT 1
                """,
                item_id,
            )
        return self._record(row) if row is not None else None

    async def _mutate(
        self,
        speech_id: str,
        transition: Callable[[SpeechDeliveryRecord], SpeechDeliveryRecord],
    ) -> SpeechDeliveryRecord:
        async with connection_scope(self._executor) as connection, connection.transaction():
            current = await self._get(connection, speech_id, for_update=True)
            candidate = transition(current)
            now = datetime.now(UTC)
            row = await connection.fetchrow(
                f"""
                UPDATE {self._table} SET
                    intended_spoken_content = $2,
                    delivered_speech_transcript = $3,
                    played_audio_end_us = $4,
                    status = $5,
                    precision = $6,
                    text_committed = $7,
                    reason = $8,
                    revision = revision + 1,
                    updated_at = $9
                WHERE speech_id = $1 AND revision = $10
                RETURNING *
                """,
                speech_id,
                candidate.intended_spoken_content,
                candidate.delivered_speech_transcript,
                candidate.played_audio_end_us,
                candidate.status.value,
                candidate.precision.value if candidate.precision is not None else None,
                candidate.text_committed,
                candidate.reason,
                now,
                current.revision,
            )
            if row is None:
                raise RuntimeError("speech delivery revision changed during locked transition")
            return self._record(row)

    async def _get(
        self,
        connection: Any,
        speech_id: str,
        *,
        for_update: bool = False,
    ) -> SpeechDeliveryRecord:
        suffix = " FOR UPDATE" if for_update else ""
        row = await connection.fetchrow(
            f"SELECT * FROM {self._table} WHERE speech_id = $1{suffix}",
            speech_id,
        )
        if row is None:
            raise KeyError(speech_id)
        return self._record(row)

    @staticmethod
    def _record(row: Mapping[str, Any]) -> SpeechDeliveryRecord:
        context = _decoded_json(row["context"])
        return SpeechDeliveryRecord(
            speech_id=row["speech_id"],
            context=InteractionContext(**context),
            source_item_id=row["source_item_id"],
            context_policy=SpeechContextPolicy(row["context_policy"]),
            interrupted_context_policy=InterruptedContextPolicy(
                row["interrupted_context_policy"]
            ),
            intended_spoken_content=row["intended_spoken_content"],
            delivered_speech_transcript=row["delivered_speech_transcript"],
            played_audio_end_us=row["played_audio_end_us"],
            status=SpeechDeliveryStatus(row["status"]),
            precision=(PlaybackPrecision(row["precision"]) if row["precision"] else None),
            text_committed=row["text_committed"],
            reason=row["reason"],
            revision=row["revision"],
            updated_at=row["updated_at"],
        )


def _settle(
    record: SpeechDeliveryRecord,
    status: SpeechDeliveryStatus,
    reason: str,
) -> SpeechDeliveryRecord:
    _require_active(record)
    return replace(record, status=status, reason=reason)


def _require_active(record: SpeechDeliveryRecord) -> None:
    if record.status.terminal:
        raise ValueError("speech delivery is already terminal")


def _same_identity(left: SpeechDeliveryRecord, right: SpeechDeliveryRecord) -> bool:
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


def _context_payload(context: InteractionContext) -> dict[str, object]:
    return {
        field: getattr(context, field)
        for field in InteractionContext.__dataclass_fields__
    }


def _decoded_json(value: Any) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise TypeError("speech delivery context must decode to an object")
    return decoded


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
