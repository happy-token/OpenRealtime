CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".runtime_telemetry_records (
    event_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    device_id text NOT NULL,
    voice_session_id text NOT NULL,
    thread_id text NOT NULL,
    generation bigint CHECK (generation IS NULL OR generation >= 0),
    turn_id text,
    response_id text,
    call_id text,
    worker_id text,
    sequence bigint NOT NULL CHECK (sequence > 0),
    name text NOT NULL,
    kind text NOT NULL CHECK (
        kind IN ('event', 'span', 'milestone', 'terminal', 'provider_call')
    ),
    outcome text NOT NULL CHECK (
        outcome IN (
            'ok', 'timeout', 'error', 'cancelled',
            'superseded', 'degraded', 'no_response'
        )
    ),
    severity text NOT NULL CHECK (
        severity IN ('debug', 'info', 'warning', 'error')
    ),
    occurred_at timestamptz NOT NULL,
    monotonic_ns bigint NOT NULL CHECK (monotonic_ns >= 0),
    duration_ms double precision CHECK (duration_ms IS NULL OR duration_ms >= 0),
    timeout_ms double precision CHECK (timeout_ms IS NULL OR timeout_ms >= 0),
    error_type text,
    error_message text,
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(attributes) = 'object'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS runtime_telemetry_time_name_idx
    ON "__VOICEAGENT_SCHEMA__".runtime_telemetry_records (
        occurred_at DESC, name
    );

CREATE INDEX IF NOT EXISTS runtime_telemetry_session_sequence_idx
    ON "__VOICEAGENT_SCHEMA__".runtime_telemetry_records (
        tenant_id, voice_session_id, sequence
    );

CREATE INDEX IF NOT EXISTS runtime_telemetry_outcome_idx
    ON "__VOICEAGENT_SCHEMA__".runtime_telemetry_records (
        outcome, occurred_at DESC
    )
    WHERE outcome <> 'ok';

CREATE INDEX IF NOT EXISTS runtime_telemetry_provider_call_idx
    ON "__VOICEAGENT_SCHEMA__".runtime_telemetry_records (
        occurred_at DESC,
        (attributes->>'provider'),
        (attributes->>'operation')
    )
    WHERE kind = 'provider_call';
