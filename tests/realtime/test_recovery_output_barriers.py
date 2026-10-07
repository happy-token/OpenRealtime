"""Recovery rejection must block PCM before asynchronous failure notification."""

import asyncio
import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from server.endpoint_session.in_memory_session import InMemoryEndpointSession
from server.realtime import AssistantYieldRequested, ResponseStarted
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.transport.frames import AssistantAudioChunkFrame, OutputEpochStartedFrame
from tests.realtime.test_misinterruption_recovery_planning import (
    locked,
    physically_stopped,
    rewrite,
)
from tests.realtime.test_output_stop_protocol import audio_event, stopped_bridge
from tests.realtime.test_realtime_websocket_bridge import (
    RecordingConversation,
    RecordingTransport,
    context,
    event_context,
)


@pytest.mark.parametrize("failure", ["unsupported", "cas_failed", "expired", "foreign_target"])
async def test_recovery_rejection_synchronously_blocks_immediately_following_pcm(failure):
    bridge, _, transport, receipt = await stopped_bridge()
    try:
        await bridge.handle_inbound(receipt)
        revisions, owner, overlap = locked()
        rewrite(revisions, overlap)
        physically_stopped(revisions, owner)
        plan = revisions.plan_misinterruption_recovery(now_ns=100)
        plan = replace(plan, stop_command_id=receipt.stop_command_id,
            predecessor_response_id="response-1", source_context=replace(owner, response_id="response-1"),
            deadline_ns=time.monotonic_ns() + 1_000_000_000)
        if failure == "unsupported":
            transport.output_epoch = "epoch"
        elif failure == "cas_failed":
            transport.rotate_output_epoch = lambda **kwargs: False
        elif failure == "expired":
            plan = replace(plan, deadline_ns=time.monotonic_ns() - 1)
        else:
            plan = replace(plan, source_context=replace(owner, response_id="other"), predecessor_response_id="other")
        event = ResponseStarted(event_id="recovery", context=plan.response_context,
            conversation_sequence=5, occurred_at=datetime.now(UTC), response_id=plan.response_context.response_id,
            response_sequence=1, supersedes_response_id=plan.predecessor_response_id, recovery=plan)
        before = len(transport.frames)
        await bridge.handle_event(event)
        # No event-loop yield between rejection and queued PCM: notification
        # tasks cannot provide the synchronous delivery barrier themselves.
        await bridge.handle_event(audio_event(plan.response_context.response_id, 3))
        assert not any(isinstance(frame, AssistantAudioChunkFrame) for frame in transport.frames[before:])
        assert bridge._stop_output_failed
        assert bridge.output_epoch == "epoch"
    finally:
        await bridge.close()


async def test_recovery_control_waiting_for_send_lock_never_crosses_attachment():
    bridge, _, transport, receipt = await stopped_bridge()
    endpoint = InMemoryEndpointSession("race", transport, transport.receive(), buffer_outbound_frames=False)
    endpoint._output_epoch = "epoch"
    bridge._transport = endpoint
    replacement = RecordingTransport()
    sending = attaching = None
    try:
        await bridge.handle_inbound(receipt)
        revisions, owner, overlap = locked()
        rewrite(revisions, overlap)
        physically_stopped(revisions, owner)
        plan = replace(revisions.plan_misinterruption_recovery(now_ns=100),
            stop_command_id=receipt.stop_command_id, predecessor_response_id="response-1",
            source_context=replace(owner, response_id="response-1"), deadline_ns=time.monotonic_ns() + 1_000_000_000)
        event = ResponseStarted(event_id="recovery", context=plan.response_context,
            conversation_sequence=5, occurred_at=datetime.now(UTC), response_id=plan.response_context.response_id,
            response_sequence=1, supersedes_response_id=plan.predecessor_response_id, recovery=plan)
        await endpoint._send_lock.acquire()
        sending = asyncio.create_task(bridge.handle_event(event))
        await asyncio.sleep(0)
        assert endpoint.output_epoch == plan.output_epoch
        await endpoint.detach()
        attaching = asyncio.create_task(endpoint.attach(replacement))
        await asyncio.sleep(0)
        assert endpoint.output_epoch != plan.output_epoch
        endpoint._send_lock.release()
        await asyncio.gather(sending, attaching)
        await bridge.handle_event(audio_event(plan.response_context.response_id, 3))
        assert not any(frame.type in {"output_epoch_started", "assistant_audio_chunk"} for frame in replacement.frames)
        assert bridge._stop_output_failed
    finally:
        if endpoint._send_lock.locked():
            endpoint._send_lock.release()
        for task in (sending, attaching):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (sending, attaching) if task is not None), return_exceptions=True)
        await bridge.close()
        await endpoint.close()


