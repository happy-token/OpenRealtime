CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".web_user_sessions (
    token_hash text PRIMARY KEY,
    issuer text NOT NULL,
    subject text NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS web_user_sessions_subject_idx
    ON "__VOICEAGENT_SCHEMA__".web_user_sessions (issuer, subject);

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".user_provider_credentials (
    issuer text NOT NULL,
    subject text NOT NULL,
    provider text NOT NULL,
    sealed_key bytea NOT NULL,
    key_version uuid NOT NULL,
    suffix text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (issuer, subject, provider)
);
