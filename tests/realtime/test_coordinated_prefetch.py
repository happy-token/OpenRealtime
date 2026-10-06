from __future__ import annotations

import asyncio

import pytest

from server.core.turn_content import TurnContent
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.turn_policy.policy import TurnPolicy
from tests.realtime.test_cascaded_capabilities import context
from tests.realtime.test_coordinated_turn_manager import Endpoint, start, text


class Prefetch:
    def __init__(self):
        self.prepared = []
        self.invalidations = []

    async def prepare(self, turn):
        self.prepared.append(turn)
        return True

    async def invalidate(self, generation, *, reason):
        self.invalidations.append((generation, reason))
        return True


async def opened(prefetch):
    session = await CoordinatedTurnManagerCapabilityAdapter(
        TurnPolicy,
        semantic_chunks_enabled=True,
        response_prefetch_enabled=True,
        chunk_stability_ms=5,
        response_prefetcher=prefetch,
        eot_classifier=Endpoint(),
    ).open(context=context())

    async def build(text, generation):
        return TurnContent(text=text, generation=generation, conversation_context="前轮真实上下文")

    session.set_prefetch_turn_builder(build)
    return session


async def test_stable_input_prepares_with_commit_context_and_growth_invalidates():
    prefetch = Prefetch()
    session = await opened(prefetch)
    try:
        await start(session)
        await text(session, "帮我介绍上海", 1)
        await asyncio.sleep(0.01)
        assert prefetch.prepared == []
        await text(session, "帮我介绍上海。", 2)
        await asyncio.sleep(0.02)
        assert len(prefetch.prepared) == 1
        assert prefetch.prepared[0].conversation_context == "前轮真实上下文"
        await text(session, "帮我介绍上海。还有苏州", 3)
        await asyncio.sleep(0.01)
        assert prefetch.invalidations[-1][1] == "asr_revision"
    finally:
        await session.close()


async def test_revision_only_terminal_punctuation_reuses_prefetch():
    prefetch = Prefetch()
    session = await opened(prefetch)
    try:
        await start(session)
        await text(session, "帮我介绍上海。", 1)
        await asyncio.sleep(0.02)
        await text(session, "帮我介绍上海！", 2)
        await asyncio.sleep(0.01)
        assert len(prefetch.prepared) == 1
        assert prefetch.invalidations == []
    finally:
        await session.close()
    assert prefetch.invalidations[-1][1] == "session_closed"


async def test_committed_turn_reuses_one_producer_without_exposing_speculative_text():
    from server.realtime.capabilities.asr import AsrTranscriptFinal
    from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
    from server.realtime.capabilities.turn_manager import (
        AsrCommitRequested,
        ObserveAsrEvent,
        UserTurnCommitted,
    )
    from tests.realtime.test_coordinated_turn_manager import stop, take

    class Brain:
        def __init__(self):
            self.turns = []
            self.started = asyncio.Event()

        async def stream(self, turn):
            self.turns.append(turn)
            self.started.set()
            yield "上海是一座城市。"

    provider = Brain()
    prefetch = SpeculativeStreamingBrain(provider)
    session = await opened(prefetch)
    stream = session.events()
    try:
        await start(session)
        await text(session, "帮我介绍上海。", 1)
        await asyncio.wait_for(provider.started.wait(), 0.2)
        assert session.snapshot().commit_pending is False
        await stop(session)
        request = await take(stream, AsrCommitRequested)
        await session.send(
            ObserveAsrEvent(
                event=AsrTranscriptFinal(
                    context=request.context, revision=2, text="帮我介绍上海！", reason="test"
                )
            )
        )
        committed = await take(stream, UserTurnCommitted)
        final = TurnContent(
            text=committed.text,
            generation=committed.context.generation,
            conversation_context="前轮真实上下文",
        )
        assert [delta async for delta in prefetch.stream(final)] == ["上海是一座城市。"]
        assert len(provider.turns) == 1
    finally:
        await stream.aclose()
        await session.close()


async def test_interruption_chunks_never_prepare_a_reply():
    from dataclasses import replace

    from server.realtime.capabilities.turn_manager import ObserveSystemResponseStarted
    from tests.realtime.test_coordinated_turn_manager import Interrupt

    prefetch = Prefetch()
    session = await CoordinatedTurnManagerCapabilityAdapter(
        TurnPolicy,
        semantic_chunks_enabled=True,
        response_prefetch_enabled=True,
        response_prefetcher=prefetch,
        semantic_interruption_classifier=Interrupt(),
    ).open(context=context())
    try:
        await session.send(
            ObserveSystemResponseStarted(
                response_id="a", context=replace(context(), response_id="a")
            )
        )
        await start(session)
        await text(session, "改查上海的。", 1)
        await asyncio.sleep(0.01)
        assert prefetch.prepared == []
    finally:
        await session.close()


