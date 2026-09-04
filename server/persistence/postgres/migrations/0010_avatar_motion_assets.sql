CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".motion_base_candidates (
    candidate_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    visual_identity_id text NOT NULL,
    source_kind text NOT NULL CHECK (source_kind IN ('upload', 'vidu', 'liveportrait')),
    source_id text NOT NULL,
    artifact_id text NOT NULL REFERENCES "__VOICEAGENT_SCHEMA__".artifacts (artifact_id),
    logical_name text NOT NULL,
    rights_scope text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL CHECK (length(request_digest) = 64),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    sha256 text NOT NULL CHECK (length(sha256) = 64),
    duration_ms bigint NOT NULL CHECK (duration_ms > 0),
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    frame_rate_numerator integer NOT NULL CHECK (frame_rate_numerator > 0),
    frame_rate_denominator integer NOT NULL CHECK (frame_rate_denominator > 0),
    video_codec text NOT NULL,
    has_audio boolean NOT NULL,
    audio_codec text,
    phase text NOT NULL CHECK (phase IN ('candidate', 'accepting', 'accepted', 'failed')),
    revision bigint NOT NULL CHECK (revision > 0),
    failure_reason text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (tenant_id, idempotency_key),
    CHECK (has_audio = (audio_codec IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS motion_base_candidates_owner_identity_idx
    ON "__VOICEAGENT_SCHEMA__".motion_base_candidates (
        tenant_id, owner_id, visual_identity_id, created_at
    );

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".motion_base_acceptances (
    acceptance_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    candidate_id text NOT NULL UNIQUE
        REFERENCES "__VOICEAGENT_SCHEMA__".motion_base_candidates (candidate_id),
    reviewer_id text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL CHECK (length(request_digest) = 64),
    identity_match boolean NOT NULL,
    single_person boolean NOT NULL,
    closed_mouth boolean NOT NULL,
    fixed_camera boolean NOT NULL,
    no_gestures boolean NOT NULL,
    rights_confirmed boolean NOT NULL,
    phase text NOT NULL CHECK (phase IN ('accepting', 'accepted', 'failed')),
    source_master_artifact_id text
        REFERENCES "__VOICEAGENT_SCHEMA__".artifacts (artifact_id),
    motion_base_id text,
    failure_reason text,
    revision bigint NOT NULL CHECK (revision > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (tenant_id, idempotency_key),
    CHECK (
        identity_match AND single_person AND closed_mouth
        AND fixed_camera AND no_gestures AND rights_confirmed
    )
);

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".motion_base_videos (
    motion_base_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    visual_identity_id text NOT NULL,
    candidate_id text NOT NULL UNIQUE
        REFERENCES "__VOICEAGENT_SCHEMA__".motion_base_candidates (candidate_id),
    acceptance_id text NOT NULL UNIQUE
        REFERENCES "__VOICEAGENT_SCHEMA__".motion_base_acceptances (acceptance_id),
    source_master_artifact_id text NOT NULL UNIQUE
        REFERENCES "__VOICEAGENT_SCHEMA__".artifacts (artifact_id),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    sha256 text NOT NULL CHECK (length(sha256) = 64),
    duration_ms bigint NOT NULL CHECK (duration_ms > 0),
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    frame_rate_numerator integer NOT NULL CHECK (frame_rate_numerator > 0),
    frame_rate_denominator integer NOT NULL CHECK (frame_rate_denominator > 0),
    video_codec text NOT NULL,
    has_audio boolean NOT NULL,
    audio_codec text,
    created_at timestamptz NOT NULL,
    CHECK (has_audio = (audio_codec IS NOT NULL))
);

ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_acceptances
    DROP CONSTRAINT IF EXISTS motion_base_acceptances_motion_base_fk;
ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_acceptances
    ADD CONSTRAINT motion_base_acceptances_motion_base_fk
    FOREIGN KEY (motion_base_id)
    REFERENCES "__VOICEAGENT_SCHEMA__".motion_base_videos (motion_base_id);

CREATE INDEX IF NOT EXISTS motion_base_videos_owner_identity_idx
    ON "__VOICEAGENT_SCHEMA__".motion_base_videos (
        tenant_id, owner_id, visual_identity_id, created_at
    );
