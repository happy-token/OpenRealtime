from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from server.ledger.event_ledger import LedgerEvent
from server.observability.latency import LatencyMilestone, ResponseLatencyTrace
from server.observability.telemetry import (
    DiagnosticsWindow,
    InMemoryTelemetryStore,
    RuntimeTelemetry,
    TelemetryIdentity,
    TelemetryKind,
    TelemetryOutcome,
    telemetry_generation_scope,
)


class BlockingTelemetryStore(InMemoryTelemetryStore):
    def __init__(self) -> None:
        super().__init__()
        self.write_started = asyncio.Event()
        self.release_write = asyncio.Event()

    async def append_batch(self, records) -> None:
        self.write_started.set()
        await self.release_write.wait()
        await super().append_batch(records)


async def test_runtime_queue_is_bounded_when_storage_stalls() -> None:
    store = BlockingTelemetryStore()
    telemetry = RuntimeTelemetry(
        store,
        batch_size=1,
        max_queue_size=1,
    )
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-overload",
            thread_id="voice-overload",
        )
    )

    session.record("first")
    await store.write_started.wait()
    session.record("queued")
    session.record("dropped")

    assert telemetry.pending_records == 1
    assert telemetry.dropped_records == 1

    store.release_write.set()
    await telemetry.close()


async def test_overview_aggregates_latency_timeouts_errors_and_no_response() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store, batch_size=2)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="browser",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )

    for generation, duration_ms, outcome in (
        (1, 100.0, TelemetryOutcome.OK),
        (2, 200.0, TelemetryOutcome.TIMEOUT),
        (3, 300.0, TelemetryOutcome.ERROR),
        (4, 400.0, TelemetryOutcome.OK),
    ):
        session.record(
            "asr.final_tail",
            generation=generation,
            kind=TelemetryKind.SPAN,
            duration_ms=duration_ms,
            timeout_ms=250.0,
            outcome=outcome,
        )

    session.turn_terminal(1, outcome=TelemetryOutcome.OK, duration_ms=900.0)
    session.turn_terminal(2, outcome=TelemetryOutcome.NO_RESPONSE, duration_ms=5000.0)
    session.turn_terminal(3, outcome=TelemetryOutcome.ERROR, duration_ms=1200.0)
    await telemetry.flush()

    overview = await store.overview(DiagnosticsWindow.last(timedelta(hours=1)))
    asr = next(metric for metric in overview.metrics if metric.name == "asr.final_tail")

    assert asr.sample_count == 4
    assert asr.p50_ms == 200.0
    assert asr.p95_ms == 400.0
    assert asr.p99_ms == 400.0
    assert asr.max_ms == 400.0
    assert asr.timeout_count == 1
    assert asr.error_count == 1
    assert overview.turn_count == 3
    assert overview.successful_turn_count == 1
    assert overview.no_response_count == 1
    assert overview.error_count == 2

    await telemetry.close()


async def test_overview_separates_expected_barge_in_from_failed_turns() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-barge-in",
            thread_id="voice-barge-in",
        )
    )

    session.turn_terminal(
        1,
        outcome=TelemetryOutcome.CANCELLED,
        duration_ms=50,
        error="text_barge_in",
    )
    session.record(
        "provider.deepseek.tool_chat.complete",
        generation=1,
        kind=TelemetryKind.PROVIDER_CALL,
        outcome=TelemetryOutcome.CANCELLED,
        duration_ms=45,
        error="CancelledError",
    )
    session.turn_terminal(2, outcome=TelemetryOutcome.OK, duration_ms=900)
    await telemetry.flush()

    overview = await store.overview(DiagnosticsWindow.last(timedelta(hours=1)))

    assert overview.turn_count == 2
    assert overview.interrupted_count == 1
    assert overview.cancelled_count == 0
    assert overview.success_rate == 1.0

    await telemetry.close()