@pytest.mark.parametrize("transition", ["none", "detach", "reattach", "closed"])
async def test_endpoint_epoch_notification_is_never_buffered_for_another_attachment(transition):
    transport, replacement = RecordingTransport(), RecordingTransport()
    endpoint = InMemoryEndpointSession("epoch-notify", transport, transport.receive())
    try:
        original = endpoint.output_epoch
        assert not endpoint.rotate_output_epoch(previous="wrong", replacement="fresh")
        assert endpoint.rotate_output_epoch(previous=original, replacement="fresh")
        frame = OutputEpochStartedFrame(previous_output_epoch=original, output_epoch="fresh", recovery_id="plan", generation=3)
        if transition == "detach":
            await endpoint.detach()
        elif transition == "reattach":
            await endpoint.attach(replacement)
        elif transition == "closed":
            await endpoint.close()
        assert await endpoint.send_output_epoch_started(frame) is (transition == "none")
        assert not endpoint._buffer and not replacement.frames
        assert transport.frames == ([frame] if transition == "none" else [])
        if transition != "none":
            assert not endpoint.rotate_output_epoch(previous="fresh", replacement="next")
    finally:
        await endpoint.close()


@pytest.mark.parametrize("interruption", ["normal_close", "deadline", "send_error"])
async def test_recovery_notification_has_bounded_wait_and_normal_close_is_not_failure(interruption):
    bridge, _, transport, receipt = await stopped_bridge()
    sending = None
    entered = asyncio.Event()
    original_send = transport.send

    async def blocked_send(frame):
        if frame.type == "output_epoch_started":
            entered.set()
            if interruption == "send_error":
                raise RuntimeError("socket send failed")
            await asyncio.Event().wait()
        await original_send(frame)

    try:
        await bridge.handle_inbound(receipt)
        revisions, owner, overlap = locked()
        rewrite(revisions, overlap)
        physically_stopped(revisions, owner)
        plan = replace(revisions.plan_misinterruption_recovery(now_ns=100),
            stop_command_id=receipt.stop_command_id, predecessor_response_id="response-1",
            source_context=replace(owner, response_id="response-1"), deadline_ns=time.monotonic_ns() + 50_000_000)
        event = ResponseStarted(event_id="recovery", context=plan.response_context,
            conversation_sequence=5, occurred_at=datetime.now(UTC), response_id=plan.response_context.response_id,
            response_sequence=1, supersedes_response_id=plan.predecessor_response_id, recovery=plan)
        transport.send = blocked_send
        sending = asyncio.create_task(bridge.handle_event(event))
        await asyncio.wait_for(entered.wait(), .1)
        if interruption == "normal_close":
            bridge.begin_close()
            sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
            await asyncio.sleep(0)
            assert not bridge._failure_notification_started
            assert not any(frame.type == "voice_session_failed" for frame in transport.frames)
        elif interruption == "deadline":
            done, _ = await asyncio.wait([sending], timeout=.2)
            assert done, "notification must not stall the entire event pump past its recovery deadline"
            await sending
            assert bridge._stop_output_failed
        else:
            with pytest.raises(RuntimeError, match="socket send failed"):
                await sending
            assert bridge._stop_output_failed
    finally:
        if sending is not None and not sending.done():
            sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
        await bridge.close()


