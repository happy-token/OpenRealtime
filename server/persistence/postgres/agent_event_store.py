"""PostgreSQL canonical Agent event stream and durable cursor."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from server.agent_session.driver_protocol import AgentEvent, utc_now
from server.agent_session.event_store import (
    AgentEventAppendResult,
    AgentEventConflict,
    AgentEventGap,
    AgentEventRecord,
    agent_event_digest,
    agent_event_kind,
    decode_agent_event,
    encode_agent_event,
)
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name


class PostgresAgentEventStore:
    def __init__(self, executor: Any, *, schema: str = "voiceagent") -> None:
        self._executor = executor
        validated = validate_schema_name(schema)
        self._events = f'"{validated}".agent_events'
        self._cursors = f'"{validated}".agent_event_cursors'

    async def append(self, event: AgentEvent) -> AgentEventAppendResult:
        if not event.worker_id or not event.event_id:
            raise ValueError("Agent event worker_id and event_id must be non-empty")
        digest = agent_event_digest(event)
        now = utc_now()
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                await connection.execute(
                    f"""
                    INSERT INTO {self._cursors} (
                        worker_id, last_sequence, updated_at
                    )
                    VALUES ($1, 0, $2)
                    ON CONFLICT (worker_id) DO NOTHING
                    """,
                    event.worker_id,
                    now,
                )
                cursor = await connection.fetchrow(
                    f"""
                    SELECT last_sequence FROM {self._cursors}
                    WHERE worker_id = $1
                    FOR UPDATE
                    """,
                    event.worker_id,
                )
                if cursor is None:
                    raise RuntimeError("Agent event cursor disappeared")
                existing = await connection.fetchrow(
                    f"""
                    SELECT * FROM {self._events}
                    WHERE worker_id = $1 AND event_id = $2
                    """,
                    event.worker_id,
                    event.event_id,
                )
                if existing is not None:
                    if existing["event_digest"] != digest:
                        raise AgentEventConflict(
                            f"Agent event {event.event_id!r} was reused with different content"
                        )
                    return AgentEventAppendResult(self._record(existing), created=False)

                expected = int(cursor["last_sequence"]) + 1
                if event.sequence != expected:
                    raise AgentEventGap(expected=expected, actual=event.sequence)
                row = await connection.fetchrow(
                    f"""
                    INSERT INTO {self._events} (
                        worker_id, event_id, sequence, kind, driver_kind,
                        backend_session_id, backend_run_id, event_payload,
                        event_digest, occurred_at, ingested_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8::jsonb,
                        $9, $10, $11
                    )
                    RETURNING *
                    """,
                    event.worker_id,
                    event.event_id,
                    event.sequence,
                    agent_event_kind(event),
                    event.locator.driver_kind,
                    event.locator.backend_session_id,
                    event.locator.backend_run_id,
                    _json(encode_agent_event(event)),
                    digest,
                    event.occurred_at,
                    now,
                )
                await connection.execute(
                    f"""
                    UPDATE {self._cursors}
                    SET last_sequence = $2, last_event_id = $3, updated_at = $4
                    WHERE worker_id = $1
                    """,
                    event.worker_id,
                    event.sequence,
                    event.event_id,
                    now,
                )
                if row is None:  # pragma: no cover - INSERT RETURNING contract
                    raise RuntimeError("Agent event insert returned no row")
                return AgentEventAppendResult(self._record(row), created=True)

    async def last_sequence(self, worker_id: str) -> int:
        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        async with connection_scope(self._executor) as connection:
            sequence = await connection.fetchval(
                f"SELECT last_sequence FROM {self._cursors} WHERE worker_id = $1",
                worker_id,
            )
            return int(sequence or 0)

    async def list_events(
        self,
        worker_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> tuple[AgentEventRecord, ...]:
        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        async with connection_scope(self._executor) as connection:
            rows = await connection.fetch(
                f"""
                SELECT * FROM {self._events}
                WHERE worker_id = $1 AND sequence > $2
                ORDER BY sequence
                LIMIT $3
                """,
                worker_id,
                after_sequence,
                limit,
            )
            return tuple(self._record(row) for row in rows)

    @staticmethod
    def _record(row: Mapping[str, Any]) -> AgentEventRecord:
        payload = row["event_payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError("Agent event payload must decode to an object")
        return AgentEventRecord(
            event=decode_agent_event(payload),
            event_digest=row["event_digest"],
            ingested_at=row["ingested_at"],
        )


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
