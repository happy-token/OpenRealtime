from __future__ import annotations

from datetime import UTC, datetime

from server.observability.telemetry import (
    TelemetryKind,
    TelemetryOutcome,
    TelemetryRecord,
    TelemetrySeverity,
)
from server.persistence.postgres.runtime_telemetry import PostgresTelemetryStore


class RecordingExecutor:
    def __init__(self) -> None:
        self.query = ""
        self.args: list[tuple[object, ...]] = []

    async def executemany(self, query: str, args: list[tuple[object, ...]]) -> None:
        self.query = query
        self.args = args


async def test_postgres_telemetry_batches_redacted_json_records() -> None:
    executor = RecordingExecutor()
    store = PostgresTelemetryStore(executor, schema="voiceagent_test")
    record = TelemetryRecord(
        event_id="event-1",
        sequence=1,
        name="llm.first_token",
        kind=TelemetryKind.SPAN,
        outcome=TelemetryOutcome.OK,
        severity=TelemetrySeverity.INFO,
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="browser",
        voice_session_id="voice-1",
        thread_id="thread-1",
        generation=1,
        turn_id="turn-1",
        response_id="response-1",
        call_id=None,
        worker_id=None,
        occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
        monotonic_ns=100,
        duration_ms=321.0,
        timeout_ms=3000.0,
        attributes={"provider": "deepseek"},
    )

    await store.append_batch((record,))

    assert 'INSERT INTO "voiceagent_test".runtime_telemetry_records' in executor.query
    assert len(executor.args) == 1
    assert executor.args[0][0] == "event-1"
    assert executor.args[0][12:15] == ("llm.first_token", "span", "ok")
    assert executor.args[0][-1] == '{"provider":"deepseek"}'
