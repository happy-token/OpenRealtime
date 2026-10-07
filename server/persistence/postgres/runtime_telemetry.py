"""PostgreSQL adapter for runtime telemetry writes and diagnostics reads."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from server.observability.telemetry import (
    DiagnosticsOverview,
    DiagnosticsWindow,
    MetricAggregate,
    ReceiptKey,
    SessionDetail,
    SessionSummary,
    TelemetryKind,
    TelemetryOutcome,
    TelemetryRecord,
    TelemetrySeverity,
)
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.conversation_journal import _session_statement_timeout
from server.persistence.postgres.schema import validate_schema_name

_SESSION_EVENT_LIMIT = 5000


async def validate_playback_lookup_index(conn: Any, schema: str) -> None:
    # Deparsed expressions depend on visibility in search_path. Normalize only
    # inside this SAVEPOINT and restore the caller's successful transaction state.
    async with conn.transaction():
        previous = await conn.fetchval("SHOW search_path")
        await conn.execute("SELECT pg_catalog.set_config('search_path','pg_catalog',true)")
        await _validate_playback_lookup_index_expression(conn, schema)
        await conn.execute("SELECT pg_catalog.set_config('search_path',$1,true)", previous)


async def _validate_playback_lookup_index_expression(conn: Any, schema: str) -> None:
    quoted = await conn.fetchval("SELECT quote_ident($1)", validate_schema_name(schema))
    position = f"{quoted}.recording_playback_sample_position"
    attachment = f"{quoted}.recording_playback_attachment_key"
    valid = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=$1 "
        "AND c.relname='runtime_playback_attachment_idx' AND i.indisvalid AND i.indisready "
        "AND NOT i.indisunique AND NOT i.indisexclusion "
        "AND i.indrelid=to_regclass($2) AND i.indnkeyatts=2 AND i.indnatts=2 "
        "AND i.indkey::text='0 0' AND i.indoption::text='0 3' "
        "AND pg_get_expr(i.indpred, i.indrelid, true)=$3 "
        "AND pg_get_expr(i.indexprs, i.indrelid, true)=$4 "
        "AND ARRAY(SELECT DISTINCT d.refobjid FROM pg_depend d WHERE d.classid='pg_class'::regclass "
        "AND d.objid=i.indexrelid AND d.refclassid='pg_proc'::regclass ORDER BY d.refobjid) "
        "= ARRAY(SELECT p.oid FROM pg_proc p JOIN pg_namespace pn ON pn.oid=p.pronamespace "
        "WHERE pn.nspname=$1 AND p.proname IN ('recording_playback_attachment_key',"
        "'recording_playback_sample_position') ORDER BY p.oid))",
        schema,
        f'"{schema}".runtime_telemetry_records',
        f"name = 'client.playback_progress'::text AND outcome = 'ok'::text AND {position}(attributes) IS NOT NULL",
        f"{attachment}(tenant_id, user_id, voice_session_id, thread_id, generation, turn_id, response_id, attributes), {position}(attributes)",
    )
    if not valid:
        raise RuntimeError("playback attachment index is missing, invalid or incompatible")


class PostgresTelemetryStore:
    """One adapter implements both the write and diagnostics query interfaces."""

    def __init__(self, executor: Any, *, schema: str = "voiceagent") -> None:
        self._executor = executor
        validated = validate_schema_name(schema)
        self._records = f'"{validated}".runtime_telemetry_records'
        self._schema = validated

    async def playback_receipts_for(self, keys: Sequence[ReceiptKey]) -> dict[ReceiptKey, int]:
        from server.observability.recording_playback import validated_receipt_keys

        selected = validated_receipt_keys(keys)
        if not selected:
            return {}
        fields = (
            "tenant",
            "owner",
            "session",
            "thread",
            "generation",
            "turn",
            "response",
            "epoch",
            "speech",
            "rate",
        )
        payload = json.dumps([dict(zip(fields, key, strict=True)) for key in selected])
        schema = f'"{self._schema}"'
        position = f"{schema}.recording_playback_sample_position"
        attachment = f"{schema}.recording_playback_attachment_key"
        async with asyncio.timeout(4), connection_scope(self._executor) as conn, conn.transaction():
            previous = await conn.fetchval("SHOW statement_timeout")
            await conn.execute(
                "SELECT set_config('statement_timeout', $1, true)",
                _session_statement_timeout(previous),
            )
            await validate_playback_lookup_index(conn, self._schema)
            rows = await conn.fetch(
                f"""WITH wanted AS MATERIALIZED (
                    SELECT * FROM jsonb_to_recordset($1::jsonb) AS q(
                        tenant text, owner text, session text, thread text, generation bigint,
                        turn text, response text, epoch text, speech text, rate integer)
                ) SELECT q.*, hit.position FROM wanted q
                JOIN LATERAL (
                    SELECT {position}(r.attributes) AS position FROM {self._records} r
                    WHERE r.name='client.playback_progress' AND r.outcome='ok'
                        AND {position}(r.attributes) IS NOT NULL
                        AND {attachment}(r.tenant_id,r.user_id,r.voice_session_id,r.thread_id,
                            r.generation,r.turn_id,r.response_id,r.attributes) =
                            {attachment}(q.tenant,q.owner,q.session,q.thread,q.generation,q.turn,q.response,
                                jsonb_build_object('output_epoch',q.epoch,'speech_id',q.speech,'sample_rate_hz',q.rate))
                        AND r.tenant_id=q.tenant AND r.user_id=q.owner AND r.voice_session_id=q.session
                        AND r.thread_id=q.thread AND r.generation=q.generation
                        AND r.turn_id IS NOT DISTINCT FROM q.turn AND r.response_id IS NOT DISTINCT FROM q.response
                        AND r.attributes->>'output_epoch'=q.epoch AND r.attributes->>'speech_id'=q.speech
                        AND r.attributes->'sample_rate_hz'=to_jsonb(q.rate)
                    ORDER BY {position}(r.attributes) DESC LIMIT 1
                ) hit ON true""",
                payload,
            )
            # Successful nested SAVEPOINTs retain SET LOCAL unless explicitly restored.
            await conn.execute("SELECT set_config('statement_timeout', $1, true)", previous)
        return {tuple(row[field] for field in fields): row["position"] for row in rows}

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
                    count(*) FILTER (WHERE outcome = 'degraded') AS degraded_count,
                    count(DISTINCT (voice_session_id, coalesce(response_id, turn_id, generation::text))) FILTER (WHERE kind='terminal' AND outcome IN ('error','timeout','no_response')) AS failed_turn_count
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
            failure_rows = await connection.fetch(
                f"""SELECT substring(name from 21) AS capability,
                    count(*) FILTER (WHERE outcome = 'error') AS error_count,
                    count(*) FILTER (WHERE outcome = 'timeout') AS timeout_count
                FROM {self._records}
                WHERE occurred_at >= $1 AND ($2::timestamptz IS NULL OR occurred_at <= $2)
                    AND name LIKE 'realtime.capability.%' AND outcome IN ('error','timeout')
                GROUP BY name ORDER BY name""",
                window.since,
                window.until,
            )
            health_rows = await connection.fetch(
                f"""SELECT name, outcome, error_type, tenant_id, user_id, voice_session_id, call_id, attributes->>'incident_id' AS incident_id, count(*) AS count
                FROM {self._records} WHERE occurred_at >= $1 AND ($2::timestamptz IS NULL OR occurred_at <= $2)
                GROUP BY name, outcome, error_type, tenant_id, user_id, voice_session_id, call_id, attributes->>'incident_id'""",
                window.since,
                window.until,
            )
        from server.observability.module_health import module_health

        resolved_summary = summary or {}
        return DiagnosticsOverview(
            since=window.since,
            until=window.until or datetime.now(UTC),
            session_count=int(resolved_summary.get("session_count") or 0),
            turn_count=int(resolved_summary.get("turn_count") or 0),
            successful_turn_count=int(resolved_summary.get("successful_turn_count") or 0),
            no_response_count=int(resolved_summary.get("no_response_count") or 0),
            timeout_count=int(resolved_summary.get("timeout_count") or 0),
            error_count=int(resolved_summary.get("error_count") or 0),
            cancelled_count=int(resolved_summary.get("cancelled_count") or 0),
            interrupted_count=int(resolved_summary.get("interrupted_count") or 0),
            degraded_count=int(resolved_summary.get("degraded_count") or 0),
            metrics=tuple(_metric(row) for row in metric_rows),
            module_health=module_health(health_rows),
            latency_collection_ready=any(
                row["name"] == "interaction.collection_ready" for row in health_rows
            ),
            failed_turn_count=int(resolved_summary.get("failed_turn_count") or 0),
            capability_failures=tuple(
                {
                    "capability": str(row["capability"]),
                    "error_count": int(row["error_count"]),
                    "timeout_count": int(row["timeout_count"]),
                }
                for row in failure_rows
            ),
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
                    count(*) AS event_count,
                    count(*) FILTER (WHERE name='transport.disconnected') AS disconnect_count,
                    array_agg(DISTINCT name) FILTER (WHERE outcome IN ('error','timeout') OR name='transport.disconnected') AS failure_names
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

    async def session_detail(
        self, voice_session_id: str, *, after_event_id: str | None = None
    ) -> SessionDetail | None:
        if not voice_session_id:
            raise ValueError("voice_session_id must be non-empty")
        async with connection_scope(self._executor) as connection:
            cursor_clause = ""
            args = [voice_session_id, _SESSION_EVENT_LIMIT + 1]
            if after_event_id is not None:
                anchor = await connection.fetchrow(
                    f"SELECT event_id FROM {self._records} WHERE voice_session_id = $1 AND event_id = $2",
                    voice_session_id,
                    after_event_id,
                )
                if anchor is None:
                    raise ValueError("unknown telemetry cursor")
                cursor_clause = f"AND (occurred_at, monotonic_ns, sequence, event_id) > (SELECT occurred_at, monotonic_ns, sequence, event_id FROM {self._records} WHERE voice_session_id = $1 AND event_id = $3)"
                args.append(after_event_id)
            rows = await connection.fetch(
                f"SELECT * FROM {self._records} WHERE voice_session_id = $1 {cursor_clause} ORDER BY occurred_at, monotonic_ns, sequence, event_id LIMIT $2",
                *args,
            )
            if not rows and after_event_id is None:
                return None
            records = tuple(_record(row) for row in rows[:_SESSION_EVENT_LIMIT])
            # Summary covers the whole session, independently of the displayed page.
            summary_row = await connection.fetchrow(
                f"""SELECT voice_session_id,
                min(occurred_at) AS first_event_at, max(occurred_at) AS last_event_at,
                count(*) FILTER (WHERE kind = 'terminal') AS turn_count,
                count(*) FILTER (WHERE outcome = 'timeout') AS timeout_count,
                count(*) FILTER (WHERE outcome = 'error') AS error_count,
                count(*) FILTER (WHERE kind = 'terminal' AND outcome = 'no_response') AS no_response_count,
                count(*) AS event_count FROM {self._records} WHERE voice_session_id = $1 GROUP BY voice_session_id""",
                voice_session_id,
            )
        if summary_row is None:
            return None
        return SessionDetail(
            summary=_session_summary(summary_row),
            events=records,
            next_cursor=records[-1].event_id if len(rows) > _SESSION_EVENT_LIMIT else None,
        )

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
        disconnect_count=int(row.get("disconnect_count") or 0),
        failure_names=tuple(row.get("failure_names") or ()),
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
        duration_ms=(float(row["duration_ms"]) if row["duration_ms"] is not None else None),
        timeout_ms=(float(row["timeout_ms"]) if row["timeout_ms"] is not None else None),
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
