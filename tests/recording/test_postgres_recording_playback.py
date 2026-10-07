from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest

from server.artifacts import InMemoryS3ObjectClient
from server.core.playback import sample_position_us
from server.observability.recording_playback import receipt_index
from server.persistence.postgres.runtime_telemetry import PostgresTelemetryStore
from tests.persistence.test_postgres_artifact_store import postgres as postgres  # noqa: PLC0414
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_postgres_recording_history_preservation import runtime_for
from tests.recording.test_recording_playback import receipt, sent_recording
from tests.recording.test_recording_playback_lookup import assert_long_catalog, attachment

pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)


async def test_postgres_catalog_finds_receipt_beyond_the_first_5000_events(postgres):
    _, schema = postgres
    runtime = await runtime_for(schema, InMemoryS3ObjectClient())
    try:
        await assert_long_catalog(runtime)
    finally:
        await runtime.close()


@pytest.mark.parametrize("precise", [False, True])
async def test_postgres_receipt_attachment_survives_runtime_restart(postgres, precise):
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    ctx = replace(context(), response_id="response")
    runtime = await runtime_for(schema, objects)
    try:
        await sent_recording(runtime, ctx, start=2500)
        receipt(runtime, ctx, precise=precise)
        await runtime.telemetry.flush()
        async with pool.acquire() as conn:
            raw = await conn.fetchval(
                f'SELECT attributes FROM "{schema}".runtime_telemetry_records WHERE name=$1',
                "client.playback_progress",
            )
        attrs = json.loads(raw) if isinstance(raw, str) else raw
        assert attrs["output_epoch"] == ("output" if precise else None)
        assert attrs["played_position_samples"] == (80 if precise else None)
        assert attrs["sample_rate_hz"] == (16000 if precise else None)
    finally:
        await runtime.close()
    rebuilt = await runtime_for(schema, objects)
    try:
        page = await rebuilt.recordings.read_page(ctx.voice_session_id)
        assert page["playback_source"]["status"] == "available"
        assert not page["playback_source"]["truncated"]
        row = page["items"][0]
        assert row["status"] == "available"
        assert row["playback_confirmation"] == "not-inferred"
        assert row["playback"] == {
            "status": "reported" if precise else "unknown",
            "reported_end_sample": 80 if precise else None,
            "overlap_samples": 40 if precise else None,
            "sample_rate_hz": 16000 if precise else None,
        }
    finally:
        await rebuilt.close()


