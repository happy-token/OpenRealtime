from server.persistence.postgres.schema import render_migrations


def test_provider_instance_migrations_are_additive_and_schema_qualified() -> None:
    statements = render_migrations("voiceagent_test")
    create = next(sql for sql in statements if "CREATE TABLE IF NOT EXISTS \"voiceagent_test\".provider_instances" in sql)
    assert "CREATE TABLE IF NOT EXISTS \"voiceagent_test\".provider_selections" in create
    assert "ADD COLUMN IF NOT EXISTS provider_instances" in create
    assert "DROP TABLE" not in create
    cooldown = next(sql for sql in statements if "test_last_started_at" in sql)
    assert "ADD COLUMN IF NOT EXISTS test_last_started_at" in cooldown
    contract = next(sql for sql in statements if "provider_instances_builtin_contract" in sql)
    assert "provider = 'doubao'" in contract
    assert "provider IN ('deepseek', 'openai')" in contract
    reset = next(sql for sql in statements if "Earlier speech" in sql)
    assert "UPDATE \"voiceagent_test\".provider_instances" in reset
    assert "capability IN ('asr', 'tts')" in reset
    dashscope_asr = next(sql for sql in statements if "DROP CONSTRAINT IF EXISTS provider_instances_builtin_contract" in sql)
    assert "capability = 'asr' AND provider IN ('doubao', 'dashscope')" in dashscope_asr
    environment_choice = next(sql for sql in statements if "provider_selection_one_target" in sql)
    assert "env_provider" in environment_choice
    assert "instance_id DROP NOT NULL" in environment_choice
