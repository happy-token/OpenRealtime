from __future__ import annotations

from datetime import UTC, datetime

from server.core.interaction_context import InteractionContext
from server.observability.telemetry import (
    InMemoryTelemetryStore,
    RuntimeTelemetry,
    TelemetryIdentity,
    TelemetryOutcome,
)
from server.realtime.observability import RealtimeTelemetryObserver
from server.realtime.protocol import (
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
