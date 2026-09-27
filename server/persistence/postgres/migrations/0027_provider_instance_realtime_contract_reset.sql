-- Earlier speech "passed" states proved only endpoint connectivity, not the
-- required partial/final or duplex contract. Re-test before new selection.
UPDATE "__VOICEAGENT_SCHEMA__".provider_instances
SET connection_status = 'untested', tested_at = NULL, test_message = NULL
WHERE capability IN ('asr', 'tts');
