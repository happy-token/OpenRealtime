ALTER TABLE "__VOICEAGENT_SCHEMA__".provider_instances
  ADD COLUMN IF NOT EXISTS base_url text NOT NULL DEFAULT '';

UPDATE "__VOICEAGENT_SCHEMA__".provider_instances
SET base_url = CASE provider
  WHEN 'doubao' THEN 'https://openspeech.bytedance.com'
  WHEN 'dashscope' THEN 'https://dashscope.aliyuncs.com'
  WHEN 'deepseek' THEN 'https://api.deepseek.com'
  WHEN 'openai' THEN 'https://api.openai.com/v1'
  ELSE '' END
WHERE base_url = '';

CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".provider_preview_test_limits (
  scope text NOT NULL,
  issuer text NOT NULL,
  subject text NOT NULL,
  last_started_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope, issuer, subject)
);
