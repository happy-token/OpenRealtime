CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".voice_admissions (
    ticket_hash text PRIMARY KEY,
    issuer text,
    subject text,
    guest_id uuid,
    asr_provider text NOT NULL,
    asr_source text NOT NULL CHECK (asr_source IN ('platform', 'personal')),
    tts_provider text NOT NULL,
    tts_source text NOT NULL CHECK (tts_source IN ('platform', 'personal')),
    llm_provider text NOT NULL,
    llm_source text NOT NULL CHECK (llm_source IN ('platform', 'personal')),
    anam_source text CHECK (anam_source IN ('platform', 'personal')),
    personal_providers text[] NOT NULL DEFAULT '{}',
    credential_versions jsonb NOT NULL DEFAULT '{}',
    issued_at timestamptz NOT NULL DEFAULT now(),
    connect_by timestamptz NOT NULL,
    deadline_at timestamptz,
    expires_at timestamptz NOT NULL,
    bound_session_id uuid,
    anam_issued_at timestamptz,
    ended_at timestamptz,
    revoked_at timestamptz,
    CHECK ((issuer IS NULL AND subject IS NULL AND guest_id IS NOT NULL)
        OR (issuer IS NOT NULL AND subject IS NOT NULL AND guest_id IS NULL))
);

CREATE INDEX IF NOT EXISTS voice_admissions_active_idx
    ON "__VOICEAGENT_SCHEMA__".voice_admissions (expires_at)
    WHERE ended_at IS NULL AND revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS voice_admissions_owner_idx
    ON "__VOICEAGENT_SCHEMA__".voice_admissions (issuer, subject)
    WHERE ended_at IS NULL AND revoked_at IS NULL;
