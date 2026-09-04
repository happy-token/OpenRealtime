from server.persistence.postgres.schema import render_migrations


def test_runtime_telemetry_migration_has_query_and_session_indexes() -> None:
    migration = next(
        sql for sql in render_migrations("voiceagent_test") if "runtime_telemetry_records" in sql
    )

    assert '"voiceagent_test".runtime_telemetry_records' in migration
    assert "runtime_telemetry_time_name_idx" in migration
    assert "runtime_telemetry_session_sequence_idx" in migration
    assert "runtime_telemetry_outcome_idx" in migration
