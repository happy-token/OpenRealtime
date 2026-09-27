ALTER TABLE "__VOICEAGENT_SCHEMA__".provider_instances
  DROP CONSTRAINT IF EXISTS provider_instances_builtin_contract;

ALTER TABLE "__VOICEAGENT_SCHEMA__".provider_instances
  ADD CONSTRAINT provider_instances_builtin_contract CHECK (
    (capability = 'asr' AND provider IN ('doubao', 'dashscope') AND model = '')
    OR (capability = 'tts' AND provider IN ('doubao', 'dashscope') AND model = '')
    OR (capability = 'llm' AND provider IN ('deepseek', 'openai'))
  );
