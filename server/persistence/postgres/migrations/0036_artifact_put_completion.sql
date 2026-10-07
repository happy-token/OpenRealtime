-- An unconfirmed put can still write after a cleanup request. Keep its
-- cleanup intent retryable until the writer actually reports completion.
-- PostgreSQL 16 adds this constant default without rewriting the table.
ALTER TABLE "__VOICEAGENT_SCHEMA__".artifact_upload_attempts
    ADD COLUMN IF NOT EXISTS put_completed boolean NOT NULL DEFAULT false;
