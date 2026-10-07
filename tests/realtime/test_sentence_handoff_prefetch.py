"""Candidate generation overlaps physical sentence waiting without delivery."""

import asyncio
import time
from dataclasses import replace

import pytest

from server.core.turn_content import TurnContent
from server.realtime.capabilities.asr import AsrTranscriptFinal
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    ObserveAsrEvent,
    ObserveAssistantPlayback,
    ObserveAssistantYielded,
    UserTurnCommitted,
)
from tests.realtime.test_coordinated_turn_manager import start, stop, take, text
from tests.realtime.test_sentence_permit_actor import prepared


class Brain:
    def __init__(self):
        self.turns = []
        self.started = asyncio.Event()

    async def stream(self, turn):
        self.turns.append(turn)
        self.started.set()
        yield "补充后的回答。"


@pytest.mark.parametrize("final_changed", [False, True])
async def test_stopped_supplement_prepares_before_physical_stop_and_final_controls_reuse(final_changed):
    brain = Brain()
    cache = SpeculativeStreamingBrain(brain)
    session, stream, first, second, fact, event = await prepared(
        response_prefetch_enabled=True, response_prefetcher=cache, sentence_handoff_prefetch_enabled=True)
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        async with asyncio.timeout(.2):
            await brain.started.wait()
        assert event.sentence_permit is not None
        assert session.sentence_playback_permit_current(event.sentence_permit)
        assert not session.snapshot().commit_pending
        assert not [item for item in session._outbox._queue if isinstance(item, UserTurnCommitted)]
        assert brain.turns[0].text == "查天气\n补充一下，明天也要看。"
        assert brain.turns[0].generation == second.generation
        async with asyncio.timeout(.2):
            while not cache._state.done:
                await asyncio.sleep(0)
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply", fact=replace(
            fact, terminal=True, current_sentence=None, observed_at_ns=time.monotonic_ns())))
        request = await take(stream, AsrCommitRequested)
        final_text = "补充一下，后天也要看。" if final_changed else "补充一下，明天也要看！"
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=request.context,
            revision=2, text=final_text, reason="test")))
        committed = await take(stream, UserTurnCommitted)
        assert committed.continuation_of_turn_id == first.turn_id
        result = [part async for part in cache.stream(TurnContent(text=committed.text,
            generation=committed.context.generation))]
        assert result == ["补充后的回答。"]
        assert len(brain.turns) == (2 if final_changed else 1)
        assert brain.turns[-1].text == committed.text or not final_changed
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize("change", ["resume", "correction", "stop", "position_unknown"])
async def test_sentence_candidate_is_invalidated_when_authority_changes(change):
    brain = Brain()
    cache = SpeculativeStreamingBrain(brain)
    session, stream, first, second, fact, _event = await prepared(
        response_prefetch_enabled=True, response_prefetcher=cache, sentence_handoff_prefetch_enabled=True)
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        async with asyncio.timeout(.2):
            await brain.started.wait()
        if change == "resume":
            await start(session, second)
        elif change == "position_unknown":
            await session.send(ObserveAssistantPlayback(context=first, response_id="reply", fact=replace(
                fact, output_epoch=None, current_sentence=None, position_precision="unknown",
                played_position_samples=None, sample_rate_hz=None, observed_at_ns=time.monotonic_ns())))
        else:
            value = "不是，我刚才说错了。" if change == "correction" else "别说了。"
            await text(session, value, revision=2, ctx=second)
        async with asyncio.timeout(.2):
            while cache._state is not None:
                await asyncio.sleep(0)
        assert not session.snapshot().commit_pending
        assert len(brain.turns) == 1
    finally:
        await stream.aclose()
        await session.close()


async def test_late_partial_revisions_retire_one_candidate_without_per_character_requests():
    brain = Brain()
    cache = SpeculativeStreamingBrain(brain)
    session, stream, _first, second, _fact, event = await prepared(
        response_prefetch_enabled=True, response_prefetcher=cache, sentence_handoff_prefetch_enabled=True)
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        await asyncio.wait_for(brain.started.wait(), .2)
        for revision in range(2, 10):
            await text(session, "补充一下，明天也要看。还有周末" + "啊" * revision,
                revision=revision, ctx=second)
        await asyncio.sleep(.01)
        assert len(brain.turns) == 1
        assert session._input.sentence_wait == event.sentence_permit
        assert not session.snapshot().commit_pending
        assert cache._state is None
    finally:
        await stream.aclose()
        await session.close()


