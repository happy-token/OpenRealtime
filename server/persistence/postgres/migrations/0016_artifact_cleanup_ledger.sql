CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".artifact_upload_attempts (
    attempt_id text PRIMARY KEY,
    artifact_id text NOT NULL
        REFERENCES "__VOICEAGENT_SCHEMA__".artifacts (artifact_id),
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    object_key text NOT NULL UNIQUE,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    sha256 text NOT NULL CHECK (length(sha256) = 64),
    phase text NOT NULL CHECK (
        phase IN ('pending', 'committed', 'cleanup_pending', 'cleaning', 'cleaned')
    ),
    cleanup_token text,
    cleanup_after timestamptz NOT NULL,
    failure_reason text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS artifact_upload_attempts_cleanup_idx
    ON "__VOICEAGENT_SCHEMA__".artifact_upload_attempts (cleanup_after, updated_at)
    WHERE phase IN ('pending', 'cleanup_pending', 'cleaning');

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".artifact_cleanup_intents (
    artifact_id text PRIMARY KEY
        REFERENCES "__VOICEAGENT_SCHEMA__".artifacts (artifact_id),
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    reason text NOT NULL,
    phase text NOT NULL CHECK (phase IN ('pending', 'cancelled', 'completed')),
    cleanup_after timestamptz NOT NULL,
    failure_reason text,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS artifact_cleanup_intents_pending_idx
    ON "__VOICEAGENT_SCHEMA__".artifact_cleanup_intents (cleanup_after, updated_at)
    WHERE phase = 'pending';
