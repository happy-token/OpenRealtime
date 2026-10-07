"""Context permission must survive generation and be checked at delivery queues."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from server.realtime import (
    AudioDelta,
    DisplayContentDelta,
    RealtimeCapabilityFailed,
    ResponseCompleted,
    ResponseFailed,
    ResponseStarted,
    SpeechTextAlignment,
    SpokenContentDelta,
)
from server.realtime.protocol.engine import is_output_context_current
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from server.transport.frames import AssistantAudioChunkFrame
from tests.realtime.test_input_association_production import wait_for
from tests.realtime.test_reply_playback_observation import Provider, playing_core
from tests.realtime.test_response_context_frontier import next_input, position


@asynccontextmanager
async def queued_reply(*, generation_finished=True, wrappers="none"):
    release = asyncio.Event()

    class Brain:
        def __init__(self):
            self.calls = 0

        async def stream(self, turn):
            self.calls += 1
            yield "第一句。第二句。"
            if self.calls == 2 and not generation_finished:
                await release.wait()

    class Tts:
        def __init__(self):
            self.calls = 0

        async def synthesize_duplex(self, texts):
            self.calls += 1
            async for value in texts:
                async for chunk in Provider().synthesize_stream(value):
                    yield chunk

    brain = Brain()
    core, bridge = await playing_core(brain=brain, tts=Tts(), managed=True, wrappers=wrappers,
        speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    try:
        await position(bridge, 500)
        command = await next_input(core, conversation)
        await conversation.send(command)
        await wait_for(lambda: any(isinstance(entry[1], AudioDelta) for entry in conversation._events._queue))
        if generation_finished:
            await wait_for(lambda: core._response_task is None)
            await wait_for(lambda: any(isinstance(entry[1], ResponseCompleted) for entry in conversation._events._queue))
        audio = next(entry[1] for entry in conversation._events._queue if isinstance(entry[1], AudioDelta))
        yield core, bridge, audio, command, brain
    finally:
        release.set()
        await conversation.close()


@pytest.mark.parametrize("wrappers", ["none", "tools", "tools_and_agents"])
@pytest.mark.parametrize("generation_finished", [False, True])
@pytest.mark.parametrize("heard_text_changes", [False, True])
async def test_actual_managed_queue_and_bridge_revalidate_published_context_after_enqueue(wrappers, generation_finished, heard_text_changes):
    async with queued_reply(generation_finished=generation_finished, wrappers=wrappers) as (_core, bridge, audio, _, _brain):
        conversation = bridge._conversation
        assert conversation.output_delivery_allowed(audio)
        await position(bridge, 2000 if heard_text_changes else 700)
        assert conversation.output_delivery_allowed(audio) is (not heard_text_changes)
        before = sum(isinstance(frame, AssistantAudioChunkFrame) for frame in bridge._transport.frames)
        await bridge.handle_event(audio)
        after = sum(isinstance(frame, AssistantAudioChunkFrame) for frame in bridge._transport.frames)
        assert after - before == (0 if heard_text_changes else 1)


@pytest.mark.parametrize("kind", ["audio", "text", "alignment", "completion"])
@pytest.mark.parametrize("heard_text_changes", [False, True])
async def test_final_frame_rechecks_after_wait_and_does_not_count_rejected_samples(monkeypatch, kind, heard_text_changes):
    async with queued_reply() as (_core, bridge, audio, _, _brain):
        entries = [entry[1] for entry in bridge._conversation._events._queue]
        for event in entries:
            if isinstance(event, (ResponseStarted, SpokenContentDelta)):
                await bridge.handle_event(event)
        event_type = {"audio": AudioDelta, "text": DisplayContentDelta,
                      "alignment": SpeechTextAlignment, "completion": ResponseCompleted}[kind]
        source = next(event for event in entries if isinstance(event, event_type))
        if kind == "completion":
            await bridge.handle_event(audio)
        playback = bridge._playback_by_speech["response:next-response"]
        before_samples = playback.audio_samples
        before_frames = len(bridge._transport.frames)
        entered, release = asyncio.Event(), asyncio.Event()
        send = bridge._send_frame

        async def gated_send(frame, **kwargs):
            if kwargs.get("source") is source and not entered.is_set():
                entered.set()
                await release.wait()
            await send(frame, **kwargs)

        monkeypatch.setattr(bridge, "_send_frame", gated_send)
        task = asyncio.create_task(bridge.handle_event(source))
        try:
            await asyncio.wait_for(entered.wait(), .3)
            assert playback.audio_samples == before_samples
            await position(bridge, 2000 if heard_text_changes else 700)
            release.set()
            await asyncio.wait_for(task, .3)
            if heard_text_changes:
                assert len(bridge._transport.frames) == before_frames
                assert playback.audio_samples == before_samples
            else:
                assert len(bridge._transport.frames) > before_frames
                if kind == "audio":
                    assert playback.audio_samples > before_samples
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


async def test_completed_context_failure_preserves_terminal_fact_and_emits_targeted_diagnostic():
    async with queued_reply(wrappers="tools_and_agents") as (core, bridge, audio, command, brain):
        conversation = bridge._conversation
        await position(bridge, 2000)
        sequence, task_count = core._sequence, len(core._detached_response_tasks)
        for _ in range(5):
            assert not conversation.output_delivery_allowed(audio)
            assert not is_output_context_current(conversation, audio)
        assert core._sequence == sequence and len(core._detached_response_tasks) == task_count
        received = []
        async with asyncio.timeout(.5):
            async for event in conversation.events():
                received.append(event)
                if isinstance(event, RealtimeCapabilityFailed) and event.capability == "response_context":
                    assert event.context.response_id == command.response_id
                    break
        assert sum(isinstance(event, ResponseCompleted) for event in received) == 1
        assert not any(isinstance(event, (AudioDelta, DisplayContentDelta, ResponseFailed)) for event in received)
        assert brain.calls == 2
        await wait_for(lambda: not core._detached_response_tasks)


async def test_published_identity_cannot_rebind_queued_output_to_a_new_generation():
    async with queued_reply() as (_core, bridge, audio, command, brain):
        with pytest.raises(ValueError, match="cannot be reused"):
            await bridge._conversation.send(replace(command, command_id="duplicate", idempotency_key="duplicate"))
        assert brain.calls == 2
        assert bridge._conversation.output_delivery_allowed(audio)


@pytest.mark.parametrize("text_count", [16, 40])
@pytest.mark.parametrize("heard_text_changes", [False, True])
async def test_context_change_wakes_full_tts_text_queue_without_waiting_for_overall_deadline(text_count, heard_text_changes):
    from server.speech.tts import SynthesizedAudioChunk
    from tests.realtime.test_brain_heard_frontier import terminal

    release, closed = asyncio.Event(), asyncio.Event()

    class Brain:
        def __init__(self):
            self.calls = 0

        async def stream(self, turn):
            self.calls += 1
            if self.calls == 1:
                yield "第一句。第二句。"
            else:
                for _ in range(text_count):
                    yield "继续。"

    class Tts:
        def __init__(self):
            self.calls = 0

        async def synthesize_duplex(self, texts):
            self.calls += 1
            if self.calls == 1:
                async for value in texts:
                    async for chunk in Provider().synthesize_stream(value):
                        yield chunk
                return
            try:
                await release.wait()
                async for _ in texts:
                    yield SynthesizedAudioChunk(pcm16=b"\x00\x00", sample_rate_hz=1000, is_final=False)
            finally:
                closed.set()

    brain = Brain()
    core, bridge = await playing_core(brain=brain, tts=Tts(), managed=True,
        speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    core._response_timeout_s = 2
    try:
        await position(bridge, 500)
        await conversation.send(await next_input(core, conversation))
        await wait_for(lambda: bool(core._tts._text_queue._putters))
        await position(bridge, 2000 if heard_text_changes else 700)
        if heard_text_changes:
            async with asyncio.timeout(.3):
                received = await terminal(conversation)
            assert isinstance(received[-1], ResponseFailed)
            assert "heard context changed" in received[-1].error
            assert "deadline exceeded" not in received[-1].error
            assert closed.is_set() and not core._tts._text_queue._putters
            assert not core._tts_cleanup_unconfirmed
        else:
            assert core._response_task is not None and not core._response_task.done()
            release.set()
            received = await terminal(conversation)
            assert isinstance(received[-1], ResponseCompleted)
        assert brain.calls == 2
        await wait_for(lambda: not core._detached_response_tasks)
    finally:
        release.set()
        await conversation.close()


@pytest.mark.parametrize("stage", ["before_start", "start_acknowledgement"])
async def test_context_change_at_tts_start_never_leaves_unowned_provider(monkeypatch, stage):
    from server.realtime.capabilities.tts import StartTts
    from tests.realtime.test_brain_heard_frontier import terminal

    entered, release, provider_entered, provider_closed = (asyncio.Event() for _ in range(4))

    class Brain:
        async def stream(self, turn):
            yield "第一句。第二句。"

    class Tts:
        def __init__(self):
            self.calls = 0

        async def synthesize_duplex(self, texts):
            self.calls += 1
            if self.calls == 1:
                async for value in texts:
                    async for chunk in Provider().synthesize_stream(value):
                        yield chunk
                return
            try:
                provider_entered.set()
                async for value in texts:
                    async for chunk in Provider().synthesize_stream(value):
                        yield chunk
            finally:
                provider_closed.set()

    tts = Tts()
    store = InMemorySpeechDeliveryStore()
    core, bridge = await playing_core(brain=Brain(), tts=tts, managed=True, speech_deliveries=store)
    conversation = bridge._conversation
    native_send, speech_start = core._tts.send, store.start

    async def start_record(record):
        if stage == "before_start" and record.speech_id == "response:next-response":
            entered.set()
            await release.wait()
        return await speech_start(record)

    async def start_native(command):
        await native_send(command)
        if stage == "start_acknowledgement" and isinstance(command, StartTts):
            await provider_entered.wait()
            entered.set()
            await release.wait()

    monkeypatch.setattr(store, "start", start_record)
    monkeypatch.setattr(core._tts, "send", start_native)
    try:
        await position(bridge, 500)
        await conversation.send(await next_input(core, conversation))
        await asyncio.wait_for(entered.wait(), .3)
        await position(bridge, 2000)
        release.set()
        async with asyncio.timeout(.3):
            received = await terminal(conversation)
        assert isinstance(received[-1], ResponseFailed)
        assert "heard context changed" in received[-1].error
        assert tts.calls == (1 if stage == "before_start" else 2)
        assert provider_closed.is_set() is (stage == "start_acknowledgement")
        assert core._tts._speech_id is None and not core._tts_task_by_response_id
        assert not core._tts_cleanup_unconfirmed
        await wait_for(lambda: not core._detached_response_tasks)
    finally:
        release.set()
        await conversation.close()