async def test_default_configuration_keeps_sentence_generation_after_physical_stop():
    brain = Brain()
    cache = SpeculativeStreamingBrain(brain)
    session, stream, _first, second, _fact, _event = await prepared(
        response_prefetch_enabled=True, response_prefetcher=cache)
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        await asyncio.sleep(.02)
        assert not brain.started.is_set()
        assert not session.snapshot().commit_pending
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize("kind", ["text", "speech"])
@pytest.mark.parametrize("stop_samples", [600, 1000])
async def test_managed_bridge_candidate_waits_for_stop_and_rebuilds_actual_heard_context(kind, stop_samples):
    from server.realtime import AssistantYieldRequested as CanonicalYield
    from server.realtime.capabilities.coordinated_turn_manager import (
        CoordinatedTurnManagerCapabilityAdapter,
    )
    from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
    from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
    from server.turn_policy.policy import TurnPolicy
    from server.voice_session.protocol import OutputStopResult, PlaybackProgressV2
    from tests.realtime.test_coordinated_turn_manager import Interrupt
    from tests.realtime.test_input_association_production import wait_for
    from tests.realtime.test_realtime_websocket_bridge import context
    from tests.realtime.test_reply_playback_observation import Provider, playing_core
    from tests.realtime.test_sentence_permit_actor import ControlledAsr

    class RealBrain:
        def __init__(self):
            self.turns = []

        async def stream(self, turn):
            self.turns.append(turn)
            yield "第一句。第二句。"

    class Duplex:
        async def synthesize_duplex(self, texts):
            async for value in texts:
                async for packet in Provider().synthesize_stream(value):
                    yield packet

    provider, asr, tts = RealBrain(), ControlledAsr(), Duplex()
    asr.latest = "补充一下，明天也要看。"
    cache = (SpeculativeStreamingBrain(provider) if kind == "text" else
        SpeculativeSpeechPipeline(brain=provider, tts=tts))
    manager = CoordinatedTurnManagerCapabilityAdapter(TurnPolicy,
        semantic_interruption_classifier=Interrupt(), response_prefetch_enabled=True,
        sentence_handoff_prefetch_enabled=True, response_prefetcher=cache,
        asr_idle_stop_ms=15, semantic_interruption_idle_ms=5, recovery_timeout_ms=1000)
    core, bridge = await playing_core(precise_stop=True, brain=cache,
        tts=cache if kind == "speech" else tts, asr=asr, turn_manager=manager,
        managed=True, speech_deliveries=InMemorySpeechDeliveryStore())
    actor = core._input_pipeline._turn_manager
    second = replace(context(), turn_id="supplement", generation=2)
    pump = None
    try:
        await bridge.handle_inbound(PlaybackProgressV2(output_epoch="epoch", speech_id="response:reply",
            generation=1, phase="playing", played_position_samples=500))
        await start(actor, second)
        await text(actor, asr.latest, ctx=second)
        async with asyncio.timeout(1):
            async for event in bridge._conversation.events():
                await bridge.handle_event(event)
                if isinstance(event, CanonicalYield):
                    break
        async def drain():
            async for event in bridge._conversation.events():
                await bridge.handle_event(event)
        pump = asyncio.create_task(drain())
        request = next(iter(bridge._output_stops.values())).request
        await stop(actor, second)
        await wait_for(lambda: len(provider.turns) == 2)
        await wait_for(lambda: cache._state.done)
        candidate = provider.turns[1]
        assert candidate.text == "说两句\n" + asr.latest
        assert "第一句。" not in (candidate.conversation_context or "")
        assert "user: 说两句" not in (candidate.conversation_context or "")
        assert asr.commits == []
        assert not any(frame.type in {"assistant_text", "assistant_speech_text", "assistant_audio_chunk"}
            and frame.generation == 2 for frame in bridge._transport.frames)
        await bridge.handle_inbound(OutputStopResult(output_epoch="epoch", speech_id="response:reply",
            generation=1, stop_command_id=request.stop_command_id, outcome="queue_stopped",
            played_position_samples=stop_samples))
        await wait_for(lambda: any(frame.type == "assistant_speech_text" and frame.generation == 2
            for frame in bridge._transport.frames))
        assert len(asr.commits) == 1
        assert len(provider.turns) == (3 if stop_samples == 1000 else 2)
        current = provider.turns[-1]
        assert current.text == candidate.text
        if stop_samples == 1000:
            assert len(provider.turns) == 3
            assert "第一句。" in (current.conversation_context or "")
            assert "第二句。" not in (current.conversation_context or "")
        formal = await core._turn_from_projection(core._last_projected_thread_sequence,
            generation=second.generation)
        assert formal.conversation_context == current.conversation_context
        assert formal.context_projection_digest == current.context_projection_digest
    finally:
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        await bridge.close()
        await bridge._conversation.close()


