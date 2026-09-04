CREATE TABLE IF NOT EXISTS "__VOICEAGENT_SCHEMA__".speech_delivery_records (
    speech_id text PRIMARY KEY,
    context jsonb NOT NULL,
    source_item_id text,
    context_policy text NOT NULL,
    interrupted_context_policy text NOT NULL,
    intended_spoken_content text NOT NULL DEFAULT '',
    delivered_speech_transcript text NOT NULL DEFAULT '',
    played_audio_end_us bigint NOT NULL DEFAULT 0,
    status text NOT NULL,
    precision text,
    text_committed boolean NOT NULL DEFAULT false,
    reason text,
    revision bigint NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CHECK (played_audio_end_us >= 0),
    CHECK (revision >= 1)
);

CREATE INDEX IF NOT EXISTS speech_delivery_source_item_idx
    ON "__VOICEAGENT_SCHEMA__".speech_delivery_records (source_item_id, updated_at DESC)
    WHERE source_item_id IS NOT NULL;
