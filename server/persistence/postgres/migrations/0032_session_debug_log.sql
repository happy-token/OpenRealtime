CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".session_debug_log (
    event_id text PRIMARY KEY,
    voice_session_id text NOT NULL,
    generation bigint CHECK (generation IS NULL OR generation >= 0),
    turn_id text,
    sequence bigint NOT NULL CHECK (sequence > 0),
    stage text NOT NULL CHECK (stage <> ''),
    event text NOT NULL CHECK (event <> ''),
    summary text NOT NULL CHECK (summary <> ''),
    occurred_at timestamptz NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(detail) = 'object'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS session_debug_log_session_sequence_idx
    ON "__VOICEAGENT_SCHEMA__".session_debug_log (
        voice_session_id, sequence
    );

CREATE INDEX IF NOT EXISTS session_debug_log_time_idx
    ON "__VOICEAGENT_SCHEMA__".session_debug_log (
        occurred_at DESC
    );