@pytest.mark.parametrize("cache", ["text", "text_audio"])
@pytest.mark.parametrize("projection", ["full", "budgeted"])
async def test_engine_prefetch_uses_same_journal_context_as_final_response(cache, projection):
    from server.conversation_journal import (
        ConversationItemDraft,
        ConversationItemKind,
        ConversationItemStatus,
        InMemoryConversationJournal,
        TextContent,
    )
    from server.realtime import (
        AppendItem,
        ItemProjected,
        JournaledRealtimeConversation,
        RequestResponse,
        ResponseCompleted,
    )
    from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
    from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
    from server.voice_session.context import (
        BudgetedConversationContextProjector,
        ConservativeTokenCounter,
        ContextPolicy,
        FullConversationContextProjector,
        InMemorySummaryCheckpointStore,
        SummaryCheckpointValidator,
    )
    from tests.realtime import test_cascaded_engine as fixtures

    class Brain:
        def __init__(self):
            self.turns = []

        async def stream(self, turn):
            self.turns.append(turn)
            yield "上海是一座城市。"

    provider = Brain()
    tts = fixtures.EchoDuplexTts()
    brain = (SpeculativeSpeechPipeline(brain=provider, tts=tts) if cache == "text_audio"
             else SpeculativeStreamingBrain(provider))
    validator = SummaryCheckpointValidator()
    projector = (FullConversationContextProjector() if projection == "full" else
        BudgetedConversationContextProjector(policy=ContextPolicy(
            policy_version="test", context_window_tokens=1000, max_output_tokens=20,
            tool_schema_tokens=0, governing_instruction_tokens=0, current_input_tokens=20,
            safety_margin_tokens=20), token_counter=ConservativeTokenCounter(),
            checkpoint_store=InMemorySummaryCheckpointStore(validator),
            checkpoint_validator=validator, compressor=None))
    ctx = fixtures.context()
    core = await fixtures.CascadedRealtimeEngine(
        vad=fixtures.LegacyVadCapabilityAdapter(
            lambda: fixtures.EnergyVad(
                fixtures.EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=fixtures.LegacyAsrCapabilityAdapter(fixtures.PreloadedAsrEngine("unused")),
        turn_manager=CoordinatedTurnManagerCapabilityAdapter(
            fixtures.TurnPolicy, response_prefetch_enabled=True, response_prefetcher=brain
        ),
        brain=fixtures.LegacyBrainCapabilityAdapter(brain),
        speech_renderer=fixtures.DeterministicSpeechRenderer(),
        tts=fixtures.LegacyTtsCapabilityAdapter(brain if cache == "text_audio" else tts),
        context_projector_factory=lambda: projector,
    ).open(context=ctx, profile=None)
    conversation = JournaledRealtimeConversation(
        context=ctx, journal=InMemoryConversationJournal(), engine_conversation=core
    )
    events = conversation.events()
    try:
        for sequence, phrase in ((1, "我刚才问了杭州"), (2, "介绍上海。")):
            if sequence == 2:
                turn = await core._turn_for_prefetch(phrase, ctx.generation)
                assert "杭州" in turn.conversation_context
                await brain.prepare(turn)
            await conversation.send(
                AppendItem(
                    command_id=f"append-{sequence}",
                    idempotency_key=f"append-{sequence}",
                    context=ctx,
                    draft=ConversationItemDraft(
                        item_id=f"user-{sequence}",
                        context=ctx,
                        kind=ConversationItemKind.USER_INPUT,
                        status=ConversationItemStatus.COMPLETED,
                        producer="test",
                        content=(TextContent(phrase),),
                    ),
                )
            )
            assert isinstance(await anext(events), ItemProjected)
        await conversation.send(
            RequestResponse(
                command_id="response",
                idempotency_key="response",
                context=ctx,
                response_id="response",
                minimum_thread_sequence=2,
            )
        )
        async with asyncio.timeout(1):
            async for event in events:
                if isinstance(event, ResponseCompleted):
                    break
        assert len(provider.turns) == 1
        assert provider.turns[0].conversation_context == turn.conversation_context
        formal = await core._turn_from_projection(2, generation=ctx.generation)
        assert formal.context_projection_digest == turn.context_projection_digest
    finally:
        await events.aclose()
        await conversation.close()
