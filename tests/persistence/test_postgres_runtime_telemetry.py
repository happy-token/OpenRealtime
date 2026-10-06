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


async def test_precise_stop_identity_survives_postgres_adapter_write_and_session_read():
    columns = ("event_id", "tenant_id", "user_id", "device_id", "voice_session_id",
               "thread_id", "generation", "turn_id", "response_id", "call_id", "worker_id",
               "sequence", "name", "kind", "outcome", "severity", "occurred_at",
               "monotonic_ns", "duration_ms", "timeout_ms", "error_type", "error_message",
               "attributes")

    class RoundTripExecutor(RecordingExecutor):
        async def fetch(self, query, *args):
            assert "WHERE voice_session_id = $1" in query
            assert args == ("voice-1", 5001)
            return [dict(zip(columns, row, strict=True)) for row in self.args]

        async def fetchrow(self, query, *args):
            assert args == ("voice-1",)
            return {"voice_session_id": "voice-1", "first_event_at": timestamp,
                    "last_event_at": timestamp, "turn_count": 0, "timeout_count": 0,
                    "error_count": 0, "no_response_count": 0, "event_count": 1}

    timestamp = datetime(2026, 10, 7, tzinfo=UTC)
    executor = RoundTripExecutor()
    store = PostgresTelemetryStore(executor)
    record = TelemetryRecord(event_id="stop-fact", sequence=1, name="playback.stop_receipt",
        kind=TelemetryKind.EVENT, outcome=TelemetryOutcome.OK, severity=TelemetrySeverity.INFO,
        tenant_id="tenant-1", user_id="user-1", device_id="browser", voice_session_id="voice-1",
        thread_id="thread-1", generation=3, turn_id="original-turn", response_id="response-1",
        call_id="stop-1", worker_id=None, occurred_at=timestamp, monotonic_ns=1200,
        duration_ms=None, timeout_ms=1500, attributes={"stop_command_id": "stop-1",
            "output_epoch": "epoch-1", "speech_id": "response:response-1",
            "state": "STOP_CONFIRMED", "played_position_samples": 1200,
            "handoff": "pending", "received_at": timestamp.isoformat()})
    await store.append_batch((record,))
    detail = await store.session_detail("voice-1")
    assert detail is not None
    assert detail.events == (record,)
    assert detail.summary.turn_count == 0
