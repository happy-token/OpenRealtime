from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from server.observability.session_connection import SessionConnectionObserver
from server.observability.telemetry import (
    DiagnosticsWindow,
    InMemoryTelemetryStore,
    RuntimeTelemetry,
    TelemetryIdentity,
)
from server.realtime import AssistantYieldRequested
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.realtime.transport.output_stop import OutputStopObservation
from server.voice_session.protocol import OutputStopResult
from tests.realtime.test_output_stop_protocol import audio_event
from tests.realtime.test_realtime_websocket_bridge import (
    RecordingConversation,
    RecordingTransport,
    context,
    event_context,
)


async def request_stop(observer, *, conversation=None, timeout=1500):
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=conversation or RecordingConversation(),
        transport=transport,
        output_epoch="epoch",
        precise_output_stop=True,
        output_stop_timeout_ms=timeout,
        diagnostic_observer=observer,
    )
    audio = audio_event(generation=3)
    await bridge.handle_event(
        replace(audio, context=replace(audio.context, turn_id="original-turn"))
    )
    await bridge.handle_event(
        AssistantYieldRequested(
            event_id="yield",
            conversation_sequence=4,
            occurred_at=datetime.now(UTC),
            context=replace(event_context(), generation=4, turn_id="interrupting-turn"),
            reason="barge_in_floor_claim",
        )
    )
    request = transport.frames[-1]
    receipt = OutputStopResult(
        output_epoch=request.output_epoch,
        speech_id=request.speech_id,
        generation=request.generation,
        stop_command_id=request.stop_command_id,
        outcome="queue_stopped",
        played_position_samples=1200,
    )
    return bridge, transport, receipt


async def test_stop_observations_are_queryable_with_original_identity_and_success_spans():
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store)
    await runtime.start()
    identity = TelemetryIdentity("tenant-1", "user-1", "browser", "voice-1", "thread-1")
    observer = SessionConnectionObserver(runtime.bind(identity))
    observed = []

    def observe(event):
        observed.append(event)
        observer(event)

    bridge = None
    try:
        bridge, _, receipt = await request_stop(observe)
        await bridge.handle_inbound(receipt)
        await bridge.handle_inbound(receipt)  # A replay must not add successful samples.
        await bridge.close()
        await runtime.flush()
        detail = await store.session_detail("voice-1")
        assert detail is not None
        events = [event for event in detail.events if event.name.startswith("playback.stop_")]
        assert [event.name for event in events] == [
            "playback.stop_requested",
            "playback.stop_receipt",
            "playback.stop_request_to_receipt",
            "playback.stop_handoff_ready",
            "playback.stop_receipt_to_handoff",
            "playback.stop_request_to_handoff",
        ]
        assert [event.phase for event in observed] == ["requested", "receipt", "handoff_ready"]
        for event in events:
            assert event.call_id == receipt.stop_command_id
            assert event.generation == 3 and event.turn_id == "original-turn"
            assert event.response_id == "response-1"
            assert event.attributes["output_epoch"] == "epoch"
            assert event.attributes["speech_id"] == receipt.speech_id
            assert event.attributes["stop_command_id"] == receipt.stop_command_id
        assert events[1].attributes["played_position_samples"] == 1200
        assert events[3].attributes["handoff"] == "granted"
        assert events[1].attributes["state"] == "STOP_CONFIRMED"
        assert events[1].attributes["requested_at"] and events[1].attributes["received_at"]
        assert all(event.duration_ms is None for event in events if event.kind.value == "event")
        assert sum(event.duration_ms is not None for event in events) == 3
        with pytest.raises(AttributeError):
            observed[0].reason = "changed"
        overview = await store.overview(DiagnosticsWindow(datetime.now(UTC) - timedelta(minutes=1)))
        assert (
            overview.turn_count == 0 and overview.error_count == 0 and overview.timeout_count == 0
        )
    finally:
        if bridge:
            await bridge.close()
        await runtime.close()


