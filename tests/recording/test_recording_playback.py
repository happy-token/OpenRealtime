from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.observability.telemetry import TelemetryIdentity
from server.realtime.observability import RealtimeTelemetryObserver
from server.realtime.protocol import PlaybackPrecision, SpeechPlaybackProgress
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_session_audio_recording import audio


async def sent_recording(runtime, ctx, *, start=0, stream="speech", epoch="output"):
    recorder = runtime.open_recording(ctx)
    recorder.capture(
        "sent",
        replace(audio(timestamp=start), stream_id=stream),
        context=ctx,
        epoch=epoch,
        speech_id="speech",
    )
    assert await recorder.close()


def receipt(
    runtime, ctx, *, epoch="output", position=80, precise=True, rate=16000, speech="speech"
):
    telemetry = runtime.telemetry.bind(
        TelemetryIdentity(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            device_id=ctx.device_id,
            voice_session_id=ctx.voice_session_id,
            thread_id=ctx.thread_id,
        )
    )
    RealtimeTelemetryObserver(telemetry).observe_event(
        SpeechPlaybackProgress(
            event_id="receipt",
            context=ctx,
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            speech_id=speech,
            delivered_text_end=0,
            delivered_speech_transcript="",
            played_audio_end_us=position * 1000000 // rate,
            precision=PlaybackPrecision.SEGMENT,
            completed=False,
            output_epoch=epoch if precise else None,
            played_position_samples=position if precise else None,
            sample_rate_hz=rate if precise else None,
        )
    )


@pytest.mark.asyncio
async def test_scoped_actual_receipt_projects_only_its_overlap_with_saved_audio():
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx = replace(context(), response_id="response")
    try:
        await sent_recording(runtime, ctx, start=2500)
        receipt(runtime, ctx)
        await runtime.telemetry.flush()
        page = await runtime.recordings.read_page(ctx.voice_session_id)
        assert page["items"][0]["start_sample"] == 40
        assert page["items"][0]["playback"] == {
            "status": "reported",
            "reported_end_sample": 80,
            "overlap_samples": 40,
            "sample_rate_hz": 16000,
        }
        assert page["items"][0]["playback_confirmation"] == "not-inferred"
        assert page["playback_source"]["status"] == "available"
        assert not page["playback_source"]["truncated"]
    finally:
        await runtime.close()


@pytest.mark.parametrize("position,overlap", [(0, 0), (40, 0), (80, 40), (200, 160)])
async def test_reported_prefix_is_clipped_to_each_actual_saved_interval(position, overlap):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx = replace(context(), response_id="response")
    try:
        await sent_recording(runtime, ctx, start=2500)
        receipt(runtime, ctx, position=position)
        if position > 0:
            receipt(
                runtime, ctx, position=0
            )  # Late smaller raw receipt cannot erase positive evidence.
        await runtime.telemetry.flush()
        view = (await runtime.recordings.read_page(ctx.voice_session_id))["items"][0]["playback"]
        assert view["status"] == "reported" and view["overlap_samples"] == overlap
        assert view["reported_end_sample"] == position
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "key",
    [
        "tenant_id",
        "user_id",
        "voice_session_id",
        "thread_id",
        "generation",
        "turn_id",
        "response_id",
        "epoch",
        "speech",
        "rate",
        "stream",
        "legacy",
        "missing",
    ],
)
async def test_missing_legacy_or_foreign_receipts_never_claim_a_saved_interval(key):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx = replace(context(), response_id="response")
    try:
        await sent_recording(runtime, ctx, stream="foreign-stream" if key == "stream" else "speech")
        other = replace(
            ctx,
            **(
                {key: 2 if key == "generation" else "foreign"}
                if key
                in {
                    "tenant_id",
                    "user_id",
                    "voice_session_id",
                    "thread_id",
                    "generation",
                    "turn_id",
                    "response_id",
                }
                else {}
            ),
        )
        if key != "missing":
            receipt(
                runtime,
                other,
                epoch="foreign" if key == "epoch" else "output",
                speech="foreign" if key == "speech" else "speech",
                rate=8000 if key == "rate" else 16000,
                precise=key != "legacy",
            )
        await runtime.telemetry.flush()
        view = (await runtime.recordings.read_page(ctx.voice_session_id))["items"][0]["playback"]
        assert view == {
            "status": "unknown",
            "reported_end_sample": None,
            "overlap_samples": None,
            "sample_rate_hz": None,
        }
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "attrs",
    [
        {"played_position_samples": True},
        {"sample_rate_hz": False},
        {"played_audio_end_us": 999},
        {"precision": "estimated"},
        {"completed": True, "started": True},
        {"played_position_samples": -1},
        {"output_epoch": ""},
    ],
)
async def test_malformed_persisted_receipts_are_not_reclassified_as_exact(attrs):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx = replace(context(), response_id="response")
    try:
        await sent_recording(runtime, ctx)
        receipt(runtime, ctx)
        await runtime.telemetry.flush()
        store = runtime.diagnostics
        event = next(event for event in store._records if event.name == "client.playback_progress")
        store._records.remove(event)
        await store.append_batch(
            [replace(event, event_id="bad", attributes=dict(event.attributes) | attrs)]
        )
        view = (await runtime.recordings.read_page(ctx.voice_session_id))["items"][0]["playback"]
        assert view["status"] == "unknown" and view["overlap_samples"] is None
    finally:
        await runtime.close()


