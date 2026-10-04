from __future__ import annotations

from datetime import UTC, datetime

from server.core.interaction_context import InteractionContext
from server.observability.telemetry import (
    InMemoryDebugLogStore,
    InMemoryTelemetryStore,
    RuntimeDebugLog,
    RuntimeTelemetry,
    TelemetryIdentity,
    TelemetryOutcome,
)
from server.realtime.observability import RealtimeTelemetryObserver
from server.realtime.protocol import (
    AssistantYieldRequested,
    AudioDelta,
    AudioEncoding,
    AudioFrame,
    DisplayContentDelta,
    InputTranscriptCompleted,
    InputTranscriptDelta,
    PlaybackPrecision,
    RealtimeCapabilityFailed,
    RequestResponse,
    ResponseCompleted,
    ResponseStarted,
    SpeechPlaybackProgress,
)


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
        response_id="response-1",
    )


async def test_realtime_observer_projects_response_latency_and_terminal_outcome() -> None:
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store, flush_interval_s=0.01)
    await runtime.start()
    telemetry = runtime.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )
    observer = RealtimeTelemetryObserver(telemetry)
    now = datetime.now(UTC)

    observer.observe_command(
        RequestResponse(
            command_id="request-1",
            idempotency_key="request-1",
            context=context(),
            response_id="response-1",
            minimum_thread_sequence=1,
        )
    )
    observer.observe_event(
        ResponseStarted(
            event_id="started-1",
            context=context(),
            conversation_sequence=1,
            occurred_at=now,
            response_id="response-1",
            response_sequence=1,
        )
    )
    observer.observe_event(
        DisplayContentDelta(
            event_id="text-1",
            context=context(),
            conversation_sequence=2,
            occurred_at=now,
            response_id="response-1",
            response_sequence=2,
            delta="你好",
        )
    )
    observer.observe_event(
        AudioDelta(
            event_id="audio-1",
            context=context(),
            conversation_sequence=3,
            occurred_at=now,
            response_id="response-1",
            response_sequence=3,
            frame=AudioFrame(
                stream_id="tts-1",
                sequence=0,
                timestamp_us=0,
                duration_us=20_000,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=24_000,
                channels=1,
                data=b"\x00\x00",
            ),
            segment_index=0,
        )
    )
    observer.observe_event(
        ResponseCompleted(
            event_id="completed-1",
            context=context(),
            conversation_sequence=4,
            occurred_at=now,
            response_id="response-1",
            response_sequence=4,
        )
    )

    await runtime.flush()
    detail = await runtime.diagnostics.session_detail("voice-1")
    assert detail is not None
    names = [record.name for record in detail.events]
    assert set(names) == {
        "realtime.response_requested",
        "brain.response_started",
        "brain.time_to_first_text",
        "tts.time_to_first_audio",
        "turn.total",
    }
    terminal = next(record for record in detail.events if record.name == "turn.total")
    assert terminal.outcome is TelemetryOutcome.OK
    await runtime.close()


async def test_realtime_observer_classifies_response_deadline_as_timeout() -> None:
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store, flush_interval_s=0.01)
    await runtime.start()
    telemetry = runtime.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )
    observer = RealtimeTelemetryObserver(telemetry)
    observer.observe_event(
        RealtimeCapabilityFailed(
            event_id="failure-1",
            context=context(),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            capability="response_deadline",
            error="response deadline exceeded after 30.000s",
        )
    )

    await runtime.flush()
    detail = await runtime.diagnostics.session_detail("voice-1")
    assert detail is not None
    assert detail.events[0].name == "realtime.capability.response_deadline"
    assert detail.events[0].outcome is TelemetryOutcome.TIMEOUT
    await runtime.close()


