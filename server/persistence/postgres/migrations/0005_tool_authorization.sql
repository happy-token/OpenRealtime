CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".tool_policy_decisions (
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    voice_session_id text NOT NULL,
    thread_id text NOT NULL,
    call_id text NOT NULL,
    request_digest text NOT NULL CHECK (length(request_digest) = 64),
    request_payload jsonb NOT NULL CHECK (jsonb_typeof(request_payload) = 'object'),
    policy_context_payload jsonb NOT NULL
        CHECK (jsonb_typeof(policy_context_payload) = 'object'),
    decision_payload jsonb NOT NULL CHECK (jsonb_typeof(decision_payload) = 'object'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, user_id, voice_session_id, thread_id, call_id)
);

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".tool_pending_confirmations (
    confirmation_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    voice_session_id text NOT NULL,
    thread_id text NOT NULL,
    call_id text NOT NULL,
    pending_payload jsonb NOT NULL CHECK (jsonb_typeof(pending_payload) = 'object'),
    request_payload jsonb NOT NULL CHECK (jsonb_typeof(request_payload) = 'object'),
    policy_context_payload jsonb NOT NULL
        CHECK (jsonb_typeof(policy_context_payload) = 'object'),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    resolution_payload jsonb CHECK (
        resolution_payload IS NULL OR jsonb_typeof(resolution_payload) = 'object'
    ),
    created_at timestamptz NOT NULL,
    UNIQUE (tenant_id, user_id, voice_session_id, thread_id, call_id)
);

CREATE INDEX IF NOT EXISTS tool_pending_confirmations_expiry_idx
    ON "__VOICEAGENT_SCHEMA__".tool_pending_confirmations (expires_at)
    WHERE consumed_at IS NULL;

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".tool_execution_grants (
    decision_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    voice_session_id text NOT NULL,
    thread_id text NOT NULL,
    call_id text NOT NULL,
    request_digest text NOT NULL CHECK (length(request_digest) = 64),
    grant_payload jsonb NOT NULL CHECK (jsonb_typeof(grant_payload) = 'object'),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL,
    UNIQUE (tenant_id, user_id, voice_session_id, thread_id, call_id)
);

CREATE INDEX IF NOT EXISTS tool_execution_grants_expiry_idx
    ON "__VOICEAGENT_SCHEMA__".tool_execution_grants (expires_at)
    WHERE consumed_at IS NULL;
