from server.observability.module_health import module_health


def test_missing_connection_instrumentation_does_not_become_zero():
    result = {row["module"]: row for row in module_health([])}
    assert result["tts"]["disconnect_count"] is None
    assert result["llm"]["error_count"] is None


def test_provider_failure_is_not_counted_again_as_capability_failure():
    result = {row["module"]: row for row in module_health([
        {"name": "provider.deepseek.responses.stream", "outcome": "timeout", "count": 1},
        {"name": "realtime.capability.brain", "outcome": "timeout", "count": 1},
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