@pytest.mark.parametrize("change", ["resume", "correction", "unknown", "close"])
async def test_projection_wait_cannot_start_supplier_after_sentence_authority_is_revoked(change):
    brain = Brain()
    cache = SpeculativeStreamingBrain(brain)
    session, stream, first, second, fact, _event = await prepared(
        response_prefetch_enabled=True, response_prefetcher=cache, sentence_handoff_prefetch_enabled=True)
    entered, release = asyncio.Event(), asyncio.Event()

    async def build(candidate):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            # A context projector that returns after cancellation still cannot
            # restore permission or initiate a provider request.
            await release.wait()
        return TurnContent(text=candidate.text, generation=candidate.generation)

    session.set_prefetch_turn_builder(build)
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        await asyncio.wait_for(entered.wait(), .2)
        if change == "resume":
            await start(session, second)
        elif change == "correction":
            await text(session, "不是，我刚才说错了。", revision=2, ctx=second)
        elif change == "unknown":
            await session.send(ObserveAssistantPlayback(context=first, response_id="reply", fact=replace(
                fact, output_epoch=None, current_sentence=None, position_precision="unknown",
                played_position_samples=None, sample_rate_hz=None, observed_at_ns=time.monotonic_ns())))
        else:
            closing = asyncio.create_task(session.close())
            await asyncio.sleep(0)
        release.set()
        if change == "close":
            await closing
        await asyncio.sleep(.01)
        assert brain.turns == []
    finally:
        release.set()
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize("relation", ["new_topic", "unresolved", "correction"])
async def test_same_final_text_does_not_reuse_candidate_when_final_relation_changes(relation):
    from server.turn_policy.input_association import (
        ConservativeInputAssociationPolicy,
        InputAssociation,
        InputRelation,
    )

    class Policy:
        final = False

        def associate(self, request):
            if self.final:
                label = InputRelation(relation)
                return InputAssociation(label, None if label is InputRelation.NEW_TOPIC
                    else request.previous_turn_id, "test_final")
            return ConservativeInputAssociationPolicy().associate(request)

    policy, brain = Policy(), Brain()
    cache = SpeculativeStreamingBrain(brain)
    session, stream, first, second, fact, _event = await prepared(
        response_prefetch_enabled=True, response_prefetcher=cache, sentence_handoff_prefetch_enabled=True,
        input_association_policy=policy)
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        await asyncio.wait_for(brain.started.wait(), .2)
        async with asyncio.timeout(.2):
            while not cache._state.done:
                await asyncio.sleep(0)
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply", fact=replace(
            fact, terminal=True, current_sentence=None, observed_at_ns=time.monotonic_ns())))
        request = await take(stream, AsrCommitRequested)
        policy.final = True
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=request.context, revision=2,
            text="补充一下，明天也要看。", reason="test")))
        committed = await take(stream, UserTurnCommitted)
        assert committed.input_relation == relation
        await asyncio.sleep(.01)
        assert cache._state is None
    finally:
        await stream.aclose()
        await session.close()


async def test_unknown_terminal_releases_input_but_cannot_retain_sentence_candidate():
    brain = Brain()
    cache = SpeculativeStreamingBrain(brain)
    session, stream, first, second, fact, _event = await prepared(
        response_prefetch_enabled=True, response_prefetcher=cache, sentence_handoff_prefetch_enabled=True)
    try:
        await session.send(ObserveAssistantYielded(context=replace(second, response_id="reply")))
        await stop(session, second)
        await asyncio.wait_for(brain.started.wait(), .2)
        async with asyncio.timeout(.2):
            while not cache._state.done:
                await asyncio.sleep(0)
        await session.send(ObserveAssistantPlayback(context=first, response_id="reply", fact=replace(
            fact, terminal=True, current_sentence=None, position_precision="unknown",
            played_position_samples=None, sample_rate_hz=None, observed_at_ns=time.monotonic_ns())))
        await take(stream, AsrCommitRequested)
        async with asyncio.timeout(.2):
            while cache._state is not None:
                await asyncio.sleep(0)
        assert session._prefetch._candidate is None
        assert session.snapshot().commit_pending
    finally:
        await stream.aclose()
        await session.close()
