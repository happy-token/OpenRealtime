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
            fact, terminal=True, current_sentence=None, played_audio_end_us=1_000_000,
            played_position_samples=1000, confirmed_text_end=4, observed_at_ns=time.monotonic_ns())))
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
@pytest.mark.parametrize("generation_active", [False, True])
@pytest.mark.parametrize("projection", ["full", "budgeted", "source_changes"])
async def test_managed_bridge_candidate_waits_for_stop_and_rebuilds_actual_heard_context(kind, stop_samples, generation_active, projection):
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
            self.release = asyncio.Event()
            self.old_closed = asyncio.Event()

        async def stream(self, turn):
            self.turns.append(turn)
            first = len(self.turns) == 1
            try:
                yield "第一句。第二句。"
                if first and generation_active:
                    await self.release.wait()
            finally:
                if first:
                    self.old_closed.set()

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
        managed=True, speech_deliveries=InMemorySpeechDeliveryStore(), return_after_alignment=generation_active)
    if projection == "budgeted":
        from tests.voice_session.test_context import heard_projector
        core._context_projector, _store = heard_projector()
    if projection == "source_changes":
        from server.conversation_journal import ConversationItemKind
        from server.voice_session.context import FullConversationContextProjector
        class SourceChangingProjector(FullConversationContextProjector):
            reads = 0
            async def project_hypothetical_text(self, items):
                self.reads += 1
                if self.reads == 1:
                    source = next(item for item in core._projected_items.values()
                        if item.kind is ConversationItemKind.ASSISTANT_OUTPUT and item.context.response_id == "reply")
                    core._projected_items[source.sequence] = replace(source,
                        provider_metadata={**source.provider_metadata, "late_source_fact": "verified"})
                    await asyncio.sleep(0)
                return await super().project_hypothetical_text(items)
        core._context_projector = SourceChangingProjector()
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
        assert provider.old_closed.is_set()
        assert candidate.text == "说两句\n" + asr.latest
        assert "第一句。" not in (candidate.conversation_context or "")
        assert "user: 说两句" not in (candidate.conversation_context or "")
        if projection == "source_changes":
            assert core._context_projector.reads == 2
        assert candidate.conditional_handoff is not None
        assert candidate.conditional_handoff.permit.permit_id == request.sentence_permit.permit_id
        assert "第一句。" in candidate.conditional_handoff.expected_context
        assert "第二句。" not in candidate.conditional_handoff.expected_context
        assert "条件计划" in candidate.model_text
        actual = await core._speech_deliveries.get("response:reply")
        assert actual.delivered_speech_transcript == ""
        assert not any(item.content for item in core._projected_items.values()
            if item.context.response_id == "reply")
        assert asr.commits == []
        assert not any(frame.type in {"assistant_text", "assistant_speech_text", "assistant_audio_chunk"}
            and frame.generation == 2 for frame in bridge._transport.frames)
        await bridge.handle_inbound(OutputStopResult(output_epoch="epoch", speech_id="response:reply",
            generation=1, stop_command_id=request.stop_command_id, outcome="queue_stopped",
            played_position_samples=stop_samples))
        await wait_for(lambda: any(frame.type == "assistant_speech_text" and frame.generation == 2
            for frame in bridge._transport.frames))
        assert len(asr.commits) == 1
        assert len(provider.turns) == (2 if stop_samples == 1000 else 3)
        current = provider.turns[-1]
        current_context = (current.conditional_handoff.expected_context if current.conditional_handoff is not None
            else current.conversation_context)
        current_digest = (current.conditional_handoff.expected_projection_digest if current.conditional_handoff is not None
            else current.context_projection_digest)
        assert current.text == candidate.text
        if stop_samples == 1000:
            assert len(provider.turns) == 2
            assert "第一句。" in (current_context or "")
            assert "第二句。" not in (current_context or "")
        formal = await core._turn_from_projection(core._last_projected_thread_sequence,
            generation=second.generation)
        assert formal.conversation_context == current_context
        assert formal.context_projection_digest == current_digest
    finally:
        provider.release.set()
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
            fact, terminal=True, current_sentence=None, played_audio_end_us=1_000_000,
            played_position_samples=1000, confirmed_text_end=4, observed_at_ns=time.monotonic_ns())))
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