async def test_realtime_observer_records_partial_asr_progress_without_raw_text() -> None:
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store, flush_interval_s=0.01)
    await runtime.start()
    telemetry = runtime.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )
    observer = RealtimeTelemetryObserver(telemetry)

    observer.observe_event(
        InputTranscriptDelta(
            event_id="partial-1",
            context=context(),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            text="给我讲个故事",
            delta="故事",
            transcript_revision=3,
            audio_timestamp_us=320_000,
        )
    )

    await runtime.flush()
    detail = await runtime.diagnostics.session_detail("voice-1")
    assert detail is not None
    assert detail.events[0].name == "asr.transcript_delta"
    assert detail.events[0].attributes == {
        "audio_timestamp_us": 320_000,
        "replaces_previous": False,
        "text_length": 6,
        "transcript_revision": 3,
    }
    await runtime.close()


async def test_realtime_observer_measures_barge_in_time_to_client_stop() -> None:
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store, flush_interval_s=0.01)
    await runtime.start()
    telemetry = runtime.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )
    debug_runtime = RuntimeDebugLog(InMemoryDebugLogStore())
    await debug_runtime.start()
    debug_log = debug_runtime.bind("voice-1")
    observer = RealtimeTelemetryObserver(telemetry, debug_log=debug_log)

    observer.observe_event(
        AssistantYieldRequested(
            event_id="yield-1",
            context=context(),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            reason="barge_in_floor_claim",
        )
    )
    observer.observe_event(
        SpeechPlaybackProgress(
            event_id="progress-1",
            context=context(),
            conversation_sequence=2,
            occurred_at=datetime.now(UTC),
            speech_id="speech-1",
            delivered_text_end=2,
            delivered_speech_transcript="你好",
            played_audio_end_us=12_000,
            precision=PlaybackPrecision.SEGMENT,
            completed=False,
            stopped=True,
        )
    )

    await runtime.flush()
    detail = await runtime.diagnostics.session_detail("voice-1")
    assert detail is not None
    names = [record.name for record in detail.events]
    assert "barge_in.detected" in names
    assert "barge_in.time_to_client_stop" in names
    stop_span = next(
        record for record in detail.events if record.name == "barge_in.time_to_client_stop"
    )
    assert stop_span.duration_ms is not None
    assert stop_span.duration_ms >= 0

    await debug_runtime.flush()
    timeline = await debug_runtime.query.session_timeline("voice-1")
    assert [entry.event for entry in timeline] == [
        "barge_in_detected",
        "barge_in_client_stopped",
    ]

    await runtime.close()
    await debug_runtime.close()


async def test_realtime_observer_does_not_measure_stop_for_normal_playback_progress() -> None:
    """A non-final progress report with no preceding yield must not fabricate
    a barge-in span — only a real AssistantYieldRequested starts the clock."""

    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store, flush_interval_s=0.01)
    await runtime.start()
    telemetry = runtime.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )
    observer = RealtimeTelemetryObserver(telemetry)

    observer.observe_event(
        SpeechPlaybackProgress(
            event_id="progress-1",
            context=context(),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            speech_id="speech-1",
            delivered_text_end=0,
            delivered_speech_transcript="",
            played_audio_end_us=0,
            precision=PlaybackPrecision.SEGMENT,
            completed=False,
        )
    )

    await runtime.flush()
    detail = await runtime.diagnostics.session_detail("voice-1")
    assert detail is not None
    names = [record.name for record in detail.events]
    assert "barge_in.time_to_client_stop" not in names
    await runtime.close()


async def test_realtime_observer_records_endpoint_to_first_client_playback(
    monkeypatch,
) -> None:
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store, flush_interval_s=0.01)
    await runtime.start()
    telemetry = runtime.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )
    observer = RealtimeTelemetryObserver(telemetry)
    monotonic_times = iter((10_000_000_000, 10_700_000_000))
    monkeypatch.setattr(
        "server.realtime.observability.time.monotonic_ns",
        lambda: next(monotonic_times),
    )
    now = datetime.now(UTC)

    observer.observe_event(
        InputTranscriptCompleted(
            event_id="input-completed-1",
            context=context(),
            conversation_sequence=1,
            occurred_at=now,
            text="你好",
            transcript_revision=1,
            provider_endpoint_observed=True,
        )
    )
    observer.observe_event(
        SpeechPlaybackProgress(
            event_id="playback-started-1",
            context=context(),
            conversation_sequence=2,
            occurred_at=now,
            speech_id="response:response-1",
            delivered_text_end=0,
            delivered_speech_transcript="",
            played_audio_end_us=0,
            precision=PlaybackPrecision.EXACT,
            completed=False,
            started=True,
        )
    )

    await runtime.flush()
    detail = await runtime.diagnostics.session_detail("voice-1")
    assert detail is not None
    metric = next(
        event
        for event in detail.events
        if event.name == "turn.endpoint_to_client_playback"
    )
    assert metric.duration_ms == 700.0
    await runtime.close()


