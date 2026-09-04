ALTER TABLE "__VOICEAGENT_SCHEMA__".agent_tasks
    ADD COLUMN IF NOT EXISTS dispatch_attempt_count integer NOT NULL DEFAULT 0
    CHECK (dispatch_attempt_count >= 0);