@pytest.mark.parametrize("outcome", ["unknown", "stale", "deadline", "normal_close"])
async def test_failed_and_cancelled_stop_waits_never_become_success_samples(outcome):
    store, observed = InMemoryTelemetryStore(), []
    runtime = RuntimeTelemetry(store)
    await runtime.start()
    observer = SessionConnectionObserver(
        runtime.bind(TelemetryIdentity("t", "u", "d", "voice-1", "thread"))
    )

    def observe(event):
        observed.append(event)
        observer(event)

    bridge = None
    try:
        bridge, _, receipt = await request_stop(
            observe, timeout=10 if outcome == "deadline" else 1500
        )
        if outcome == "normal_close":
            await bridge.close()
        elif outcome == "deadline":
            await asyncio.wait_for(bridge.wait_for_output_failure(), 1)
        else:
            await bridge.handle_inbound(
                receipt.model_copy(update={"outcome": outcome, "played_position_samples": None})
            )
        await bridge.close()
        await runtime.flush()
        detail = await store.session_detail("voice-1")
        events = [event for event in detail.events if event.name.startswith("playback.stop_")]
        failures = [event for event in events if event.name == "playback.stop_handoff_failed"]
        assert len(failures) == 1
        assert all(event.duration_ms is None for event in events)
        assert failures[0].attributes["handoff"] == "denied"
        assert failures[0].attributes["observed_wait_ms"] >= 0
        assert (
            failures[0].outcome.value
            == {
                "unknown": "error",
                "stale": "error",
                "deadline": "timeout",
                "normal_close": "cancelled",
            }[outcome]
        )
        overview = await store.overview(DiagnosticsWindow(datetime.now(UTC) - timedelta(minutes=1)))
        assert overview.turn_count == 0
        assert overview.error_count == int(outcome in {"unknown", "stale"})
        assert overview.timeout_count == int(outcome == "deadline")
        playback = next(
            module for module in overview.module_health if module["module"] == "playback"
        )
        if outcome != "normal_close":
            assert playback["timeout_count"] == int(outcome == "deadline")
            assert playback["error_count"] == int(outcome in {"unknown", "stale"})
    finally:
        if bridge:
            await bridge.close()
        await runtime.close()


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_observer_failure_cannot_change_stop_permission_or_audio_delivery(error_type):
    calls = []

    def broken(event):
        calls.append(event)
        raise error_type("telemetry unavailable")

    bridge, transport, receipt = await request_stop(broken)
    try:
        await bridge.handle_inbound(receipt)
        await bridge.handle_event(audio_event("next", 4))
        assert transport.frames[-1].speech_id == "response:next"
        assert bridge.output_stop_snapshot()[0].state == "STOP_CONFIRMED"
        assert all(isinstance(event, OutputStopObservation) for event in calls)
    finally:
        await bridge.close()


async def test_projection_deadline_preserves_queue_fact_without_successful_handoff():
    class BlockedProjection(RecordingConversation):
        async def send(self, command):
            await asyncio.Event().wait()

    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store)
    await runtime.start()
    observer = SessionConnectionObserver(
        runtime.bind(TelemetryIdentity("t", "u", "d", "voice-1", "thread"))
    )
    bridge, _, receipt = await request_stop(observer, conversation=BlockedProjection(), timeout=25)
    try:
        with pytest.raises(TimeoutError):
            await bridge.handle_inbound(receipt)
        await runtime.flush()
        detail = await store.session_detail("voice-1")
        assert detail is not None
        failures = [
            event for event in detail.events if event.name == "playback.stop_handoff_failed"
        ]
        assert len(failures) == 1
        assert failures[0].outcome.value == "timeout"
        assert failures[0].attributes["reason_code"] == "playback_projection_deadline"
        assert failures[0].attributes["state"] == "STOP_CONFIRMED"
        assert failures[0].attributes["played_position_samples"] == 1200
        assert failures[0].duration_ms is None
        assert [event.name for event in detail.events if event.duration_ms is not None] == [
            "playback.stop_request_to_receipt"
        ]
        assert bridge.output_stop_snapshot()[0].state == "STOP_CONFIRMED"
    finally:
        await bridge.close()
        await runtime.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("output_epoch", "other"),
        ("speech_id", "other"),
        ("generation", 99),
        ("stop_command_id", "other"),
    ],
)
async def test_mismatched_receipts_do_not_create_diagnostic_samples(field, value):
    observed = []
    bridge, _, receipt = await request_stop(observed.append)
    try:
        await bridge.handle_inbound(receipt.model_copy(update={field: value}))
        assert [event.phase for event in observed] == ["requested"]
        await bridge.handle_inbound(receipt)
        await bridge.handle_inbound(receipt)
        assert [event.phase for event in observed] == ["requested", "receipt", "handoff_ready"]
    finally:
        await bridge.close()


async def test_full_diagnostics_queue_reports_loss_without_blocking_stop_permission():
    class BlockedStore(InMemoryTelemetryStore):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()

        async def append_batch(self, records):
            self.entered.set()
            await self.release.wait()
            await super().append_batch(records)

    store = BlockedStore()
    runtime = RuntimeTelemetry(store, max_queue_size=1, flush_interval_s=0.001)
    await runtime.start()
    telemetry = runtime.bind(TelemetryIdentity("t", "u", "d", "voice-1", "thread"))
    observer = SessionConnectionObserver(telemetry)
    await asyncio.wait_for(store.entered.wait(), 1)
    telemetry.record("test.queue_filler")
    bridge, transport, receipt = await request_stop(observer)
    try:
        await bridge.handle_inbound(receipt)
        await bridge.handle_event(audio_event("next", 4))
        assert transport.frames[-1].speech_id == "response:next"
        health = runtime.collection_health()
        assert health["status"] == "degraded"
        assert health["dropped_events"] == 6
    finally:
        store.release.set()
        await bridge.close()
        await runtime.close()


async def test_diagnostic_request_is_an_immutable_copy_of_live_stop_identity():
    changes = []

    def mutate(event):
        changes.append(event.phase)
        event.request.stop_command_id = "changed-by-observer"

    bridge, transport, receipt = await request_stop(mutate)
    try:
        assert receipt.stop_command_id != "changed-by-observer"
        await bridge.handle_inbound(receipt)
        await bridge.handle_event(audio_event("next", 4))
        assert transport.frames[-1].speech_id == "response:next"
        assert changes == ["requested", "receipt", "handoff_ready"]
    finally:
        await bridge.close()
