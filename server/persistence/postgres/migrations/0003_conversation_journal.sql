CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".conversation_threads (
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    thread_id text NOT NULL,
    version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, user_id, thread_id)
);

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".conversation_items (
    item_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    device_id text NOT NULL,
    voice_session_id text NOT NULL,
    thread_id text NOT NULL,
    turn_id text NOT NULL,
    generation bigint NOT NULL CHECK (generation >= 0),
    response_id text,
    call_id text,
    worker_id text,
    confirmation_id text,
    handoff_id text,
    sequence bigint NOT NULL CHECK (sequence > 0),
    schema_version integer NOT NULL CHECK (schema_version > 0),
    kind text NOT NULL CHECK (
        kind IN (
            'session.opened', 'session.resumed', 'session.closed',
            'user.input', 'assistant.output',
            'tool.requested', 'tool.result',
            'delegation.requested', 'delegation.progress', 'delegation.result',
            'confirmation.requested', 'confirmation.decided',
            'context.summary', 'context.correction', 'context.redaction'
        )
    ),
    status text NOT NULL CHECK (
        status IN (
            'committed', 'in_progress', 'completed',
            'failed', 'cancelled', 'interrupted'
        )
    ),
    producer text NOT NULL,
    content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'array'),
    visibility text[] NOT NULL CHECK (cardinality(visibility) > 0),
    parent_item_id text,
    provider_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(provider_metadata) = 'object'),
    item_digest text NOT NULL CHECK (length(item_digest) = 64),
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    UNIQUE (tenant_id, user_id, thread_id, sequence),
    CONSTRAINT conversation_items_thread_fk
        FOREIGN KEY (tenant_id, user_id, thread_id)
        REFERENCES "__VOICEAGENT_SCHEMA__".conversation_threads (
            tenant_id, user_id, thread_id
        )
);

CREATE INDEX IF NOT EXISTS conversation_items_thread_read_idx
    ON "__VOICEAGENT_SCHEMA__".conversation_items (
        tenant_id, user_id, thread_id, sequence
    );

CREATE INDEX IF NOT EXISTS conversation_items_worker_idx
    ON "__VOICEAGENT_SCHEMA__".conversation_items (
        tenant_id, worker_id, sequence
    )
    WHERE worker_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS conversation_items_call_idx
    ON "__VOICEAGENT_SCHEMA__".conversation_items (
        tenant_id, call_id, sequence
    )
    WHERE call_id IS NOT NULL;
