from server.observability.module_health import module_health


def test_missing_connection_instrumentation_does_not_become_zero():
    result = {row["module"]: row for row in module_health([])}
    assert result["tts"]["disconnect_count"] is None
    assert result["llm"]["error_count"] is None


def test_provider_failure_is_not_counted_again_as_capability_failure():
    result = {row["module"]: row for row in module_health([
        {"name": "provider.deepseek.responses.stream", "outcome": "timeout", "count": 1, "voice_session_id": "s", "call_id": "same-incident"},
        {"name": "realtime.capability.brain", "outcome": "timeout", "count": 1, "voice_session_id": "s", "call_id": "same-incident"},
        {"name": "provider.deepseek.responses.stream", "outcome": "cancelled", "count": 2},
    ])}
    assert result["llm"]["timeout_count"] == 1
    assert result["llm"]["error_count"] == 0


def test_connection_recovery_uses_completed_attempts_and_unique_sessions():
    result = {row["module"]: row for row in module_health([
        {"name": "transport.collection_ready", "outcome": "ok"},
        {"name": "transport.disconnected", "outcome": "ok", "voice_session_id": "s"},
        {"name": "transport.disconnected", "outcome": "ok", "voice_session_id": "s"},
        {"name": "transport.recovered", "outcome": "ok"},
        {"name": "transport.recovery_failed", "outcome": "error"},
    ])}
    assert result["transport"]["disconnect_count"] == 2
    assert result["transport"]["affected_session_count"] == 1
    assert result["transport"]["recovery_rate"] == 0.5


def test_unrelated_capability_failure_is_not_hidden_by_another_session_provider():
    health = {row["module"]: row for row in module_health([
        {"name": "provider.deepseek.responses.stream", "outcome": "timeout", "voice_session_id": "A", "call_id": "A"},
        {"name": "realtime.capability.brain", "outcome": "timeout", "voice_session_id": "B", "call_id": "B"},
    ])}
    assert health["llm"]["timeout_count"] == 2


def test_explicit_same_incident_deduplicates_disconnect_as_well_as_error():
    common = {"outcome": "error", "error_type": "ConnectionResetError", "voice_session_id": "A", "call_id": "incident"}
    health = {row["module"]: row for row in module_health([
        {**common, "name": "provider.asr.listen"},
        {**common, "name": "realtime.capability.asr"},
    ])}
    assert health["asr"]["error_count"] == 1
    assert health["asr"]["disconnect_count"] == 1


def test_missing_causal_identity_does_not_suppress_a_possible_independent_failure():
    health = {row["module"]: row for row in module_health([
        {"name": "provider.asr.listen", "outcome": "error", "voice_session_id": "A"},
        {"name": "realtime.capability.asr", "outcome": "error", "voice_session_id": "A"},
    ])}
    assert health["asr"]["error_count"] == 2


async def verify_recorded_health(store):
    from datetime import timedelta

    from server.observability.telemetry import (
        DiagnosticsWindow,
        RuntimeTelemetry,
        TelemetryIdentity,
        TelemetryOutcome,
    )

    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    try:
        a = telemetry.bind(TelemetryIdentity(tenant_id="tenant", user_id="user", device_id="device", voice_session_id="A", thread_id="thread"))
        b = telemetry.bind(TelemetryIdentity(tenant_id="tenant", user_id="user", device_id="device", voice_session_id="B", thread_id="thread"))
        for name in ("provider.asr.listen", "realtime.capability.asr"):
            a.record(name, outcome=TelemetryOutcome.ERROR, error=ConnectionResetError(), call_id="asr-incident")
        a.record("provider.deepseek.responses.stream", outcome=TelemetryOutcome.TIMEOUT, call_id="llm-A")
        b.record("realtime.capability.brain", outcome=TelemetryOutcome.TIMEOUT, call_id="llm-B")
        await telemetry.flush()
        overview = await store.overview(DiagnosticsWindow.last(timedelta(hours=1)))
        health = {row["module"]: row for row in overview.module_health}
        assert health["asr"]["error_count"] == 1 and health["asr"]["disconnect_count"] == 1
        assert health["llm"]["timeout_count"] == 2
    finally:
        await telemetry.close()


async def test_memory_overview_preserves_causal_identity_for_health():
    from server.observability.telemetry import InMemoryTelemetryStore

    await verify_recorded_health(InMemoryTelemetryStore())
