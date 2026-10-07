-- Forward-only additive index; run outside a transaction block.
-- Controlled rollback: DROP INDEX CONCURRENTLY schema.conversation_items_recording_read_idx;
CREATE INDEX CONCURRENTLY IF NOT EXISTS conversation_items_recording_read_idx
    ON "__VOICEAGENT_SCHEMA__".conversation_items (voice_session_id, tenant_id, user_id, thread_id, sequence)
    WHERE producer = 'voice-session-recording';
