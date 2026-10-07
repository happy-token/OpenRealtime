-- Run outside a transaction block, after 0039's immutable functions exist.
-- Controlled rollback: DROP INDEX CONCURRENTLY schema.runtime_playback_attachment_idx;
-- Digest only accelerates retrieval: the query also checks every original field.
CREATE INDEX CONCURRENTLY IF NOT EXISTS runtime_playback_attachment_idx
    ON "__VOICEAGENT_SCHEMA__".runtime_telemetry_records (
        "__VOICEAGENT_SCHEMA__".recording_playback_attachment_key(
            tenant_id, user_id, voice_session_id, thread_id, generation,
            turn_id, response_id, attributes
        ),
        "__VOICEAGENT_SCHEMA__".recording_playback_sample_position(attributes) DESC
    ) WHERE name = 'client.playback_progress' AND outcome = 'ok'
        AND "__VOICEAGENT_SCHEMA__".recording_playback_sample_position(attributes) IS NOT NULL;