@pytest.mark.parametrize("fault", ["scope", "response", "source", "text", "policy", "advanced", "model_failure", "tts_failure"])
async def test_wrong_hypothesis_source_skips_preparation_but_keeps_formal_input_exit(monkeypatch, fault):
    from server.realtime import AssistantYieldRequested as CanonicalYield
    from server.realtime.capabilities.coordinated_turn_manager import (
        CoordinatedTurnManagerCapabilityAdapter,
    )
    from server.realtime.protocol.commands import InterruptedContextPolicy
    from server.turn_policy.policy import TurnPolicy
    from server.voice_session.protocol import OutputStopResult, PlaybackProgressV2
    from tests.realtime.test_coordinated_turn_manager import Interrupt
    from tests.realtime.test_input_association_production import wait_for
    from tests.realtime.test_realtime_websocket_bridge import context
    from tests.realtime.test_reply_playback_observation import Brain as OriginalBrain
    from tests.realtime.test_reply_playback_observation import playing_core
    from tests.realtime.test_sentence_permit_actor import ControlledAsr

    class Counted(OriginalBrain):
        def __init__(self):
            self.turns = []
        async def stream(self, turn):
            self.turns.append(turn)
            if fault == "model_failure" and len(self.turns) == 2:
                raise RuntimeError("candidate model failed")
            async for part in super().stream(turn):
                yield part

    provider, asr = Counted(), ControlledAsr()
    asr.latest = "补充一下，明天也要看。"
    from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
    from tests.realtime.test_reply_playback_observation import Provider
    class FailingDuplex:
        calls = 0
        async def synthesize_duplex(self, texts):
            self.calls += 1
            async for value in texts:
                if self.calls == 2:
                    raise RuntimeError("candidate TTS failed")
                async for packet in Provider().synthesize_stream(value):
                    yield packet
    cache = (SpeculativeSpeechPipeline(brain=provider, tts=FailingDuplex()) if fault == "tts_failure"
        else SpeculativeStreamingBrain(provider))
    notices, observed = [], []
    manager = CoordinatedTurnManagerCapabilityAdapter(TurnPolicy,
        semantic_interruption_classifier=Interrupt(), response_prefetch_enabled=True,
        sentence_handoff_prefetch_enabled=True, response_prefetcher=cache,
        asr_idle_stop_ms=15, semantic_interruption_idle_ms=5, recovery_timeout_ms=1000)
    core, bridge = await playing_core(precise_stop=True, brain=cache, asr=asr,
        tts=cache if fault == "tts_failure" else None, turn_manager=manager, managed=True)
    actor, pump = core._input_pipeline._turn_manager, None
    actor._prefetch._observer = lambda operation, generation, detail: notices.append(operation)
    second = replace(context(), turn_id="supplement", generation=2)
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
                observed.append(event)
                await bridge.handle_event(event)
        pump = asyncio.create_task(drain())
        await wait_for(lambda: actor._input.yielded)
        request = next(iter(bridge._output_stops.values())).request
        original_get = core._speech_deliveries.get
        async def wrong_once(speech_id):
            record = await original_get(speech_id)
            if fault in {"model_failure", "tts_failure"}:
                return record
            if fault == "scope":
                return replace(record, context=replace(record.context, voice_session_id="foreign"))
            if fault == "response":
                return replace(record, context=replace(record.context, response_id="foreign"))
            if fault == "source":
                return replace(record, source_item_id="foreign")
            if fault == "text":
                return replace(record, intended_spoken_content="错误文本。")
            if fault == "policy":
                return replace(record, interrupted_context_policy=InterruptedContextPolicy.OMIT)
            return replace(record, delivered_speech_transcript=record.intended_spoken_content[:4])
        monkeypatch.setattr(core._speech_deliveries, "get", wrong_once)
        await stop(actor, second)
        if fault in {"model_failure", "tts_failure"}:
            await wait_for(lambda: cache._state is not None and cache._state.done and cache._state.error is not None)
            assert len(provider.turns) == 2
        else:
            await wait_for(lambda: "failed" in notices)
            assert len(provider.turns) == 1
            assert cache._state is None
        assert asr.commits == []
        monkeypatch.setattr(core._speech_deliveries, "get", original_get)
        await bridge.handle_inbound(OutputStopResult(output_epoch="epoch", speech_id="response:reply",
            generation=1, stop_command_id=request.stop_command_id, outcome="queue_stopped", played_position_samples=1000))
        if fault in {"model_failure", "tts_failure"}:
            from server.conversation_journal import ConversationItemKind, TextContent
            from server.realtime import ResponseFailed
            await wait_for(lambda: any(isinstance(event, ResponseFailed) and event.context.generation == 2
                for event in observed))
            assert len(asr.commits) == 1
            assert len(provider.turns) == 2
            assert any(item.kind is ConversationItemKind.USER_INPUT and item.context.turn_id == second.turn_id
                and any(isinstance(part, TextContent) and asr.latest in part.text for part in item.content)
                for item in core._projected_items.values())
            assert not any(frame.type == "assistant_audio_chunk" and frame.generation == 2
                for frame in bridge._transport.frames)
            return
        await wait_for(lambda: any(frame.type == "assistant_speech_text" and frame.generation == 2
            for frame in bridge._transport.frames))
        assert len(asr.commits) == 1
        assert len(provider.turns) == 2
        assert provider.turns[-1].text == "说两句\n" + asr.latest
        assert "第一句。" in provider.turns[-1].conversation_context
    finally:
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        await bridge.close()
        await bridge._conversation.close()