async def test_stop_ack_is_explicit_and_survives_response_cancellation() -> None:
    from dataclasses import replace
    from server.realtime.protocol import ResponseCancelled
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store)
    await runtime.start()
    try:
        telemetry = runtime.bind(TelemetryIdentity("t", "u", "d", "voice-1", "thread"))
        observer = RealtimeTelemetryObserver(telemetry)
        now = datetime.now(UTC)
        base = dict(context=context(), conversation_sequence=1, occurred_at=now)
        observer.observe_event(AssistantYieldRequested(event_id="yield", reason="barge_in_floor_claim", **base))
        progress = SpeechPlaybackProgress(event_id="progress", speech_id="speech", delivered_text_end=0, delivered_speech_transcript="", played_audio_end_us=0, precision=PlaybackPrecision.SEGMENT, completed=False, **base)
        observer.observe_event(progress)
        await runtime.flush()
        detail = await runtime.diagnostics.session_detail("voice-1")
        assert not any(e.name == "barge_in.time_to_client_stop" for e in detail.events)
        observer.observe_event(ResponseCancelled(event_id="cancel", response_id="response-1", response_sequence=1, reason="barge_in_floor_claim", **base))
        observer.observe_event(replace(progress, event_id="stopped", stopped=True))
        await runtime.flush()
        detail = await runtime.diagnostics.session_detail("voice-1")
        assert len([e for e in detail.events if e.name == "barge_in.time_to_client_stop"]) == 1
    finally:
        await runtime.close()


async def test_direct_metric_records_inherit_task_local_generation() -> None:
    from server.observability.telemetry import telemetry_generation_scope
    runtime = RuntimeTelemetry(InMemoryTelemetryStore())
    await runtime.start()
    try:
        telemetry = runtime.bind(TelemetryIdentity("t", "u", "d", "voice-1", "thread"))
        with telemetry_generation_scope(7):
            record = telemetry.record("llm.request_to_first_text", duration_ms=100)
        assert record.generation == 7
        assert telemetry.record("unscoped").generation is None
    finally:
        await runtime.close()


async def test_stop_for_another_response_does_not_consume_pending_yield() -> None:
    from dataclasses import replace
    runtime = RuntimeTelemetry(InMemoryTelemetryStore())
    await runtime.start()
    try:
        observer = RealtimeTelemetryObserver(runtime.bind(TelemetryIdentity("t", "u", "d", "voice-1", "thread")))
        now = datetime.now(UTC)
        observer.observe_event(AssistantYieldRequested(event_id="yield", context=context(), conversation_sequence=1, occurred_at=now, reason="barge_in_floor_claim"))
        progress = SpeechPlaybackProgress(event_id="wrong-stop", context=replace(context(), response_id="response-2", generation=2), conversation_sequence=2, occurred_at=now, speech_id="response:response-2", delivered_text_end=0, delivered_speech_transcript="", played_audio_end_us=0, precision=PlaybackPrecision.SEGMENT, completed=False, stopped=True)
        observer.observe_event(progress)
        await runtime.flush()
        assert not any(event.name == "barge_in.time_to_client_stop" for event in (await runtime.diagnostics.session_detail("voice-1")).events)
        observer.observe_event(replace(progress, event_id="correct-stop", context=context(), speech_id="response:response-1"))
        await runtime.flush()
        metrics = [event for event in (await runtime.diagnostics.session_detail("voice-1")).events if event.name == "barge_in.time_to_client_stop"]
        assert len(metrics) == 1
        assert metrics[0].generation == 1
        assert metrics[0].response_id == "response-1"
    finally:
        await runtime.close()
