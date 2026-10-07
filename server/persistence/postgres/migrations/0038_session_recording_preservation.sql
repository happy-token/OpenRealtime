-- Additive Session policy, deployed only through controlled migrations.
-- Policy rows are monotonic: no automatic unmark or expiry backfill.
-- Controlled rollback requires a new forward migration after explicit review;
-- dropping this table loses preservation obligations and must not be automated.
CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".session_recording_preservation (
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    voice_session_id text NOT NULL,
    marked_at timestamptz NOT NULL,
    actor_id text NOT NULL CHECK (octet_length(actor_id) BETWEEN 1 AND 256),
    PRIMARY KEY (tenant_id, owner_id, voice_session_id)
);
