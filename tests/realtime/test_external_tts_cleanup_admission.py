"""External speech must propagate native cleanup faults before model admission."""

import asyncio

import pytest

from server.conversation_journal import InMemoryConversationJournal
from server.realtime import (
    AppendSpeechText,
    CancelResponse,
    CancelSpeech,
    CommitSpeech,
    DeliverItem,
    DeliveryMode,
    RealtimeCapabilityFailed,
    RequestResponse,
    ResponseCancelled,
    ResponseFailed,
    StartSpeech,
)
from server.realtime.journaled import JournaledRealtimeConversation
from server.speech.tts import SynthesizedAudioChunk
from tests.realtime.test_brain_heard_frontier import terminal
from tests.realtime.test_input_association_production import wait_for
from tests.realtime.test_reply_revision_production_delivery import append_user, context, open_core


@pytest.mark.parametrize("fault", ["owned_close_error", "cancel_timeout"])
async def test_external_cleanup_fault_blocks_all_new_voice_admission(fault):
    release, synthesis_entered = asyncio.Event(), asyncio.Event()

    class FaultyIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            raise RuntimeError("external socket close failed")

    class Tts:
        def synthesize_stream(self, text):
            return FaultyIterator() if fault == "owned_close_error" else self.stalled()

        async def stalled(self):
            try:
                synthesis_entered.set()
                yield SynthesizedAudioChunk(pcm16=b"\x00\x00", sample_rate_hz=1000, is_final=False)
                await asyncio.Event().wait()
            finally:
                await release.wait()

    class Brain:
        def __init__(self):
            self.calls = 0

        async def stream(self, turn):
            self.calls += 1
            yield "不得请求模型"

    brain = Brain()
    core = await open_core(brain=brain, tts=Tts())
    core._tts._cancel_timeout_s = .01
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(), engine_conversation=core)
    events = conversation.events()
    try:
        await append_user(conversation)
        await conversation.send(StartSpeech(command_id="start", idempotency_key="start", context=context(), speech_id="external"))
        await conversation.send(AppendSpeechText(command_id="text", idempotency_key="text", context=context(),
            speech_id="external", text_sequence=1, delta="外部播报。"))
        await conversation.send(CommitSpeech(command_id="commit", idempotency_key="commit", context=context(), speech_id="external"))
        if fault == "cancel_timeout":
            await asyncio.wait_for(synthesis_entered.wait(), .2)
            await conversation.send(CancelSpeech(command_id="cancel", idempotency_key="cancel", context=context(),
                speech_id="external", reason="user_cancel"))
        async with asyncio.timeout(.5):
            while not isinstance(await anext(events), RealtimeCapabilityFailed):
                pass
        assert core._tts_cleanup_unconfirmed
        await wait_for(lambda: core._external_speech_id is None)
        await conversation.send(RequestResponse(command_id="new", idempotency_key="new", context=context(), response_id="new", minimum_thread_sequence=1))
        response = await terminal(conversation)
        assert isinstance(response[-1], ResponseFailed)
        assert "requires a new capability session" in response[-1].error
        assert brain.calls == 0
        with pytest.raises(RuntimeError, match="requires a new capability session"):
            await core.send(StartSpeech(command_id="next", idempotency_key="next", context=context(), speech_id="next"))
        for mode in (DeliveryMode.SPEECH, DeliveryMode.MODEL_RESPONSE):
            with pytest.raises(RuntimeError, match="requires a new capability session"):
                await core.send(DeliverItem(command_id=mode.value, idempotency_key=mode.value, context=context(),
                    item_id="user", delivery_id=mode.value, mode=mode))
    finally:
        release.set()
        await asyncio.gather(conversation.close(), return_exceptions=True)


async def test_direct_delivery_cancel_drains_full_native_queue_without_output_pump(monkeypatch):
    closed = asyncio.Event()

    class Tts:
        async def synthesize_stream(self, text):
            try:
                for _ in range(128):
                    yield SynthesizedAudioChunk(pcm16=b"\x00\x00", sample_rate_hz=1000, is_final=False)
            finally:
                closed.set()

    core = await open_core(tts=Tts())
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(), engine_conversation=core)

    async def blocked_pump(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(core, "_pump_tts", blocked_pump)
    try:
        await append_user(conversation)
        await conversation.send(DeliverItem(command_id="delivery", idempotency_key="delivery", context=context(),
            item_id="user", delivery_id="direct", mode=DeliveryMode.SPEECH))
        await wait_for(lambda: core._tts._events.full())
        async with asyncio.timeout(.3):
            await conversation.send(CancelResponse(command_id="cancel", idempotency_key="cancel", context=context(),
                response_id="delivery:direct", reason="user_cancel"))
        received = []
        async with asyncio.timeout(.3):
            async for event in conversation.events():
                received.append(event)
                if isinstance(event, ResponseCancelled):
                    break
        assert received[-1].reason == "user_cancel"
        assert closed.is_set()
        assert not core._tts_cleanup_unconfirmed and not core._tts_task_by_response_id
        assert not core._detached_response_tasks and not core._tts_stop_tasks
    finally:
        await conversation.close()
