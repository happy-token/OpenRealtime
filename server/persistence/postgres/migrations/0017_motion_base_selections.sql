CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".motion_base_selections (
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    visual_identity_id text NOT NULL,
    motion_base_id text NOT NULL
        REFERENCES "__VOICEAGENT_SCHEMA__".motion_base_videos (motion_base_id),
    revision bigint NOT NULL CHECK (revision > 0),
    selected_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, owner_id, visual_identity_id)
);

CREATE INDEX IF NOT EXISTS motion_base_selections_motion_base_idx
    ON "__VOICEAGENT_SCHEMA__".motion_base_selections (motion_base_id);
