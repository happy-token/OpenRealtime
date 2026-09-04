CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".motion_base_renditions (
    rendition_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    motion_base_id text NOT NULL
        REFERENCES "__VOICEAGENT_SCHEMA__".motion_base_videos (motion_base_id),
    profile text NOT NULL CHECK (
        profile IN ('mobile_fullscreen', 'desktop_fullscreen')
    ),
    phase text NOT NULL CHECK (
        phase IN ('queued', 'processing', 'ready_for_review', 'approved', 'failed')
    ),
    artifact_id text UNIQUE
        REFERENCES "__VOICEAGENT_SCHEMA__".artifacts (artifact_id),
    size_bytes bigint CHECK (size_bytes > 0),
    sha256 text CHECK (sha256 IS NULL OR length(sha256) = 64),
    duration_ms bigint CHECK (duration_ms > 0),
    width integer CHECK (width > 0),
    height integer CHECK (height > 0),
    frame_rate_numerator integer CHECK (frame_rate_numerator > 0),
    frame_rate_denominator integer CHECK (frame_rate_denominator > 0),
    video_codec text,
    has_audio boolean,
    audio_codec text,
    fit_mode text NOT NULL DEFAULT 'blur_pad',
    loop_start_ms bigint,
    loop_end_ms bigint,
    loop_crossfade_ms bigint,
    failure_reason text,
    revision bigint NOT NULL CHECK (revision > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (motion_base_id, profile),
    CHECK (
        (artifact_id IS NULL AND size_bytes IS NULL AND sha256 IS NULL
         AND duration_ms IS NULL AND width IS NULL AND height IS NULL
         AND frame_rate_numerator IS NULL AND frame_rate_denominator IS NULL
         AND video_codec IS NULL AND has_audio IS NULL AND audio_codec IS NULL)
        OR
        (artifact_id IS NOT NULL AND size_bytes IS NOT NULL AND sha256 IS NOT NULL
         AND duration_ms IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL
         AND frame_rate_numerator IS NOT NULL AND frame_rate_denominator IS NOT NULL
         AND video_codec IS NOT NULL AND has_audio IS NOT NULL)
    ),
    CHECK (has_audio IS NULL OR has_audio = (audio_codec IS NOT NULL)),
    CHECK (phase NOT IN ('ready_for_review', 'approved') OR artifact_id IS NOT NULL),
    CHECK (
        artifact_id IS NULL OR (
            frame_rate_numerator = 25 AND frame_rate_denominator = 1
            AND video_codec = 'h264' AND has_audio = false AND audio_codec IS NULL
            AND (
                (profile = 'mobile_fullscreen' AND width = 720 AND height = 1280)
                OR
                (profile = 'desktop_fullscreen' AND width = 1280 AND height = 720)
            )
        )
    ),
    CHECK (
        (loop_start_ms IS NULL AND loop_end_ms IS NULL AND loop_crossfade_ms IS NULL)
        OR
        (loop_start_ms >= 0 AND loop_end_ms > loop_start_ms
         AND loop_crossfade_ms >= 0)
    )
);

CREATE INDEX IF NOT EXISTS motion_base_renditions_owner_idx
    ON "__VOICEAGENT_SCHEMA__".motion_base_renditions (
        tenant_id, owner_id, motion_base_id, profile
    );
