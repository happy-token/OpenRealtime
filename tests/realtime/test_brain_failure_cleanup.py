"""Terminal failures revoke real queued PCM before awaiting provider cleanup."""

import asyncio

import pytest

from server.conversation_journal import InMemoryConversationJournal
from server.realtime import (
    AudioDelta,
    CancelResponse,
    RealtimeCapabilityFailed,
    RequestResponse,
    ResponseCancelled,
    ResponseFailed,
)
from server.realtime.capabilities.brain import BrainTextDelta, CancelBrainResponse
from server.realtime.journaled import JournaledRealtimeConversation
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from server.transport.frames import AssistantAudioChunkFrame
from tests.realtime.test_cascaded_engine import EchoDuplexTts
from tests.realtime.test_input_association_production import wait_for
from tests.realtime.test_reply_playback_observation import playing_core
from tests.realtime.test_reply_revision_production_delivery import append_user, context, open_core
from tests.realtime.test_response_context_frontier import next_input, position


@pytest.mark.parametrize("failure", ["overall_deadline", "heard_frontier", "missing_token"])
async def test_actual_managed_queue_and_bridge_revoke_pcm_before_blocked_cleanup(failure):
    class Brain:
        def __init__(self):
            self.calls = 0
            self.tail = asyncio.Event()
            self.cleanup_entered = asyncio.Event()
            self.cleanup_release = asyncio.Event()

        async def stream(self, turn):
            self.calls += 1
            if self.calls == 1:
                yield "第一句。第二句。"
                return
            try:
                yield "有效响应。"
                await self.tail.wait()
                yield "过期内容。"
                # Keep provider cleanup tied to owner cancellation, rather than
                # natural generator exhaustion racing the new event-reader task.
                await asyncio.Event().wait()
            finally:
                self.cleanup_entered.set()
                await self.cleanup_release.wait()

    brain = Brain()
    core, bridge = await playing_core(brain=brain, managed=True, tts=EchoDuplexTts(),
        speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    core._response_timeout_s = .2 if failure == "overall_deadline" else 2
    core._response_cancel_timeout_s = .2
    try:
        command = await next_input(core, conversation)
        await conversation.send(command)
        await wait_for(lambda: any(isinstance(entry[1], AudioDelta)
            for entry in conversation._events._queue))
        audio = next(entry[1] for entry in conversation._events._queue if isinstance(entry[1], AudioDelta))
        assert conversation.output_delivery_allowed(audio)
        if failure == "heard_frontier":
            await position(bridge, 2000)
            brain.tail.set()
        elif failure == "missing_token":
            await core._brain._events.put(BrainTextDelta(context=command.context,
                response_id=command.response_id, response_sequence=99, delta="无身份内容", request_token=None))
        await asyncio.wait_for(brain.cleanup_entered.wait(), 1)
        assert not brain.cleanup_release.is_set()
        assert not conversation.output_delivery_allowed(audio)
        before = sum(isinstance(frame, AssistantAudioChunkFrame) for frame in bridge._transport.frames)
        await bridge.handle_event(audio)
        assert sum(isinstance(frame, AssistantAudioChunkFrame) for frame in bridge._transport.frames) == before
        brain.cleanup_release.set()
        async with asyncio.timeout(1):
            async for event in conversation.events():
                assert not isinstance(event, AudioDelta)
                if isinstance(event, ResponseFailed):
                    expected = {"overall_deadline": "response deadline exceeded",
                        "heard_frontier": "new reply version", "missing_token": "did not echo"}[failure]
                    assert expected in event.error
                    break
        assert brain.calls == 2
    finally:
        brain.tail.set()
        brain.cleanup_release.set()
        await conversation.close()


@pytest.mark.parametrize("failure", ["first_text", "overall", "cancelled"])
async def test_cancel_transport_failure_preserves_original_terminal_and_quarantines(monkeypatch, failure):
    class Brain:
        def __init__(self):
            self.entered = asyncio.Event()

        async def stream(self, turn):
            self.entered.set()
            await asyncio.Event().wait()
            yield "unused"

    brain = Brain()
    core = await open_core(brain=brain)
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(),
        engine_conversation=core)
    core._response_first_text_timeout_s = .03 if failure == "first_text" else 1
    core._response_timeout_s = .03 if failure == "overall" else 2
    send = core._brain.send

    async def broken_cancel(command):
        if isinstance(command, CancelBrainResponse):
            raise RuntimeError("provider cancel failed")  # noqa: TRY004 - injected transport fault
        await send(command)

    monkeypatch.setattr(core._brain, "send", broken_cancel)
    try:
        await append_user(conversation)
        await conversation.send(RequestResponse(command_id="r", idempotency_key="r", context=context(),
            response_id="r", minimum_thread_sequence=1))
        await asyncio.wait_for(brain.entered.wait(), .5)
        if failure == "cancelled":
            await conversation.send(CancelResponse(command_id="c", idempotency_key="c", context=context(),
                response_id="r", reason="barge_in_floor_claim"))
        received = []
        async with asyncio.timeout(.5):
            async for event in conversation.events():
                received.append(event)
                if isinstance(event, (ResponseFailed, ResponseCancelled)):
                    break
        if failure == "cancelled":
            assert isinstance(received[-1], ResponseCancelled)
            assert received[-1].reason == "barge_in_floor_claim"
            assert any(isinstance(event, RealtimeCapabilityFailed) and "provider cancel failed" in event.error
                for event in received)
        else:
            assert isinstance(received[-1], ResponseFailed)
            expected = "first response text deadline exceeded" if failure == "first_text" else "response deadline exceeded"
            assert expected in received[-1].error
            assert "provider cancel failed" in received[-1].error
        assert core._brain_protocol_failed
        assert not core._brain._requests
    finally:
        await conversation.close()
