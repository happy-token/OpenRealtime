CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".app_admin_accounts (
    issuer text NOT NULL,
    subject text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    granted_by text NOT NULL,
    PRIMARY KEY (issuer, subject)
);
