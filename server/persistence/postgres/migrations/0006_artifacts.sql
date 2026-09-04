CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".artifacts (
    artifact_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    source_kind text NOT NULL,
    source_id text NOT NULL,
    logical_name text NOT NULL,
    media_type text NOT NULL,
    classification text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL CHECK (length(request_digest) = 64),
    expected_size bigint CHECK (expected_size >= 0),
    expected_sha256 text CHECK (
        expected_sha256 IS NULL OR length(expected_sha256) = 64
    ),
    retention_until timestamptz,
    phase text NOT NULL CHECK (
        phase IN (
            'staging', 'available', 'quarantined',
            'deleting', 'deleted', 'failed'
        )
    ),
    revision bigint NOT NULL CHECK (revision > 0),
    object_key text,
    object_size bigint CHECK (object_size >= 0),
    object_sha256 text CHECK (
        object_sha256 IS NULL OR length(object_sha256) = 64
    ),
    object_etag text,
    object_version_id text,
    failure_reason text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (tenant_id, idempotency_key),
    CHECK (
        (object_key IS NULL AND object_size IS NULL AND object_sha256 IS NULL)
        OR
        (object_key IS NOT NULL AND object_size IS NOT NULL AND object_sha256 IS NOT NULL)
    ),
    CHECK (phase <> 'available' OR object_key IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS artifacts_tenant_source_idx
    ON "__VOICEAGENT_SCHEMA__".artifacts (
        tenant_id, source_kind, source_id, created_at
    );

CREATE INDEX IF NOT EXISTS artifacts_staging_gc_idx
    ON "__VOICEAGENT_SCHEMA__".artifacts (updated_at)
    WHERE phase IN ('staging', 'failed', 'deleting');
