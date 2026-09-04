ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_acceptances
    ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS failure_retryable boolean,
    ADD COLUMN IF NOT EXISTS lease_token text,
    ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;

UPDATE "__VOICEAGENT_SCHEMA__".motion_base_acceptances
SET phase = 'failed',
    failure_reason = COALESCE(failure_reason, 'interrupted before lease migration'),
    failure_retryable = true,
    lease_token = NULL,
    lease_expires_at = NULL
WHERE phase = 'accepting';

UPDATE "__VOICEAGENT_SCHEMA__".motion_base_acceptances
SET failure_reason = COALESCE(failure_reason, 'legacy acceptance failure'),
    failure_retryable = COALESCE(failure_retryable, true),
    lease_token = NULL,
    lease_expires_at = NULL
WHERE phase = 'failed';

UPDATE "__VOICEAGENT_SCHEMA__".motion_base_acceptances
SET failure_reason = NULL,
    failure_retryable = NULL,
    lease_token = NULL,
    lease_expires_at = NULL
WHERE phase = 'accepted';

ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_acceptances
    DROP CONSTRAINT IF EXISTS motion_base_acceptances_recovery_check;
ALTER TABLE "__VOICEAGENT_SCHEMA__".motion_base_acceptances
    ADD CONSTRAINT motion_base_acceptances_recovery_check CHECK (
        attempt_count > 0
        AND (
            (phase = 'accepting' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL
             AND failure_reason IS NULL AND failure_retryable IS NULL)
            OR
            (phase = 'accepted' AND lease_token IS NULL AND lease_expires_at IS NULL
             AND failure_reason IS NULL AND failure_retryable IS NULL)
            OR
            (phase = 'failed' AND lease_token IS NULL AND lease_expires_at IS NULL
             AND failure_reason IS NOT NULL AND failure_retryable IS NOT NULL)
        )
    );

CREATE INDEX IF NOT EXISTS motion_base_acceptances_recovery_idx
    ON "__VOICEAGENT_SCHEMA__".motion_base_acceptances (phase, lease_expires_at)
    WHERE phase IN ('accepting', 'failed');
