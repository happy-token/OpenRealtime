"""The endpoint must release local work even when the peer won't close."""

import asyncio
from datetime import UTC, datetime

import pytest

from server.conversation_journal import InMemoryConversationJournal
from server.endpoint_session.in_memory_session import InMemoryEndpointSession
from server.realtime import AssistantYieldRequested, ReportPlaybackProgress
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.realtime.transport.output_stop import OutputStopObservation
from server.transport.frames import VoiceSessionReadyFrame
from server.voice_session.admission import LocalVoiceSessionAdmissionController
from server.voice_session.endpoint_bridge import VoiceSessionWebSocketSession
from server.voice_session.models import VoiceSessionIdentity
from server.voice_session.protocol import OutputStopResult, VoiceSessionFailureFrame
from tests.realtime.test_output_stop_protocol import audio_event
from tests.realtime.test_realtime_websocket_bridge import context, event_context
from tests.voice_session.test_endpoint_bridge import EpochTransport, WaitingConversation


class ActiveConversation(WaitingConversation):
    def __init__(self):
        super().__init__()
        self.work = [asyncio.create_task(asyncio.Event().wait(), name=f"active-{module}")
                     for module in ("brain", "tts", "classifier")]

    async def close(self):
        for task in self.work:
            task.cancel()
        await asyncio.gather(*self.work, return_exceptions=True)
        await super().close()


@pytest.mark.parametrize("noncooperative", [False, True])
@pytest.mark.parametrize("slow_notice", [False, True])
async def test_stop_failure_wakes_endpoint_and_releases_work_when_transport_close_hangs(monkeypatch, slow_notice, noncooperative):
    class SlowCloseTransport(EpochTransport):
        def __init__(self):
            super().__init__()
            self.receive_cancelled = asyncio.Event()
            self.close_started = asyncio.Event()
            self.close_cancelled = asyncio.Event()
            self.release = asyncio.Event()

        async def receive(self):
            try:
                async for frame in super().receive():
                    yield frame
            except asyncio.CancelledError:
                self.receive_cancelled.set()
                raise

        async def send(self, frame):
            if slow_notice and isinstance(frame, VoiceSessionFailureFrame):
                while not self.release.is_set():
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        if not noncooperative:
                            raise
            await super().send(frame)

        async def close(self):
            self.close_started.set()
            while not self.release.is_set():
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.close_cancelled.set()
                    if not noncooperative:
                        raise

    class ShortStopBridge(RealtimeWebSocketFrameBridge):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, output_stop_timeout_ms=10)

    class RuntimeFactory:
        conversation = None

        async def open(self, **kwargs):
            self.conversation = ActiveConversation()
            return self.conversation

    monkeypatch.setattr("server.voice_session.endpoint_bridge.RealtimeWebSocketFrameBridge", ShortStopBridge)
    raw_transport = SlowCloseTransport()
    transport = InMemoryEndpointSession("voice-1", raw_transport, raw_transport.receive(),
                                        buffer_outbound_frames=False)
    factory = RuntimeFactory()
    ctx = context()
    endpoint = VoiceSessionWebSocketSession(
        identity=VoiceSessionIdentity(tenant_id=ctx.tenant_id, user_id=ctx.user_id,
            device_id=ctx.device_id, voice_session_id=ctx.voice_session_id, thread_id=ctx.thread_id),
        context=ctx, profile="cascaded-default", runtime_factory=factory,
        journal=InMemoryConversationJournal(), transport=transport,
        admission=LocalVoiceSessionAdmissionController(),
    )
    running = asyncio.create_task(endpoint.run())
    try:
        async with asyncio.timeout(.5):
            while not any(isinstance(frame, VoiceSessionReadyFrame) for frame in raw_transport.sent):
                await asyncio.sleep(0)
        assert factory.conversation is not None
        assert all(not task.done() for task in factory.conversation.work)
        bridge = endpoint._bridge
        assert bridge is not None
        await bridge.handle_event(audio_event())
        await bridge.handle_event(AssistantYieldRequested(event_id="yield", context=event_context(),
            conversation_sequence=4, occurred_at=datetime.now(UTC), reason="barge_in_floor_claim"))
        await asyncio.wait_for(asyncio.shield(running), 1)
        assert bridge.output_stop_snapshot()[0].state == "STOP_UNKNOWN"
        assert bridge.output_stop_snapshot()[0].reason == "receipt_deadline"
        assert raw_transport.close_started.is_set() and raw_transport.close_cancelled.is_set()
        assert raw_transport.receive_cancelled.is_set()
        assert factory.conversation.closed
        assert all(task.done() for task in factory.conversation.work)
        if noncooperative:
            assert any(not task.done() for task in bridge._output_io_tasks)
            raw_transport.release.set()
            async with asyncio.timeout(.5):
                while bridge._output_io_tasks:
                    await asyncio.sleep(0)
    finally:
        raw_transport.release.set()
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        if endpoint._bridge is not None:
            await endpoint._bridge.close()