async def test_postgres_receipt_filter_matches_canonical_sample_validation(postgres):
    pool, schema = postgres
    runtime = await runtime_for(schema, InMemoryS3ObjectClient())
    ctx = replace(context(), response_id="response")
    try:
        receipt(runtime, ctx)
        await runtime.telemetry.flush()
        detail = await runtime.diagnostics.session_detail(ctx.voice_session_id)
        event = next(event for event in detail.events if event.name == "client.playback_progress")
        mutations = (
            [
                {"played_position_samples": value}
                for value in (True, -1, 80.0, "80", None, [], {}, 2**53, 10**40)
            ]
            + [
                {"sample_rate_hz": value}
                for value in (False, 0, 16000.0, "16000", None, 384000, 10**40)
            ]
            + [
                {"played_audio_end_us": value}
                for value in (False, -1, 999, 5000.0, "5000", None, 10**40)
            ]
            + [
                {"started": None},
                {"completed": "false"},
                {"started": True, "stopped": True},
                {"precision": "estimated"},
                {"output_epoch": ""},
                {"speech_id": "x" * 513},
            ]
        )
        async with pool.acquire() as conn:
            for mutation in mutations:
                attrs = dict(event.attributes) | mutation
                assert receipt_index([replace(event, attributes=attrs)]) == {}
                assert (
                    await conn.fetchval(
                        f'SELECT "{schema}".recording_playback_sample_position($1::jsonb)',
                        json.dumps(attrs),
                    )
                    is None
                )
            for position, rate in ((0, 16000), (1, 128), (3, 128), ((2**53 - 1) * 192000 // 1_000_000, 192000)):
                attrs = dict(event.attributes) | {
                    "played_position_samples": position,
                    "sample_rate_hz": rate,
                    "played_audio_end_us": sample_position_us(position, rate),
                }
                assert (
                    next(iter(receipt_index([replace(event, attributes=attrs)]).values()))
                    == position
                )
                assert (
                    await conn.fetchval(
                        f'SELECT "{schema}".recording_playback_sample_position($1::jsonb)',
                        json.dumps(attrs),
                    )
                    == position
                )
    finally:
        await runtime.close()


async def test_postgres_full_nullable_scope_and_maximum_prefix(postgres):
    _, schema = postgres
    ctx = context()
    runtime = await runtime_for(schema, InMemoryS3ObjectClient())
    try:
        receipt(runtime, ctx, position=80)
        receipt(runtime, ctx, position=0)
        await runtime.telemetry.flush()
        detail = await runtime.diagnostics.session_detail(ctx.voice_session_id)
        exact = [replace(event, turn_id=None) for event in detail.events if event.name == "client.playback_progress"]
        # Telemetry permits nullable turn; InteractionContext itself requires one.
        await runtime.diagnostics.delete_sessions([ctx.voice_session_id])
        await runtime.diagnostics.append_batch(exact)
        key = attachment(ctx)[:5] + (None,) + attachment(ctx)[6:]
        assert await runtime.diagnostics.playback_receipts_for([key]) == {key: 80}
        for index in range(10):
            value = 2 if index == 4 else 8000 if index == 9 else "foreign"
            foreign = key[:index] + (value,) + key[index + 1 :]
            assert await runtime.diagnostics.playback_receipts_for([foreign]) == {}
        assert await runtime.diagnostics.delete_sessions([ctx.voice_session_id]) == 1
        assert await runtime.diagnostics.playback_receipts_for([key]) == {}
    finally:
        await runtime.close()


async def test_postgres_lookup_uses_partial_index_and_restores_outer_timeout(postgres):
    pool, schema = postgres
    runtime = await runtime_for(schema, InMemoryS3ObjectClient())
    try:
        await assert_long_catalog(runtime)
        ctx = replace(context(), response_id="response")
        key = attachment(ctx)
        async with pool.acquire() as conn:
            await conn.execute(f'ANALYZE "{schema}".runtime_telemetry_records')

            class CapturingConnection:
                def __getattr__(self, name):
                    return getattr(conn, name)

                async def fetch(self, sql, *args):
                    self.query, self.args = sql, args
                    return await conn.fetch(sql, *args)

            captured = CapturingConnection()
            async with conn.transaction():
                await conn.execute("SET LOCAL statement_timeout='100ms'")
                assert await PostgresTelemetryStore(captured, schema=schema).playback_receipts_for(
                    [key]
                ) == {key: 80}
                assert await conn.fetchval("SHOW statement_timeout") == "100ms"
            raw = await conn.fetchval(
                "EXPLAIN (ANALYZE, FORMAT JSON) " + captured.query, *captured.args
            )
            plan = json.loads(raw)[0]["Plan"]

            def nodes(node):
                yield node
                for child in node.get("Plans", []):
                    yield from nodes(child)

            indexed = [
                node
                for node in nodes(plan)
                if node.get("Index Name") == "runtime_playback_attachment_idx"
            ]
            assert indexed and indexed[0]["Actual Rows"] == 1
            assert indexed[0].get("Rows Removed by Filter", 0) == 0
    finally:
        await runtime.close()


async def test_postgres_lookup_accepts_schema_visible_in_search_path(postgres):
    pool, schema = postgres
    runtime = await runtime_for(schema, InMemoryS3ObjectClient())
    ctx = replace(context(), response_id="response")
    try:
        receipt(runtime, ctx)
        await runtime.telemetry.flush()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT set_config('search_path',$1,true)", f'"{schema}", public')
            previous = await conn.fetchval("SHOW search_path")
            assert await PostgresTelemetryStore(conn, schema=schema).playback_receipts_for(
                [attachment(ctx)]
            ) == {attachment(ctx): 80}
            assert await conn.fetchval("SHOW search_path") == previous
    finally:
        await runtime.close()


async def test_postgres_attachment_digest_does_not_depend_on_shadowed_builtins(postgres):
    pool, schema = postgres
    async with pool.acquire() as conn:
        sql = f'''SELECT "{schema}".recording_playback_attachment_key('tenant','owner','session','thread',1,NULL,NULL,
            '{{"output_epoch":"epoch","speech_id":"speech","sample_rate_hz":16000}}'::jsonb)'''
        expected = await conn.fetchval(sql)
        await conn.execute(f'''CREATE FUNCTION "{schema}".sha256(bytea) RETURNS bytea LANGUAGE sql IMMUTABLE
            AS 'SELECT decode(repeat(''00'',32),''hex'')' ''')
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('search_path',$1,true)", f'"{schema}", pg_catalog'
            )
            assert await conn.fetchval(sql) == expected


@pytest.mark.parametrize("broken", ["missing", "predicate", "expression", "unique"])
async def test_postgres_incompatible_lookup_index_does_not_hide_audio(postgres, broken):
    pool, schema = postgres
    runtime = await runtime_for(schema, InMemoryS3ObjectClient())
    ctx = replace(context(), response_id="response")
    try:
        await sent_recording(runtime, ctx)
        receipt(runtime, ctx)
        await runtime.telemetry.flush()
        async with pool.acquire() as conn:
            await conn.execute(
                f'DROP INDEX CONCURRENTLY "{schema}".runtime_playback_attachment_idx'
            )
            if broken != "missing":
                expr = (
                    "voice_session_id, sequence"
                    if broken == "expression"
                    else f'"{schema}".recording_playback_attachment_key(tenant_id,user_id,voice_session_id,thread_id,generation,turn_id,response_id,attributes), "{schema}".recording_playback_sample_position(attributes) DESC'
                )
                predicate = (
                    f"name='client.playback_progress' AND outcome='ok' AND \"{schema}\".recording_playback_sample_position(attributes) IS NOT NULL"
                    if broken in {"expression", "unique"}
                    else "name='test.noise'"
                )
                kind = "UNIQUE " if broken == "unique" else ""
                await conn.execute(
                    f'CREATE {kind}INDEX CONCURRENTLY runtime_playback_attachment_idx ON "{schema}".runtime_telemetry_records ({expr}) WHERE {predicate}'
                )
        page = await runtime.recordings.read_page(ctx.voice_session_id)
        assert page["items"][0]["status"] == "available"
        assert page["playback_source"]["status"] == "unavailable"
        assert page["items"][0]["playback"]["overlap_samples"] is None
    finally:
        await runtime.close()
