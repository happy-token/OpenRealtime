ALTER TABLE "__VOICEAGENT_SCHEMA__".artifacts
    ADD COLUMN IF NOT EXISTS immutable boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS artifacts_immutable_idx
    ON "__VOICEAGENT_SCHEMA__".artifacts (artifact_id)
    WHERE immutable;
