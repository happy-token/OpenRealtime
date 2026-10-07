"""Recovery rejection must block PCM before asynchronous failure notification."""

import asyncio
import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from server.endpoint_session.in_memory_session import InMemoryEndpointSession
from server.realtime import ResponseStarted
from server.transport.frames import AssistantAudioChunkFrame, OutputEpochStartedFrame
from tests.realtime.test_misinterruption_recovery_planning import (
    locked,
    physically_stopped,
    rewrite,
)
from tests.realtime.test_output_stop_protocol import audio_event, stopped_bridge
from tests.realtime.test_realtime_websocket_bridge import RecordingTransport


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
