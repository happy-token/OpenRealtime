CREATE SCHEMA IF NOT EXISTS "__VOICEAGENT_SCHEMA__";

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".agent_tasks (
    worker_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    voice_session_id text NOT NULL,
    thread_id text NOT NULL,
    turn_id text NOT NULL,
    generation bigint NOT NULL CHECK (generation >= 0),
    delegation_request_id text NOT NULL,
    request_digest text NOT NULL CHECK (length(request_digest) = 64),
    semantic_fingerprint text NOT NULL CHECK (length(semantic_fingerprint) = 64),
    request_payload jsonb NOT NULL,
    context_payload jsonb NOT NULL,
    phase text NOT NULL CHECK (
        phase IN (
            'accepted', 'queued', 'starting', 'running', 'waiting',
            'cancelling', 'succeeded', 'failed', 'cancelled',
            'timed_out', 'unknown'
        )
    ),
    revision bigint NOT NULL CHECK (revision > 0),
    dedupe_guard boolean NOT NULL DEFAULT true,
    selected_agent text,
    selected_candidate_index integer CHECK (selected_candidate_index >= 0),
    backend_committed boolean NOT NULL DEFAULT false,
    dispatch_token text,
    handle_payload jsonb,
    blocker text,
    result text,
    error text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CHECK (NOT backend_committed OR dispatch_token IS NOT NULL),
    CHECK (phase <> 'succeeded' OR error IS NULL),
    CHECK (phase = 'succeeded' OR result IS NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_tasks_active_semantic_uidx
    ON "__VOICEAGENT_SCHEMA__".agent_tasks (
        tenant_id, thread_id, semantic_fingerprint
    )
    WHERE dedupe_guard AND phase IN (
        'accepted', 'queued', 'starting', 'running', 'waiting',
        'cancelling', 'unknown'
    );

CREATE INDEX IF NOT EXISTS agent_tasks_thread_created_idx
    ON "__VOICEAGENT_SCHEMA__".agent_tasks (tenant_id, thread_id, created_at);

CREATE INDEX IF NOT EXISTS agent_tasks_phase_updated_idx
    ON "__VOICEAGENT_SCHEMA__".agent_tasks (phase, updated_at)
    WHERE phase IN (
        'accepted', 'queued', 'starting', 'running', 'waiting',
        'cancelling', 'unknown'
    );

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".agent_task_request_keys (
    tenant_id text NOT NULL,
    thread_id text NOT NULL,
    delegation_request_id text NOT NULL,
    request_digest text NOT NULL CHECK (length(request_digest) = 64),
    worker_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, thread_id, delegation_request_id),
    CONSTRAINT agent_task_request_keys_worker_fk
        FOREIGN KEY (worker_id)
        REFERENCES "__VOICEAGENT_SCHEMA__".agent_tasks (worker_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS agent_task_request_keys_worker_idx
    ON "__VOICEAGENT_SCHEMA__".agent_task_request_keys (worker_id);

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".outbox_messages (
    outbox_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    message_type text NOT NULL,
    schema_version integer NOT NULL CHECK (schema_version > 0),
    dedupe_key text NOT NULL,
    payload jsonb NOT NULL,
    payload_digest text NOT NULL CHECK (length(payload_digest) = 64),
    status text NOT NULL CHECK (status IN ('pending', 'leased', 'delivered', 'dead')),
    available_at timestamptz NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_owner text,
    lease_expires_at timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    last_error text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    delivered_at timestamptz,
    UNIQUE (tenant_id, dedupe_key),
    CHECK (
        (status = 'leased' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR status <> 'leased'
    )
);

CREATE INDEX IF NOT EXISTS outbox_claim_idx
    ON "__VOICEAGENT_SCHEMA__".outbox_messages (status, available_at, created_at)
    WHERE status IN ('pending', 'leased');

CREATE INDEX IF NOT EXISTS outbox_aggregate_idx
    ON "__VOICEAGENT_SCHEMA__".outbox_messages (
        tenant_id, aggregate_type, aggregate_id, created_at
    );