async def test_normal_endpoint_cancellation_during_stop_projection_preserves_fact_without_failure():
    incoming = asyncio.Queue()
    projecting = asyncio.Event()
    observations = []

    class ReceiptTransport(EpochTransport):
        async def receive(self):
            yield self._frame
            while True:
                yield await incoming.get()

    class ProjectingConversation(ActiveConversation):
        async def send(self, command):
            if isinstance(command, ReportPlaybackProgress):
                projecting.set()
                await asyncio.Event().wait()
            await super().send(command)

    class RuntimeFactory:
        conversation = None

        async def open(self, **kwargs):
            self.conversation = ProjectingConversation()
            return self.conversation

    raw_transport = ReceiptTransport()
    transport = InMemoryEndpointSession("voice-1", raw_transport, raw_transport.receive(),
                                        buffer_outbound_frames=False)
    factory = RuntimeFactory()
    ctx = context()
    endpoint = VoiceSessionWebSocketSession(
        identity=VoiceSessionIdentity(tenant_id=ctx.tenant_id, user_id=ctx.user_id,
            device_id=ctx.device_id, voice_session_id=ctx.voice_session_id, thread_id=ctx.thread_id),
        context=ctx, profile="cascaded-default", runtime_factory=factory,
        journal=InMemoryConversationJournal(), transport=transport,
        admission=LocalVoiceSessionAdmissionController(),
        diagnostic_observer=observations.append,
    )
    running = asyncio.create_task(endpoint.run())
    try:
        async with asyncio.timeout(.5):
            while not any(isinstance(frame, VoiceSessionReadyFrame) for frame in raw_transport.sent):
                await asyncio.sleep(0)
        bridge = endpoint._bridge
        assert bridge is not None
        await bridge.handle_event(audio_event())
        await bridge.handle_event(AssistantYieldRequested(event_id="yield", context=event_context(),
            conversation_sequence=4, occurred_at=datetime.now(UTC), reason="barge_in_floor_claim"))
        request = raw_transport.sent[-1]
        await incoming.put(OutputStopResult(output_epoch=request.output_epoch, speech_id=request.speech_id,
            generation=request.generation, stop_command_id=request.stop_command_id,
            outcome="queue_stopped", played_position_samples=1200))
        await asyncio.wait_for(projecting.wait(), .1)
        assert bridge.output_stop_snapshot()[0].state == "STOP_CONFIRMED"
        running.cancel()
        await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), .5)
        snapshot = bridge.output_stop_snapshot()[0]
        assert snapshot.state == "STOP_CONFIRMED"
        assert snapshot.reason == "session_closed"
        stop_events = [event for event in observations if isinstance(event, OutputStopObservation)]
        assert [event.phase for event in stop_events] == ["requested", "receipt", "handoff_failed"]
        assert stop_events[-1].state == "STOP_CONFIRMED"
        assert stop_events[-1].reason == "session_closed"
        assert not any(isinstance(frame, VoiceSessionFailureFrame) for frame in raw_transport.sent)
        assert factory.conversation is not None and factory.conversation.closed
        assert all(task.done() for task in factory.conversation.work)
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
