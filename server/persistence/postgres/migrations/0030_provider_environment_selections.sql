ALTER TABLE "__VOICEAGENT_SCHEMA__".provider_selections
  ADD COLUMN IF NOT EXISTS env_provider text;

ALTER TABLE "__VOICEAGENT_SCHEMA__".provider_selections
  ALTER COLUMN instance_id DROP NOT NULL;

ALTER TABLE "__VOICEAGENT_SCHEMA__".provider_selections
  ADD CONSTRAINT provider_selection_one_target CHECK (
    (instance_id IS NOT NULL) <> (env_provider IS NOT NULL)
  );

ALTER TABLE "__VOICEAGENT_SCHEMA__".provider_selections
  ADD CONSTRAINT provider_selection_env_capability CHECK (
    env_provider IS NULL
    OR (capability IN ('asr', 'tts') AND env_provider IN ('doubao', 'dashscope'))
    OR (capability = 'llm' AND env_provider IN ('deepseek', 'openai'))
  );
