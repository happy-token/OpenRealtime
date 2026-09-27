CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".user_talking_model_services (
    issuer text NOT NULL,
    subject text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('musetalk', 'wav2lip')),
    url text NOT NULL,
    sealed_token bytea,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (issuer, subject, kind)
);
