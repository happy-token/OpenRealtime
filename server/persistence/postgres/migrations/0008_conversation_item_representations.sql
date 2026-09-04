ALTER TABLE "__VOICEAGENT_SCHEMA__".conversation_items
    ADD COLUMN IF NOT EXISTS display_content jsonb,
    ADD COLUMN IF NOT EXISTS spoken_content jsonb;
