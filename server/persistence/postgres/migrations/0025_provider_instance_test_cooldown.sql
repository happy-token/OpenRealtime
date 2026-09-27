ALTER TABLE "__VOICEAGENT_SCHEMA__".provider_instances
    ADD COLUMN IF NOT EXISTS test_last_started_at timestamptz;
