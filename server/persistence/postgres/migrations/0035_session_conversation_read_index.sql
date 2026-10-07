-- Run outside a transaction block. Existing tables remain writable while building.
-- Forward-only migration; a controlled rollback may DROP INDEX CONCURRENTLY.
CREATE INDEX CONCURRENTLY IF NOT EXISTS conversation_items_session_read_idx
    ON "__VOICEAGENT_SCHEMA__".conversation_items (
        voice_session_id, tenant_id, user_id, thread_id, sequence
    ) WHERE kind IN ('user.input', 'assistant.output');
