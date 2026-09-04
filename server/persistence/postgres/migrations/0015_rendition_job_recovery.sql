ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_renditions
    ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS failure_retryable boolean,
    ADD COLUMN IF NOT EXISTS lease_token text,
    ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;

UPDATE "__VOICEAGENT_SCHEMA__".motion_base_renditions
SET phase = 'failed',
    attempt_count = GREATEST(attempt_count, 1),
    failure_reason = COALESCE(failure_reason, 'interrupted before lease migration'),
    failure_retryable = true,
    lease_token = NULL,
    lease_expires_at = NULL
WHERE phase = 'processing';

UPDATE "__VOICEAGENT_SCHEMA__".motion_base_renditions
SET failure_reason = COALESCE(failure_reason, 'legacy rendition failure'),
    attempt_count = GREATEST(attempt_count, 1),
    failure_retryable = COALESCE(failure_retryable, true),
    lease_token = NULL,
    lease_expires_at = NULL
WHERE phase = 'failed';

UPDATE "__VOICEAGENT_SCHEMA__".motion_base_renditions
SET attempt_count = CASE WHEN phase = 'queued' THEN 0 ELSE GREATEST(attempt_count, 1) END,
    failure_reason = NULL, failure_retryable = NULL,
    lease_token = NULL, lease_expires_at = NULL
WHERE phase IN ('queued', 'ready_for_review', 'approved');

ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_renditions
    DROP CONSTRAINT IF EXISTS motion_base_renditions_recovery_check;
ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_renditions
    ADD CONSTRAINT motion_base_renditions_recovery_check CHECK (
        attempt_count >= 0
        AND (
            (phase = 'queued' AND attempt_count = 0 AND lease_token IS NULL
             AND lease_expires_at IS NULL AND failure_reason IS NULL
             AND failure_retryable IS NULL)
            OR
            (phase = 'processing' AND attempt_count > 0 AND lease_token IS NOT NULL
             AND lease_expires_at IS NOT NULL AND failure_reason IS NULL
             AND failure_retryable IS NULL)
            OR
            (phase IN ('ready_for_review', 'approved') AND attempt_count > 0
             AND lease_token IS NULL AND lease_expires_at IS NULL
             AND failure_reason IS NULL AND failure_retryable IS NULL)
            OR
            (phase = 'failed' AND attempt_count > 0 AND lease_token IS NULL
             AND lease_expires_at IS NULL AND failure_reason IS NOT NULL
             AND failure_retryable IS NOT NULL)
        )
    );

CREATE INDEX IF NOT EXISTS motion_base_renditions_recovery_idx
    ON "__VOICEAGENT_SCHEMA__".motion_base_renditions (phase, lease_expires_at)
    WHERE phase IN ('processing', 'failed');
