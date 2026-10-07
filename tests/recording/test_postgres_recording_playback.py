from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest

from server.artifacts import InMemoryS3ObjectClient
from tests.persistence.test_postgres_artifact_store import postgres as postgres  # noqa: PLC0414
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_postgres_recording_history_preservation import runtime_for
from tests.recording.test_recording_playback import receipt, sent_recording

pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)


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
