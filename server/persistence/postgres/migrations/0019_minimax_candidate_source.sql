ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_candidates
    DROP CONSTRAINT IF EXISTS motion_base_candidates_source_kind_check;

ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_candidates
    ADD CONSTRAINT motion_base_candidates_source_kind_check
    CHECK (source_kind IN ('upload', 'vidu', 'liveportrait', 'ltx', 'minimax'));