async def test_session_detail_returns_ordered_redacted_timeline() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-2",
            thread_id="voice-2",
        )
    )

    session.record(
        "asr.partial",
        generation=1,
        attributes={
            "text": "不应保存的原始文本",
            "revision": 1,
            "api_key": "secret",
            "token": "secret-token",
            "pcm16": b"raw-audio",
            "audio_sent": True,
            "token_count": 42,
        },
    )
    session.record(
        "llm.first_token",
        generation=1,
        kind=TelemetryKind.SPAN,
        duration_ms=321.0,
        attributes={"provider": "deepseek"},
    )
    await telemetry.flush()

    detail = await store.session_detail("voice-2")

    assert detail is not None
    assert [event.name for event in detail.events] == [
        "asr.partial",
        "llm.first_token",
    ]
    assert detail.events[0].attributes == {
        "audio_sent": True,
        "revision": 1,
        "text_length": 9,
        "token_count": 42,
    }
    assert detail.events[1].attributes["provider"] == "deepseek"

    await telemetry.close()


async def test_delete_sessions_removes_only_selected_telemetry() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    for session_id in ("voice-delete", "voice-keep"):
        session = telemetry.bind(
            TelemetryIdentity(
                tenant_id="local",
                user_id="user",
                device_id="browser",
                voice_session_id=session_id,
                thread_id=session_id,
            )
        )
        session.record("turn.total", duration_ms=100)
    await telemetry.flush()

    deleted = await telemetry.delete_sessions(["voice-delete"])

    assert deleted == 1
    assert await store.session_detail("voice-delete") is None
    assert await store.session_detail("voice-keep") is not None
    await telemetry.close()


async def test_diagnostics_window_excludes_old_records() -> None:
    store = InMemoryTelemetryStore()
    now = datetime.now(UTC)
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-3",
            thread_id="voice-3",
        )
    )
    session.record("old", generation=1, duration_ms=10, occurred_at=now - timedelta(days=2))
    session.record("new", generation=2, duration_ms=20, occurred_at=now)
    await telemetry.flush()

    overview = await store.overview(DiagnosticsWindow(since=now - timedelta(hours=1)))

    assert [metric.name for metric in overview.metrics] == ["new"]

    await telemetry.close()


async def test_ledger_observer_maps_stage_failures_without_blocking_on_storage() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-4",
            thread_id="voice-4",
        )
    )

    await session.observe_ledger(
        LedgerEvent(
            name="stage_span",
            generation=7,
            payload={
                "stage": "turn_policy.eot_classify",
                "status": "timeout",
                "duration_ms": 1000.0,
                "timeout_ms": 1000.0,
                "error": "TimeoutError: classifier deadline",
                "text": "不得保存",
            },
        )
    )
    await telemetry.flush()

    detail = await store.session_detail("voice-4")

    assert detail is not None
    event = detail.events[0]
    assert event.name == "turn_policy.eot_classify"
    assert event.kind is TelemetryKind.SPAN
    assert event.outcome is TelemetryOutcome.TIMEOUT
    assert event.duration_ms == 1000.0
    assert event.error_type == "TimeoutError"
    assert event.attributes["text_length"] == 4

    await telemetry.close()