async def test_truncated_evidence_retains_found_prefix_but_never_proves_absence(monkeypatch):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx = replace(context(), response_id="response")
    original = runtime.diagnostics.session_detail

    async def truncated(*args, **kwargs):
        return replace(await original(*args, **kwargs), next_cursor="later")

    try:
        await sent_recording(runtime, ctx)
        receipt(runtime, ctx)
        await runtime.telemetry.flush()
        monkeypatch.setattr(runtime.diagnostics, "session_detail", truncated)
        page = await runtime.recordings.read_page(ctx.voice_session_id)
        assert page["playback_source"]["truncated"] is True
        assert page["items"][0]["playback"]["overlap_samples"] == 80
    finally:
        await runtime.close()


@pytest.mark.parametrize("late_failure", [False, True])
async def test_slow_playback_evidence_degrades_without_abandoning_actual_io(
    monkeypatch, late_failure
):
    from server.application.recording import RecordingWritesPending
    from server.realtime.registry import SessionHistoryDeletionConflict

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx = replace(context(), response_id="response")
    entered, release = asyncio.Event(), asyncio.Event()
    original = runtime.diagnostics.session_detail

    async def blocked(*args, **kwargs):
        entered.set()
        await release.wait()
        if late_failure:
            raise RuntimeError("late source failure")

    try:
        await sent_recording(runtime, ctx)
        monkeypatch.setattr(runtime.diagnostics, "session_detail", blocked)
        runtime.recordings._query_timeout_s = 0.1
        runtime.recordings._optional_timeout_s = 0.01
        page = await runtime.recordings.read_page(ctx.voice_session_id)
        assert entered.is_set() and runtime.recordings._reads
        assert page["items"][0]["status"] == "available"
        assert page["preservation"]["status"] == "unmarked"
        assert page["playback_source"]["status"] == "unavailable"
        assert page["items"][0]["playback"]["status"] == "unavailable"
        # Scope resolution also uses DiagnosticsQuery; only the already-owned child is held.
        monkeypatch.setattr(runtime.diagnostics, "session_detail", original)
        with pytest.raises(SessionHistoryDeletionConflict):
            await runtime.delete_session_history(
                [ctx.voice_session_id], tenant_id="admin", user_id="admin"
            )
        with pytest.raises(RecordingWritesPending):
            await runtime.recordings.close()
    finally:
        release.set()
        async with asyncio.timeout(1):
            while runtime.recordings._reads:
                await asyncio.sleep(0)
        await runtime.close()


@pytest.mark.parametrize("source", ["policy", "playback"])
async def test_optional_child_cancellation_does_not_cancel_the_audio_catalog(monkeypatch, source):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx = replace(context(), response_id="response")

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    try:
        await sent_recording(runtime, ctx)
        if source == "policy":
            monkeypatch.setattr(
                runtime.recordings.artifacts, "get_session_preservation_for", cancelled
            )
        else:
            monkeypatch.setattr(runtime.diagnostics, "session_detail", cancelled)
        page = await runtime.recordings.read_page(ctx.voice_session_id)
        assert page["items"][0]["status"] == "available"
        assert (
            page["preservation" if source == "policy" else "playback_source"]["status"]
            == "unavailable"
        )
        assert not runtime.recordings._reads
    finally:
        await runtime.close()
