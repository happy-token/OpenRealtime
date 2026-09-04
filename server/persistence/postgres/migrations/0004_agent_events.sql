CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".agent_event_cursors (
    worker_id text PRIMARY KEY,
    last_sequence bigint NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    last_event_id text,
    updated_at timestamptz NOT NULL,
    CONSTRAINT agent_event_cursors_worker_fk
        FOREIGN KEY (worker_id)
        REFERENCES "__VOICEAGENT_SCHEMA__".agent_tasks (worker_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".agent_events (
    worker_id text NOT NULL,
    event_id text NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    kind text NOT NULL,
    driver_kind text NOT NULL,
    backend_session_id text NOT NULL,
    backend_run_id text,
    event_payload jsonb NOT NULL CHECK (jsonb_typeof(event_payload) = 'object'),
    event_digest text NOT NULL CHECK (length(event_digest) = 64),
    occurred_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL,
    PRIMARY KEY (worker_id, event_id),
    UNIQUE (worker_id, sequence),
    CONSTRAINT agent_events_worker_fk
        FOREIGN KEY (worker_id)
        REFERENCES "__VOICEAGENT_SCHEMA__".agent_tasks (worker_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS agent_events_worker_sequence_idx
    ON "__VOICEAGENT_SCHEMA__".agent_events (worker_id, sequence);
