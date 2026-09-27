-- Additive provider configuration. Legacy provider keys remain untouched until
-- admission has been cut over to explicit instance selections.
CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".provider_instances (
    id uuid PRIMARY KEY,
    scope text NOT NULL CHECK (scope IN ('personal', 'platform')),
    issuer text NOT NULL DEFAULT '',
    subject text NOT NULL DEFAULT '',
    capability text NOT NULL CHECK (capability IN ('asr', 'tts', 'llm')),
    provider text NOT NULL,
    display_name text NOT NULL,
    model text NOT NULL DEFAULT '',
    sealed_key bytea NOT NULL,
    key_version uuid NOT NULL,
    key_suffix text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    connection_status text NOT NULL DEFAULT 'untested'
        CHECK (connection_status IN ('untested', 'passed', 'failed')),
    tested_at timestamptz,
    test_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((scope = 'platform' AND issuer = '' AND subject = '')
        OR (scope = 'personal' AND issuer <> '' AND subject <> ''))
);

CREATE INDEX IF NOT EXISTS provider_instances_owner_idx
    ON "__VOICEAGENT_SCHEMA__".provider_instances
    (scope, issuer, subject, capability, created_at DESC);

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".provider_selections (
    scope text NOT NULL CHECK (scope IN ('personal', 'platform')),
    issuer text NOT NULL DEFAULT '',
    subject text NOT NULL DEFAULT '',
    capability text NOT NULL CHECK (capability IN ('asr', 'tts', 'llm')),
    instance_id uuid NOT NULL REFERENCES "__VOICEAGENT_SCHEMA__".provider_instances(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, issuer, subject, capability),
    CHECK ((scope = 'platform' AND issuer = '' AND subject = '')
        OR (scope = 'personal' AND issuer <> '' AND subject <> ''))
);

ALTER TABLE "__VOICEAGENT_SCHEMA__".voice_admissions
    ADD COLUMN IF NOT EXISTS provider_instances jsonb NOT NULL DEFAULT '{}'::jsonb;