@pytest.mark.parametrize("late_failure", [False, True])
@pytest.mark.parametrize("endpoint_session", [False, True])
async def test_noncooperative_epoch_send_has_bounded_caller_and_retained_cleanup_owner(endpoint_session, late_failure, caplog):
    bridge, _, transport, receipt = await stopped_bridge()
    sending = closing = None
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_send = transport.send

    async def noncooperative_send(frame):
        if frame.type == "output_epoch_started":
            entered.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
            if late_failure:
                raise RuntimeError("late epoch send failure")
        await original_send(frame)

    try:
        await bridge.handle_inbound(receipt)
        if endpoint_session:
            endpoint = InMemoryEndpointSession("noncoop", transport, transport.receive(), buffer_outbound_frames=False)
            endpoint._output_epoch = "epoch"
            bridge._transport = endpoint
        revisions, owner, overlap = locked()
        rewrite(revisions, overlap)
        physically_stopped(revisions, owner)
        plan = replace(revisions.plan_misinterruption_recovery(now_ns=100),
            stop_command_id=receipt.stop_command_id, predecessor_response_id="response-1",
            source_context=replace(owner, response_id="response-1"), deadline_ns=time.monotonic_ns() + 50_000_000)
        event = ResponseStarted(event_id="recovery", context=plan.response_context,
            conversation_sequence=5, occurred_at=datetime.now(UTC), response_id=plan.response_context.response_id,
            response_sequence=1, supersedes_response_id=plan.predecessor_response_id, recovery=plan)
        transport.send = noncooperative_send
        sending = asyncio.create_task(bridge.handle_event(event))
        await asyncio.wait_for(entered.wait(), .1)
        done, _ = await asyncio.wait([sending], timeout=.2)
        assert done, "swallowed cancellation cannot extend the recovery caller's deadline"
        await sending
        assert cancelled.is_set() and bridge._stop_output_failed
        assert any(not task.done() for task in bridge._output_io_tasks)
        before = len(transport.frames)
        await bridge.handle_event(audio_event(plan.response_context.response_id, 3))
        assert not any(isinstance(frame, AssistantAudioChunkFrame) for frame in transport.frames[before:])
        closing = asyncio.create_task(bridge.close())
        done, _ = await asyncio.wait([closing], timeout=.7)
        assert done, "normal cleanup cannot wait forever for a noncooperative send"
        await closing
        assert any(not task.done() for task in bridge._output_io_tasks), "close must retain residual ownership"
        release.set()
        async with asyncio.timeout(.5):
            while bridge._output_io_tasks:
                await asyncio.sleep(0)
        if late_failure:
            assert "late epoch send failure" in caplog.text
    finally:
        release.set()
        for task in (sending, closing):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (sending, closing) if task is not None), return_exceptions=True)
        await bridge.close()


@pytest.mark.parametrize("normal_close", [False, True])
@pytest.mark.parametrize("precise", [False, True])
@pytest.mark.parametrize("endpoint_session", [False, True])
async def test_noncooperative_stop_command_does_not_block_failure_exit(precise, endpoint_session, normal_close):
    transport = RecordingTransport()
    entered, release = asyncio.Event(), asyncio.Event()
    original_send = transport.send

    async def blocked_stop(frame):
        if frame.type == "assistant_speech_cancelled":
            entered.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    pass
        await original_send(frame)

    transport.send = blocked_stop
    endpoint = InMemoryEndpointSession("noncoop-stop", transport, transport.receive(), buffer_outbound_frames=False) if endpoint_session else transport
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=RecordingConversation(),
        transport=endpoint, precise_output_stop=precise, output_stop_timeout_ms=20)
    stopping = None
    try:
        await bridge.handle_event(audio_event())
        stopping = asyncio.create_task(bridge.handle_event(AssistantYieldRequested(event_id="yield",
            context=event_context(), conversation_sequence=4, occurred_at=datetime.now(UTC), reason="barge_in_floor_claim")))
        await asyncio.wait_for(entered.wait(), .1)
        if normal_close:
            bridge.begin_close()
            await bridge.close()
        done, _ = await asyncio.wait([stopping], timeout=.6)
        assert done, "legacy and precise stop commands must both bound noncooperative adapter waiting"
        await stopping
        if normal_close:
            assert not bridge._failure_notification_started
            if precise:
                assert bridge.output_stop_snapshot()[0].reason == "session_closed"
            assert any(not task.done() for task in bridge._output_io_tasks)
            release.set()
            async with asyncio.timeout(.5):
                while bridge._output_io_tasks:
                    await asyncio.sleep(0)
            return
        await asyncio.wait_for(bridge._output_failure.wait(), .8)
        assert bridge._stop_output_failed and bridge._output_failure.is_set()
        assert any(not task.done() for task in bridge._output_io_tasks)
        if precise:
            assert bridge.output_stop_snapshot()[0].state == "STOP_UNKNOWN"
        await bridge.close()
        assert any(not task.done() for task in bridge._output_io_tasks)
        release.set()
        async with asyncio.timeout(.5):
            while bridge._output_io_tasks:
                await asyncio.sleep(0)
    finally:
        release.set()
        if stopping is not None and not stopping.done():
            stopping.cancel()
        if stopping is not None:
            await asyncio.gather(stopping, return_exceptions=True)
        await bridge.close()
