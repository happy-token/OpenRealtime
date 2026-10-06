-- Additive playback fact ledger. Keep on application rollback; removal requires
-- a separate reviewed forward migration after recovery no longer depends on it.
-- No foreign key: a precise stop can target output whose first audio never arrived.
CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".speech_output_stop_records (
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    device_id text NOT NULL,
    voice_session_id text NOT NULL,
    thread_id text NOT NULL,
    stop_command_id text NOT NULL,
    state text NOT NULL CHECK (state IN ('STOP_REQUESTED', 'STOP_CONFIRMED', 'STOP_UNKNOWN')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    revision bigint NOT NULL CHECK (revision >= 1),
    PRIMARY KEY (tenant_id, user_id, device_id, voice_session_id, thread_id, stop_command_id)
);