async def test_latency_trace_projects_named_critical_path_metrics() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-5",
            thread_id="voice-5",
        )
    )
    trace = ResponseLatencyTrace(response_id="response-5", generation=5)
    session.observe_latency(trace)

    trace.mark(LatencyMilestone.TURN_ACCEPTED, at=10.0)
    trace.mark(LatencyMilestone.ENGINE_STARTED, at=10.01)
    trace.mark(LatencyMilestone.FIRST_TEXT_DELTA, at=10.30)
    trace.mark(LatencyMilestone.FIRST_SPEAKABLE_SEGMENT, at=10.35)
    trace.mark(LatencyMilestone.TTS_REQUESTED, at=10.36)
    trace.mark(LatencyMilestone.TTS_FIRST_AUDIO, at=10.44)
    trace.mark(LatencyMilestone.FIRST_AUDIO_DELTA, at=10.45)
    trace.mark(LatencyMilestone.RESPONSE_TERMINAL, at=10.70)
    await telemetry.flush()

    detail = await store.session_detail("voice-5")

    assert detail is not None
    durations = {
        event.name: event.duration_ms
        for event in detail.events
        if event.duration_ms is not None
    }
    assert durations["engine.time_to_first_text"] == 300.0
    assert durations["engine.time_to_first_speakable"] == 350.0
    assert durations["tts.time_to_first_audio"] == 80.0
    assert durations["engine.time_to_first_audio"] == 450.0
    assert durations["engine.total"] == 700.0

    await telemetry.close()


async def test_session_anchors_derive_endpoint_and_client_playback_latency() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-6",
            thread_id="voice-6",
        )
    )

    await session.observe_ledger(
        LedgerEvent(
            name="endpoint_candidate_started",
            generation=6,
            payload={"_monotonic_ns": 10_000_000_000, "source": "asr_sentence_end"},
        )
    )
    await session.observe_ledger(
        LedgerEvent(
            name="endpoint_committed",
            generation=6,
            payload={"_monotonic_ns": 10_400_000_000, "stop_source": "vad_stop"},
        )
    )
    trace = ResponseLatencyTrace(response_id="response-6", generation=6)
    session.observe_latency(trace)
    trace.mark(LatencyMilestone.TURN_ACCEPTED, at=10.41)
    trace.mark(LatencyMilestone.FIRST_TEXT_DELTA, at=10.70)
    trace.mark(LatencyMilestone.FIRST_AUDIO_DELTA, at=10.90)
    await session.observe_ledger(
        LedgerEvent(
            name="client_playback_started",
            generation=6,
            payload={"_monotonic_ns": 11_000_000_000},
        )
    )
    await telemetry.flush()

    detail = await store.session_detail("voice-6")

    assert detail is not None
    durations = {
        event.name: event.duration_ms
        for event in detail.events
        if event.duration_ms is not None
    }
    assert durations["endpoint.commit_wait"] == 400.0
    assert durations["turn.endpoint_to_first_text"] == 700.0
    assert durations["turn.endpoint_to_first_audio"] == 900.0
    assert durations["turn.endpoint_to_client_playback"] == 1000.0

    await telemetry.close()


async def test_provider_call_records_ttfb_timeout_and_provider_dimensions() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-7",
            thread_id="voice-7",
        )
    )
    session.record("endpoint_candidate_started", generation=7)

    with pytest.raises(TimeoutError):
        async with session.provider_call(
            provider="deepseek",
            operation="chat.stream",
            model="deepseek-v4-flash",
            timeout_ms=1500,
        ) as call:
            call.mark_first_response()
            raise TimeoutError("provider deadline")
    await telemetry.flush()

    detail = await store.session_detail("voice-7")

    assert detail is not None
    event = detail.events[-1]
    assert event.name == "provider.deepseek.chat.stream"
    assert event.kind is TelemetryKind.PROVIDER_CALL
    assert event.outcome is TelemetryOutcome.TIMEOUT
    assert event.generation == 7
    assert event.timeout_ms == 1500.0
    assert event.attributes["model"] == "deepseek-v4-flash"
    assert event.attributes["ttfb_ms"] >= 0

    await telemetry.close()


