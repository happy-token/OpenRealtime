DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'provider_instances_builtin_contract'
          AND conrelid = '"__VOICEAGENT_SCHEMA__".provider_instances'::regclass
    ) THEN
        ALTER TABLE "__VOICEAGENT_SCHEMA__".provider_instances
            ADD CONSTRAINT provider_instances_builtin_contract CHECK (
                (capability = 'asr' AND provider = 'doubao' AND model = '')
                OR (capability = 'tts' AND provider IN ('doubao', 'dashscope') AND model = '')
                OR (capability = 'llm' AND provider IN ('deepseek', 'openai'))
            );
    END IF;
END $$;
