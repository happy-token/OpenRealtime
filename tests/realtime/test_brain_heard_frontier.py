"""Generation-time retries share deadlines and publish only a valid attempt.

Real Managed/Core/Bridge paths with deterministic model and playback positions.
"""

import asyncio

import pytest

from server.realtime import (
    AgentDelegationRequestProposed,
    DisplayContentDelta,
    ResponseCompleted,
    ResponseFailed,
    ResponseStarted,
    ToolRequested,
)
from server.realtime.capabilities.brain_streaming import BrainDelegationCall, BrainToolCall
from server.realtime.capabilities.tts import AppendTtsText, StartTts
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from server.speech.plugins.doubao_tts_direct import _alignment_chunks
from server.speech.tts import SynthesizedAudioChunk
from server.tools.canonical import LatencyClass
from server.voice_session.context import FullConversationContextProjector
from tests.realtime.test_input_association_production import wait_for
from tests.realtime.test_reply_playback_observation import playing_core
from tests.realtime.test_response_context_frontier import next_input, position


class ControlledBrain:
    def __init__(self, *, kind="text", hold_after_first=False, uncooperative_cleanup=False,
                 initial_text="第一句。第二句。"):
        self.turns = []
        self.entered = [asyncio.Event() for _ in range(6)]
        self.release = [asyncio.Event() for _ in range(6)]
        self.cleanup = asyncio.Event()
        self.kind = kind
        self.hold_after_first = hold_after_first
        self.uncooperative_cleanup = uncooperative_cleanup
        self.initial_text = initial_text

    async def stream(self, turn):
        self.turns.append(turn)
        index = len(self.turns)
        if index == 1:
            yield self.initial_text
            return
        self.entered[index].set()
        await self.release[index].wait()
        try:
            if self.kind == "tool":
                yield BrainToolCall(call_id=f"call-{index}", tool_name="test", tool_version="1",
                                    arguments={}, latency=LatencyClass.FAST)
            elif self.kind == "delegation":
                yield BrainDelegationCall(delegation_request_id=f"work-{index}", instruction="inspect")
            yield f"有效候选{index}。"
            if self.hold_after_first:
                await self.cleanup.wait()
                yield "后续内容。"
        finally:
            if self.uncooperative_cleanup:
                while not self.cleanup.is_set():
                    try:
                        await self.cleanup.wait()
                    except asyncio.CancelledError:
                        continue

    def finish(self):
        self.cleanup.set()
        for event in self.release:
            event.set()


async def terminal(conversation):
    events = []
    async with asyncio.timeout(1):
        async for event in conversation.events():
            events.append(event)
            if isinstance(event, (ResponseCompleted, ResponseFailed)):
                return events


