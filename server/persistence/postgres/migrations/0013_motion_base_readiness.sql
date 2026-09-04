ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_videos
    ADD COLUMN IF NOT EXISTS phase text NOT NULL DEFAULT 'preparing';

ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_videos
    DROP CONSTRAINT IF EXISTS motion_base_videos_phase_check;
ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_videos
    ADD CONSTRAINT motion_base_videos_phase_check
    CHECK (phase IN ('preparing', 'ready'));

CREATE INDEX IF NOT EXISTS motion_base_videos_ready_owner_idx
    ON "__VOICEAGENT_SCHEMA__".motion_base_videos (
        tenant_id, owner_id, visual_identity_id, created_at
    ) WHERE phase = 'ready';
