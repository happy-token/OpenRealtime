-- Forward-only immutable index functions. Do not change their semantics in place
-- after 0040 builds the index; use new function names/indexes in a later migration.
-- Controlled rollback: drop 0040's index first, then these two functions.
CREATE OR REPLACE FUNCTION "__VOICEAGENT_SCHEMA__".recording_playback_sample_position(a jsonb)
RETURNS bigint LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET search_path = pg_catalog AS $$
DECLARE
    field text;
    position bigint;
    rate bigint;
    micros bigint;
    product numeric;
    whole numeric;
    remainder numeric;
BEGIN
    IF jsonb_typeof(a) IS DISTINCT FROM 'object' OR a->>'precision' IS DISTINCT FROM 'segment' THEN
        RETURN NULL;
    END IF;
    FOREACH field IN ARRAY ARRAY['played_position_samples','sample_rate_hz','played_audio_end_us'] LOOP
        IF jsonb_typeof(a->field) IS DISTINCT FROM 'number'
           OR length(a->>field) > 16 OR a->>field !~ '^[0-9]+$' THEN
            RETURN NULL;
        END IF;
    END LOOP;
    position := (a->>'played_position_samples')::bigint;
    rate := (a->>'sample_rate_hz')::bigint;
    micros := (a->>'played_audio_end_us')::bigint;
    IF position > 9007199254740991 OR micros > 9007199254740991 OR rate < 1 OR rate > 192000 THEN
        RETURN NULL;
    END IF;
    FOREACH field IN ARRAY ARRAY['output_epoch','speech_id'] LOOP
        IF jsonb_typeof(a->field) IS DISTINCT FROM 'string'
           OR octet_length(a->>field) NOT BETWEEN 1 AND 512 THEN
            RETURN NULL;
        END IF;
    END LOOP;
    FOREACH field IN ARRAY ARRAY['started','stopped','completed'] LOOP
        IF jsonb_typeof(a->field) IS DISTINCT FROM 'boolean' THEN RETURN NULL; END IF;
    END LOOP;
    IF (a->>'started')::boolean::integer + (a->>'stopped')::boolean::integer
       + (a->>'completed')::boolean::integer > 1 THEN RETURN NULL; END IF;
    -- Exactly the canonical cumulative ties-to-even clock, without bigint overflow.
    product := position::numeric * 1000000;
    whole := div(product, rate);
    remainder := mod(product, rate);
    IF remainder * 2 > rate OR (remainder * 2 = rate AND mod(whole, 2) = 1) THEN
        whole := whole + 1;
    END IF;
    IF whole <> micros THEN RETURN NULL; END IF;
    RETURN position;
END;
$$;

CREATE OR REPLACE FUNCTION "__VOICEAGENT_SCHEMA__".recording_playback_attachment_key(
    tenant text, owner text, session text, thread text, generation bigint,
    turn text, response text, a jsonb
) RETURNS bytea LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = pg_catalog AS $$
    SELECT sha256(convert_to(jsonb_build_array(tenant, owner, session, thread, generation,
        turn, response, a->>'output_epoch', a->>'speech_id', a->'sample_rate_hz')::text, 'UTF8'));
$$;