@pytest.mark.parametrize("kind", ["text", "tool", "delegation"])
async def test_two_actual_playback_updates_regenerate_before_first_publication_only(monkeypatch, kind):
    brain = ControlledBrain(kind=kind)
    core, bridge = await playing_core(brain=brain, managed=True, speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    tts_commands = []
    send_tts = core._tts.send

    async def record_tts(command):
        tts_commands.append(command)
        await send_tts(command)

    monkeypatch.setattr(core._tts, "send", record_tts)
    try:
        command = await next_input(core, conversation)
        await conversation.send(command)
        await asyncio.wait_for(brain.entered[2].wait(), 1)
        for index, samples in [(2, 1000), (3, 2000)]:
            await position(bridge, samples)
            brain.release[index].set()
            await asyncio.wait_for(brain.entered[index + 1].wait(), 1)
        assert "第一句。" not in (brain.turns[1].conversation_context or "")
        assert "第一句。" in brain.turns[2].conversation_context
        assert "第二句。" not in brain.turns[2].conversation_context
        assert "第二句。" in brain.turns[3].conversation_context
        assert tts_commands == []
        brain.release[4].set()
        received = await terminal(conversation)
        assert isinstance(received[-1], ResponseCompleted)
        assert sum(isinstance(event, ResponseStarted) for event in received) == 1
        assert [event.delta for event in received if isinstance(event, DisplayContentDelta)] == ["有效候选4。"]
        assert [event.call_id for event in received if isinstance(event, ToolRequested)] == (["call-4"] if kind == "tool" else [])
        assert [event.delegation_request_id for event in received if isinstance(event, AgentDelegationRequestProposed)] == (
            ["work-4"] if kind == "delegation" else [])
        assert sum(isinstance(command, StartTts) for command in tts_commands) == 1
        assert [command.delta for command in tts_commands if isinstance(command, AppendTtsText)] == ["有效候选4。"]
        assert len(brain.turns) == 4
        await wait_for(lambda: not core._brain_attempts and not core._brain._requests)
    finally:
        brain.finish()
        await conversation.close()


@pytest.mark.parametrize("kind", ["text", "tool", "delegation"])
async def test_public_text_does_not_retry_same_reply_or_publish_stale_later_text(kind):
    brain = ControlledBrain(kind=kind, hold_after_first=True)
    core, bridge = await playing_core(brain=brain, managed=True, speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    stream = conversation.events()
    try:
        await position(bridge, 1000)
        await conversation.send(await next_input(core, conversation))
        await asyncio.wait_for(brain.entered[2].wait(), 1)
        brain.release[2].set()
        published = []
        async with asyncio.timeout(1):
            async for event in stream:
                published.append(event)
                if isinstance(event, DisplayContentDelta):
                    assert event.delta == "有效候选2。"
                    break
        await position(bridge, 2000)
        brain.cleanup.set()
        received = []
        async with asyncio.timeout(1):
            async for event in stream:
                received.append(event)
                if isinstance(event, ResponseFailed):
                    break
        assert "new reply version" in received[-1].error
        assert not any(isinstance(event, DisplayContentDelta) for event in received)
        assert sum(isinstance(event, ToolRequested) for event in published + received) == (kind == "tool")
        assert sum(isinstance(event, AgentDelegationRequestProposed) for event in published + received) == (kind == "delegation")
        assert len(brain.turns) == 2
    finally:
        brain.finish()
        await stream.aclose()
        await conversation.close()


async def test_retries_consume_original_first_text_deadline():
    brain = ControlledBrain()
    core, bridge = await playing_core(brain=brain, managed=True, speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    core._response_first_text_timeout_s = .2
    try:
        command = await next_input(core, conversation)
        began = asyncio.get_running_loop().time()
        await conversation.send(command)
        await asyncio.wait_for(brain.entered[2].wait(), 1)
        await asyncio.sleep(.14)
        await position(bridge, 1000)
        brain.release[2].set()
        await asyncio.wait_for(brain.entered[3].wait(), 1)
        received = await terminal(conversation)
        elapsed = asyncio.get_running_loop().time() - began
        assert isinstance(received[-1], ResponseFailed)
        assert "first response text deadline exceeded" in received[-1].error
        assert .18 <= elapsed < .3
        assert not any(isinstance(event, ResponseStarted) for event in received)
        assert len(brain.turns) == 3
    finally:
        brain.finish()
        await conversation.close()


async def test_unconfirmed_cancellation_ends_reply_without_starting_replacement_attempt():
    brain = ControlledBrain(uncooperative_cleanup=True)
    core, bridge = await playing_core(brain=brain, managed=True, speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    core._response_cancel_timeout_s = .025
    try:
        command = await next_input(core, conversation)
        await conversation.send(command)
        await asyncio.wait_for(brain.entered[2].wait(), 1)
        await position(bridge, 1000)
        brain.release[2].set()
        received = await terminal(conversation)
        assert isinstance(received[-1], ResponseFailed)
        assert "cannot safely retry" in received[-1].error
        assert len(brain.turns) == 2
        assert core._detached_response_tasks
        assert not any(isinstance(event, ResponseStarted) for event in received)
        brain.finish()
        await wait_for(lambda: not core._detached_response_tasks and not core._brain._requests)
    finally:
        brain.finish()
        await conversation.close()


class ThreeSentenceTts:
    async def synthesize_stream(self, text):
        yield SynthesizedAudioChunk(pcm16=b"\x00\x00" * 3000, sample_rate_hz=1000, is_final=False)
        for start, sentence in enumerate(["第一句。", "第二句。", "第三句。"]):
            for chunk in _alignment_chunks({"text": sentence,
                "words": [{"word": sentence, "startTime": start, "endTime": start + 1}]}, 1000):
                yield chunk


async def test_third_actual_heard_update_exhausts_three_attempt_budget_without_public_output():
    brain = ControlledBrain(initial_text="第一句。第二句。第三句。")
    core, bridge = await playing_core(brain=brain, managed=True, tts=ThreeSentenceTts(),
                                    speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    try:
        await conversation.send(await next_input(core, conversation))
        await asyncio.wait_for(brain.entered[2].wait(), 1)
        for index, samples in [(2, 1000), (3, 2000), (4, 3000)]:
            await position(bridge, samples)
            brain.release[index].set()
            if index != 4:
                await asyncio.wait_for(brain.entered[index + 1].wait(), 1)
        received = await terminal(conversation)
        assert isinstance(received[-1], ResponseFailed)
        assert "retry budget exhausted" in received[-1].error
        assert len(brain.turns) == 4  # original reply plus exactly three attempts
        assert not any(isinstance(event, (ResponseStarted, DisplayContentDelta)) for event in received)
        await wait_for(lambda: not core._brain_attempts and not core._brain._requests)
    finally:
        brain.finish()
        await conversation.close()


@pytest.mark.parametrize("deadline", ["first_text", "overall"])
async def test_retry_context_projection_uses_original_deadline(deadline):
    brain = ControlledBrain()
    core, bridge = await playing_core(brain=brain, managed=True, speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    core._response_first_text_timeout_s = .08 if deadline == "first_text" else .5
    core._response_timeout_s = .08 if deadline == "overall" else .5
    entered = asyncio.Event()
    try:
        command = await next_input(core, conversation)

        class Projector(FullConversationContextProjector):
            def __init__(self):
                self.calls = 0

            async def project_text(self, items):
                self.calls += 1
                if self.calls == 2:
                    entered.set()
                    await asyncio.Event().wait()
                return await super().project_text(items)

        core._context_projector = Projector()
        await conversation.send(command)
        await asyncio.wait_for(brain.entered[2].wait(), 1)
        await position(bridge, 1000)
        brain.release[2].set()
        await asyncio.wait_for(entered.wait(), 1)
        received = await terminal(conversation)
        assert isinstance(received[-1], ResponseFailed)
        assert ("first response text deadline" if deadline == "first_text" else "response deadline exceeded") in received[-1].error
        assert len(brain.turns) == 2
        assert not any(isinstance(event, ResponseStarted) for event in received)
        await wait_for(lambda: not core._brain_attempts and not core._brain._requests)
    finally:
        brain.finish()
        await conversation.close()
