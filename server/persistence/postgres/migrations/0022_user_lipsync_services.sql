CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".user_lipsync_services (
    issuer text NOT NULL,
    subject text NOT NULL,
    url text NOT NULL,
    sealed_token bytea,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (issuer, subject)
);
