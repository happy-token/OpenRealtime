"""PostgreSQL adapter for runtime telemetry writes and diagnostics reads."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from server.observability.telemetry import (
    DiagnosticsOverview,
    DiagnosticsWindow,
    MetricAggregate,
    SessionDetail,
    SessionSummary,
    TelemetryKind,
    TelemetryOutcome,
    TelemetryRecord,
    TelemetrySeverity,
)
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name

_SESSION_EVENT_LIMIT = 5000


class PostgresTelemetryStore:
    """One adapter implements both the write and diagnostics query interfaces."""

    def __init__(self, executor: Any, *, schema: str = "voiceagent") -> None:
        self._executor = executor
        validated = validate_schema_name(schema)
        self._records = f'"{validated}".runtime_telemetry_records'

    async def append_batch(self, records: Sequence[TelemetryRecord]) -> None:
        if not records:
            return
        values = [
            (
                record.event_id,
                record.tenant_id,
                record.user_id,
                record.device_id,
                record.voice_session_id,
                record.thread_id,
                record.generation,
                record.turn_id,
                record.response_id,
                record.call_id,
                record.worker_id,
                record.sequence,
                record.name,
                record.kind.value,
                record.outcome.value,
                record.severity.value,
                record.occurred_at,
                record.monotonic_ns,
                record.duration_ms,
                record.timeout_ms,
                record.error_type,
                record.error_message,
                _json(record.attributes),
            )
            for record in records
        ]
        async with connection_scope(self._executor) as connection:
            await connection.executemany(
                f"""
                INSERT INTO {self._records} (
                    event_id, tenant_id, user_id, device_id,
                    voice_session_id, thread_id, generation, turn_id,
                    response_id, call_id, worker_id, sequence,
                    name, kind, outcome, severity, occurred_at, monotonic_ns,
                    duration_ms, timeout_ms, error_type, error_message, attributes
                )
                VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7, $8,
                    $9, $10, $11, $12,
                    $13, $14, $15, $16, $17, $18,
                    $19, $20, $21, $22, $23::jsonb
                )
                ON CONFLICT (event_id) DO NOTHING
                """,
                values,
            )

    async def overview(self, window: DiagnosticsWindow) -> DiagnosticsOverview:
        async with connection_scope(self._executor) as connection:
            summary = await connection.fetchrow(
                f"""
                SELECT
                    count(DISTINCT voice_session_id) AS session_count,
                    count(*) FILTER (WHERE kind = 'terminal') AS turn_count,
                    count(*) FILTER (
                        WHERE kind = 'terminal' AND outcome = 'ok'
                    ) AS successful_turn_count,
                    count(*) FILTER (
                        WHERE kind = 'terminal' AND outcome = 'no_response'
                    ) AS no_response_count,
                    count(*) FILTER (WHERE outcome = 'timeout') AS timeout_count,
                    count(*) FILTER (WHERE outcome = 'error') AS error_count,
                    count(*) FILTER (
                        WHERE kind = 'terminal'
                          AND outcome IN ('cancelled', 'superseded')
                          AND coalesce(error_message, '') NOT IN (
                              'text_barge_in',
                              'barge_in',
                              'barge_in_floor_claim',
                              'user_barge_in'
                          )
                    ) AS cancelled_count,
                    count(*) FILTER (
                        WHERE kind = 'terminal'
                          AND outcome IN ('cancelled', 'superseded')
                          AND coalesce(error_message, '') IN (
                              'text_barge_in',
                              'barge_in',
                              'barge_in_floor_claim',
                              'user_barge_in'
                          )
                    ) AS interrupted_count,
                    count(*) FILTER (WHERE outcome = 'degraded') AS degraded_count
                FROM {self._records}
                WHERE occurred_at >= $1
                  AND ($2::timestamptz IS NULL OR occurred_at <= $2)
                """,
                window.since,
                window.until,
            )
            metric_rows = await connection.fetch(
                f"""
                SELECT
                    name,
                    count(*) AS sample_count,
                    percentile_cont(0.50) WITHIN GROUP (
                        ORDER BY duration_ms
                    ) AS p50_ms,
                    percentile_cont(0.95) WITHIN GROUP (
                        ORDER BY duration_ms
                    ) AS p95_ms,
                    percentile_cont(0.99) WITHIN GROUP (
                        ORDER BY duration_ms
                    ) AS p99_ms,
                    max(duration_ms) AS max_ms,
                    count(*) FILTER (WHERE outcome = 'timeout') AS timeout_count,
                    count(*) FILTER (WHERE outcome = 'error') AS error_count,
                    count(*) FILTER (
                        WHERE outcome IN ('cancelled', 'superseded')
                    ) AS cancelled_count,
                    count(*) FILTER (WHERE outcome = 'degraded') AS degraded_count
                FROM {self._records}
                WHERE occurred_at >= $1
                  AND ($2::timestamptz IS NULL OR occurred_at <= $2)
                  AND duration_ms IS NOT NULL
                GROUP BY name
                ORDER BY name
                """,
                window.since,
                window.until,
            )
        resolved_summary = summary or {}
        return DiagnosticsOverview(
            since=window.since,
            until=window.until or datetime.now(UTC),
            session_count=int(resolved_summary.get("session_count") or 0),
            turn_count=int(resolved_summary.get("turn_count") or 0),
            successful_turn_count=int(
                resolved_summary.get("successful_turn_count") or 0
            ),
            no_response_count=int(resolved_summary.get("no_response_count") or 0),
            timeout_count=int(resolved_summary.get("timeout_count") or 0),
            error_count=int(resolved_summary.get("error_count") or 0),
            cancelled_count=int(resolved_summary.get("cancelled_count") or 0),
            interrupted_count=int(resolved_summary.get("interrupted_count") or 0),
            degraded_count=int(resolved_summary.get("degraded_count") or 0),
            metrics=tuple(_metric(row) for row in metric_rows),
        )

    async def list_sessions(
        self,
        window: DiagnosticsWindow,
        *,
        limit: int = 50,
    ) -> tuple[SessionSummary, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("session limit must be between 1 and 500")
        async with connection_scope(self._executor) as connection:
            rows = await connection.fetch(
                f"""
                SELECT
                    voice_session_id,
                    min(occurred_at) AS first_event_at,
                    max(occurred_at) AS last_event_at,
                    count(*) FILTER (WHERE kind = 'terminal') AS turn_count,
                    count(*) FILTER (WHERE outcome = 'timeout') AS timeout_count,
                    count(*) FILTER (WHERE outcome = 'error') AS error_count,
                    count(*) FILTER (
                        WHERE kind = 'terminal' AND outcome = 'no_response'
                    ) AS no_response_count,
                    count(*) AS event_count
                FROM {self._records}
                WHERE occurred_at >= $1
                  AND ($2::timestamptz IS NULL OR occurred_at <= $2)
                GROUP BY voice_session_id
                ORDER BY last_event_at DESC
                LIMIT $3
                """,
                window.since,
                window.until,
                limit,
            )
        return tuple(_session_summary(row) for row in rows)

    async def session_detail(self, voice_session_id: str) -> SessionDetail | None:
        if not voice_session_id:
            raise ValueError("voice_session_id must be non-empty")
        async with connection_scope(self._executor) as connection:
            rows = await connection.fetch(
                f"""
                SELECT * FROM {self._records}
                WHERE voice_session_id = $1
                ORDER BY occurred_at, monotonic_ns, sequence, event_id
                LIMIT $2
                """,
                voice_session_id,
                _SESSION_EVENT_LIMIT,
            )
        if not rows:
            return None
        records = tuple(_record(row) for row in rows)
        summary = SessionSummary(
            voice_session_id=voice_session_id,
            first_event_at=min(record.occurred_at for record in records),
            last_event_at=max(record.occurred_at for record in records),
            turn_count=sum(record.kind is TelemetryKind.TERMINAL for record in records),
            timeout_count=sum(
                record.outcome is TelemetryOutcome.TIMEOUT for record in records
            ),
            error_count=sum(record.outcome is TelemetryOutcome.ERROR for record in records),
            no_response_count=sum(
                record.kind is TelemetryKind.TERMINAL
                and record.outcome is TelemetryOutcome.NO_RESPONSE
                for record in records
            ),
            event_count=len(records),
        )
        return SessionDetail(summary=summary, events=records)

    async def delete_sessions(self, voice_session_ids: Sequence[str]) -> int:
        selected = tuple(dict.fromkeys(voice_session_ids))
        if not selected:
            return 0
        async with connection_scope(self._executor) as connection:
            rows = await connection.fetch(
                f"""
                DELETE FROM {self._records}
                WHERE voice_session_id = ANY($1::text[])
                RETURNING voice_session_id
                """,
                list(selected),
            )
        return len({str(row["voice_session_id"]) for row in rows})


def _metric(row: Mapping[str, Any]) -> MetricAggregate:
    return MetricAggregate(
        name=str(row["name"]),
        sample_count=int(row["sample_count"]),
        p50_ms=round(float(row["p50_ms"]), 3),
        p95_ms=round(float(row["p95_ms"]), 3),
        p99_ms=round(float(row["p99_ms"]), 3),
        max_ms=round(float(row["max_ms"]), 3),
        timeout_count=int(row["timeout_count"]),
        error_count=int(row["error_count"]),
        cancelled_count=int(row["cancelled_count"]),
        degraded_count=int(row["degraded_count"]),
    )


def _session_summary(row: Mapping[str, Any]) -> SessionSummary:
    return SessionSummary(
        voice_session_id=str(row["voice_session_id"]),
        first_event_at=row["first_event_at"],
        last_event_at=row["last_event_at"],
        turn_count=int(row["turn_count"]),
        timeout_count=int(row["timeout_count"]),
        error_count=int(row["error_count"]),
        no_response_count=int(row["no_response_count"]),
        event_count=int(row["event_count"]),
    )


def _record(row: Mapping[str, Any]) -> TelemetryRecord:
    attributes = row["attributes"]
    if isinstance(attributes, str):
        attributes = json.loads(attributes)
    if not isinstance(attributes, dict):
        raise TypeError("telemetry attributes must decode to an object")
    return TelemetryRecord(
        event_id=row["event_id"],
        sequence=int(row["sequence"]),
        name=row["name"],
        kind=TelemetryKind(row["kind"]),
        outcome=TelemetryOutcome(row["outcome"]),
        severity=TelemetrySeverity(row["severity"]),
        tenant_id=row["tenant_id"],
        user_id=row["user_id"],
        device_id=row["device_id"],
        voice_session_id=row["voice_session_id"],
        thread_id=row["thread_id"],
        generation=row["generation"],
        turn_id=row["turn_id"],
        response_id=row["response_id"],
        call_id=row["call_id"],
        worker_id=row["worker_id"],
        occurred_at=row["occurred_at"],
        monotonic_ns=int(row["monotonic_ns"]),
        duration_ms=(
            float(row["duration_ms"]) if row["duration_ms"] is not None else None
        ),
        timeout_ms=(
            float(row["timeout_ms"]) if row["timeout_ms"] is not None else None
        ),
        error_type=row["error_type"],
        error_message=row["error_message"],
        attributes=attributes,
    )


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
