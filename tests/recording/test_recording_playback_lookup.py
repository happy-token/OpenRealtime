from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_recording_playback import receipt, sent_recording


def attachment(ctx):
    return (
        ctx.tenant_id,
        ctx.user_id,
        ctx.voice_session_id,
        ctx.thread_id,
        ctx.generation,
        ctx.turn_id,
        ctx.response_id,
        "output",
        "speech",
        16000,
    )


async def fill_long_session(runtime, ctx):
    receipt(runtime, ctx)
    await runtime.telemetry.flush()
    detail = await runtime.diagnostics.session_detail(ctx.voice_session_id)
    event = next(event for event in detail.events if event.name == "client.playback_progress")
    await runtime.diagnostics.append_batch(
        [
            replace(
                event,
                event_id=f"noise-{index}",
                name="test.noise",
                attributes={},
                occurred_at=event.occurred_at - timedelta(seconds=1),
                sequence=index + 1,
            )
            for index in range(5001)
        ]
    )
    # The exact receipt is genuinely beyond the first diagnostic page.
    first = await runtime.diagnostics.session_detail(ctx.voice_session_id)
    assert first.next_cursor is not None
    assert all(event.name != "client.playback_progress" for event in first.events)


async def assert_long_catalog(runtime):
    ctx = replace(context(), response_id="response")
    await sent_recording(runtime, ctx)
    await fill_long_session(runtime, ctx)
    page = await runtime.recordings.read_page(ctx.voice_session_id)
    assert page["items"][0]["playback"]["status"] == "reported"
    assert page["items"][0]["playback"]["overlap_samples"] == 80
    assert page["playback_source"]["truncated"] is False


async def test_catalog_finds_exact_receipt_beyond_the_first_5000_events():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    try:
        await assert_long_catalog(runtime)
    finally:
        await runtime.close()


async def test_memory_lookup_never_scans_general_telemetry_after_ingestion():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx = replace(context(), response_id="response")
    try:
        await sent_recording(runtime, ctx)
        receipt(runtime, ctx)
        await runtime.telemetry.flush()

        class NoScan(list):
            def __iter__(self):
                raise AssertionError("playback lookup scanned general telemetry")

        runtime.diagnostics._records = NoScan(runtime.diagnostics._records)
        page = await runtime.recordings.read_page(ctx.voice_session_id)
        assert page["items"][0]["playback"]["status"] == "reported"
        assert page["items"][0]["playback"]["overlap_samples"] == 80
    finally:
        await runtime.close()


async def test_memory_receipt_index_deletion_reingestion_and_late_prefixes():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx, foreign = (
        replace(context(), response_id="response"),
        replace(context(), voice_session_id="foreign"),
    )
    key, other = attachment(ctx), attachment(foreign)
    try:
        receipt(runtime, ctx, position=80)
        receipt(runtime, ctx, position=0)
        receipt(runtime, foreign, position=120)
        await runtime.telemetry.flush()
        store = runtime.diagnostics
        assert await store.playback_receipts_for([key, other, key]) == {key: 80, other: 120}
        assert await store.delete_sessions([ctx.voice_session_id]) == 1
        assert await store.playback_receipts_for([key, other]) == {other: 120}
        receipt(runtime, ctx, position=0)
        await runtime.telemetry.flush()
        assert await store.playback_receipts_for([key]) == {key: 0}
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "bad",
    [
        "too-many",
        "bool-generation",
        "bool-rate",
        "bad-null",
        "empty-epoch",
        "unsafe-generation",
        "empty-key",
    ],
)
async def test_targeted_lookup_rejects_invalid_attachment_requests(bad):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    key = attachment(context())
    cases = {
        "too-many": [key] * 201,
        "bool-generation": [key[:4] + (True,) + key[5:]],
        "bool-rate": [key[:9] + (True,)],
        "bad-null": [key[:5] + (False,) + key[6:]],
        "empty-epoch": [key[:7] + ("",) + key[8:]],
        "unsafe-generation": [key[:4] + (2**53,) + key[5:]],
        "empty-key": [()],
    }
    try:
        with pytest.raises(ValueError):
            await runtime.diagnostics.playback_receipts_for(cases[bad])
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "bad",
    [
        "foreign",
        "unsafe",
        "bool",
        "float",
        "too-much-clock",
        "bool-generation",
        "float-generation",
        "float-rate",
    ],
)
async def test_bad_optional_targeted_result_does_not_hide_audio(monkeypatch, bad):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx = replace(context(), response_id="response")

    async def invalid(keys):
        key = keys[0]
        if bad == "foreign":
            return {("foreign",) + key[1:]: 80}
        if bad in {"bool-generation", "float-generation"}:
            return {key[:4] + (True if bad == "bool-generation" else float(key[4]),) + key[5:]: 80}
        if bad == "float-rate":
            return {key[:9] + (float(key[9]),): 80}
        return {
            key: {"unsafe": 2**53, "bool": True, "float": 80.0, "too-much-clock": 2**53 - 1}[bad]
        }

    try:
        await sent_recording(runtime, ctx)
        monkeypatch.setattr(runtime.diagnostics, "playback_receipts_for", invalid)
        page = await runtime.recordings.read_page(ctx.voice_session_id)
        assert page["items"][0]["status"] == "available"
        assert page["playback_source"]["status"] == "unavailable"
        assert page["items"][0]["playback"]["overlap_samples"] is None
    finally:
        await runtime.close()
