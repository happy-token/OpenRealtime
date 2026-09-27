CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".role_tts_selections (
    issuer text NOT NULL,
    subject text NOT NULL,
    role_id text NOT NULL,
    target text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (issuer, subject, role_id),
    CHECK (issuer <> '' AND subject <> ''),
    CHECK (length(role_id) BETWEEN 2 AND 160),
    CHECK (target ~ '^(env:(doubao|dashscope)|[0-9a-f-]{36})$')
);
