"""PostgreSQL adapter for the session debug log (narrative troubleshooting
facts, distinct from runtime_telemetry's numeric latency samples)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from server.observability.telemetry import DebugLogEntry
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name

_SESSION_TIMELINE_LIMIT = 2000


class PostgresDebugLogStore:
    """One adapter implements both the write and timeline query interfaces."""

    def __init__(self, executor: Any, *, schema: str = "voiceagent") -> None:
        self._executor = executor
        validated = validate_schema_name(schema)
        self._entries = f'"{validated}".session_debug_log'

    async def append_batch(self, entries: Sequence[DebugLogEntry]) -> None:
        if not entries:
            return
        values = [
            (
                entry.event_id,
                entry.voice_session_id,
                entry.generation,
                entry.turn_id,
                entry.sequence,
                entry.stage,
                entry.event,
                entry.summary,
                entry.occurred_at,
                _json(entry.detail),
            )
            for entry in entries
        ]
        async with connection_scope(self._executor) as connection:
            await connection.executemany(
                f"""
                INSERT INTO {self._entries} (
                    event_id, voice_session_id, generation, turn_id,
                    sequence, stage, event, summary, occurred_at, detail
                )
                VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7, $8, $9, $10::jsonb
                )
                ON CONFLICT (event_id) DO NOTHING
                """,
                values,
            )

    async def delete_sessions(self, voice_session_ids: Sequence[str]) -> int:
        selected = list(dict.fromkeys(voice_session_ids))
        if not selected:
            return 0
        async with connection_scope(self._executor) as connection:
            rows = await connection.fetch(
                f"DELETE FROM {self._entries} WHERE voice_session_id = ANY($1::text[]) RETURNING voice_session_id",
                selected,
            )
        return len({row["voice_session_id"] for row in rows})

    async def session_timeline(
        self, voice_session_id: str, *, limit: int = 2000, after_event_id: str | None = None
    ) -> tuple[DebugLogEntry, ...]:
        if not voice_session_id:
            raise ValueError("voice_session_id must be non-empty")
        if not 1 <= limit <= _SESSION_TIMELINE_LIMIT:
            raise ValueError(
                f"debug log limit must be between 1 and {_SESSION_TIMELINE_LIMIT}"
            )
        async with connection_scope(self._executor) as connection:
            cursor_clause = ""
            args = [voice_session_id, limit]
            if after_event_id is not None:
                anchor = await connection.fetchrow(f"SELECT event_id FROM {self._entries} WHERE voice_session_id = $1 AND event_id = $2", voice_session_id, after_event_id)
                if anchor is None:
                    raise ValueError("unknown debug log cursor")
                cursor_clause = f"AND (sequence, event_id) > (SELECT sequence, event_id FROM {self._entries} WHERE voice_session_id = $1 AND event_id = $3)"
                args.append(after_event_id)
            rows = await connection.fetch(
                f"""
                SELECT * FROM {self._entries}
                WHERE voice_session_id = $1
                {cursor_clause}
                ORDER BY sequence, event_id
                LIMIT $2
                """,
                *args,
            )
        return tuple(_entry(row) for row in rows)


def _entry(row: Mapping[str, Any]) -> DebugLogEntry:
    detail = row["detail"]
    if isinstance(detail, str):
        detail = json.loads(detail)
    if not isinstance(detail, dict):
        raise TypeError("debug log detail must decode to an object")
    return DebugLogEntry(
        event_id=row["event_id"],
        voice_session_id=row["voice_session_id"],
        sequence=int(row["sequence"]),
        stage=row["stage"],
        event=row["event"],
        summary=row["summary"],
        occurred_at=row["occurred_at"],
        generation=row["generation"],
        turn_id=row["turn_id"],
        detail=detail,
    )


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