async def test_provider_call_uses_task_local_generation_under_concurrency() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-provider-correlation",
            thread_id="voice-provider-correlation",
        )
    )
    first_started = asyncio.Event()
    finish_first = asyncio.Event()

    async def first_turn() -> None:
        with telemetry_generation_scope(1):
            async with session.provider_call(
                provider="deepseek", operation="responses.stream"
            ):
                first_started.set()
                await finish_first.wait()

    async def second_turn() -> None:
        await first_started.wait()
        with telemetry_generation_scope(2):
            async with session.provider_call(
                provider="deepseek", operation="tool_chat.complete"
            ):
                finish_first.set()

    await asyncio.gather(first_turn(), second_turn())
    await telemetry.flush()
    detail = await store.session_detail("voice-provider-correlation")

    assert detail is not None
    generations = {event.name: event.generation for event in detail.events}
    assert generations == {
        "provider.deepseek.responses.stream": 1,
        "provider.deepseek.tool_chat.complete": 2,
    }
    await telemetry.close()


async def test_provider_call_keeps_generation_active_when_span_started() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-provider-snapshot",
            thread_id="voice-provider-snapshot",
        )
    )
    session.record("turn.started", generation=1)

    async with session.provider_call(
        provider="deepseek", operation="responses.stream"
    ):
        session.record("next-turn.started", generation=2)
    await telemetry.flush()
    detail = await store.session_detail("voice-provider-snapshot")

    assert detail is not None
    provider = next(event for event in detail.events if event.kind is TelemetryKind.PROVIDER_CALL)
    assert provider.generation == 1
    await telemetry.close()


async def test_eot_classifier_timeout_is_counted_as_timeout_not_error() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-eot-timeout",
            thread_id="voice-eot-timeout",
        )
    )

    await session.observe_ledger(
        LedgerEvent(
            name="eot_classifier_failed",
            generation=1,
            payload={"error": "TimeoutError: semantic deadline"},
        )
    )
    await telemetry.flush()

    detail = await store.session_detail("voice-eot-timeout")

    assert detail is not None
    assert detail.summary.timeout_count == 1
    assert detail.summary.error_count == 0
    assert detail.events[0].outcome is TelemetryOutcome.TIMEOUT

    await telemetry.close()


async def test_historical_timeout_stored_as_error_is_reclassified_in_summary() -> None:
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-historical-timeout",
            thread_id="voice-historical-timeout",
        )
    )
    session.record(
        "eot_classifier_failed",
        generation=1,
        outcome=TelemetryOutcome.ERROR,
        error=TimeoutError("semantic deadline"),
    )
    await telemetry.flush()

    detail = await store.session_detail("voice-historical-timeout")

    assert detail is not None
    assert detail.events[0].outcome is TelemetryOutcome.ERROR
    assert detail.summary.timeout_count == 1
    assert detail.summary.error_count == 0

    await telemetry.close()


async def test_capability_failures_without_duration_remain_visible_in_overview() -> None:
    runtime = RuntimeTelemetry(InMemoryTelemetryStore())
    await runtime.start()
    try:
        telemetry = runtime.bind(TelemetryIdentity("t", "u", "d", "s", "th"))
        telemetry.record("tts.first_text_to_first_audio", duration_ms=100)
        telemetry.record("realtime.capability.tts", outcome=TelemetryOutcome.ERROR)
        await runtime.flush()
        overview = await runtime.diagnostics.overview(DiagnosticsWindow.last(timedelta(minutes=1)))
        assert overview.to_dict()["capability_failures"] == [{"capability": "tts", "error_count": 1, "timeout_count": 0}]
    finally:
        await runtime.close()


async def test_collection_health_reports_queue_loss_and_pending_writes() -> None:
    runtime = RuntimeTelemetry(InMemoryTelemetryStore(), max_queue_size=1)
    await runtime.start()
    try:
        telemetry = runtime.bind(TelemetryIdentity("t", "u", "d", "s", "th"))
        telemetry.record("accepted")
        telemetry.record("dropped")
        health = runtime.collection_health()
        assert health["status"] == "degraded"
        assert health["dropped_events"] == 1
        assert health["pending_events"] == 1
        await runtime.flush()
        assert runtime.collection_health()["pending_events"] == 0
        assert runtime.collection_health()["last_successful_write_at"]
    finally:
        await runtime.close()
