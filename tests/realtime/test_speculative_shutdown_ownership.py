"""Actual actor pre-generation must remain owned through Core/Managed shutdown."""

import asyncio

import pytest

from server.conversation_journal import InMemoryConversationJournal
from server.realtime.capabilities.brain_streaming import VoiceRuntimeBrainStreamingAdapter
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
from server.realtime.registry import ActiveRealtimeConversations
from server.realtime.runtime import RealtimeRuntimeFactory
from tests.realtime import test_cascaded_engine as fixtures
from tests.realtime.test_coordinated_turn_manager import Endpoint, start, text


@pytest.mark.parametrize("wrapper", ["core", "managed"])
@pytest.mark.parametrize("kind", ["text", "speech", "tool_chat"])
async def test_actual_actor_prefetch_shutdown_retains_owned_supplier_after_waiter_cancel(wrapper, kind):
    entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Brain:
        async def stream(self, turn):
            try:
                entered.set()
                await release.wait()
                yield "late"
            finally:
                closed.set()

    tts = fixtures.EchoDuplexTts()
    cache = (SpeculativeSpeechPipeline(brain=Brain(), tts=tts) if kind == "speech" else
             SpeculativeStreamingBrain(Brain()))
    brain = VoiceRuntimeBrainStreamingAdapter(chat=cache, tools=object()) if kind == "tool_chat" else cache
    engine = fixtures.CascadedRealtimeEngine(
        vad=fixtures.LegacyVadCapabilityAdapter(lambda: fixtures.EnergyVad(fixtures.EnergyVadConfig())),
        asr=fixtures.LegacyAsrCapabilityAdapter(fixtures.PreloadedAsrEngine("unused")),
        turn_manager=CoordinatedTurnManagerCapabilityAdapter(
            fixtures.TurnPolicy, semantic_chunks_enabled=True, response_prefetch_enabled=True,
            response_prefetcher=brain, eot_classifier=Endpoint(), chunk_stability_ms=5),
        brain=fixtures.LegacyBrainCapabilityAdapter(brain),
        speech_renderer=fixtures.DeterministicSpeechRenderer(),
        tts=fixtures.LegacyTtsCapabilityAdapter(cache if kind == "speech" else tts),
    )
    active = ActiveRealtimeConversations()
    ctx = fixtures.context()
    if wrapper == "managed":
        owner = await RealtimeRuntimeFactory(engine=engine, journal=InMemoryConversationJournal(),
                                            active_conversations=active).open(context=ctx, profile=None)
        core = owner._conversation._conversation._engine_conversation
    else:
        owner = core = await engine.open(context=ctx, profile=None)
    actor = core._input_pipeline._turn_manager
    await start(actor, ctx=ctx)
    await text(actor, "你好。", ctx=ctx)
    await asyncio.wait_for(entered.wait(), .5)
    producer = cache._state.task
    closing = asyncio.create_task(owner.close())
    closing_again = None
    try:
        await asyncio.sleep(.15)
        assert not closing.done() and not producer.done() and not closed.is_set()
        if wrapper == "managed":
            assert active.references_thread(tenant_id=ctx.tenant_id, user_id=ctx.user_id, thread_id=ctx.thread_id)
        closing.cancel()
        await asyncio.gather(closing, return_exceptions=True)
        closing_again = asyncio.create_task(owner.close())
        await asyncio.sleep(.02)
        assert not closing_again.done() and not producer.done()
        if wrapper == "managed":
            assert active.references_thread(tenant_id=ctx.tenant_id, user_id=ctx.user_id, thread_id=ctx.thread_id)
        release.set()
        await asyncio.wait_for(closing_again, .5)
        assert producer.done() and closed.is_set()
        if wrapper == "managed":
            assert not active.references_thread(tenant_id=ctx.tenant_id, user_id=ctx.user_id, thread_id=ctx.thread_id)
    finally:
        release.set()
        await asyncio.gather(producer, closing, *([closing_again] if closing_again else []), return_exceptions=True)
        await owner.close()


@pytest.mark.parametrize("kind", ["text", "speech"])
async def test_failed_actual_prefetch_close_keeps_managed_history_reserved(kind):
    from server.core.async_stream import OwnedStreamCleanupError
    from server.realtime.registry import SessionHistoryDeletionConflict

    entered = asyncio.Event()

    class Iterator:
        def __init__(self):
            self.sent = False
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self.sent:
                raise StopAsyncIteration
            self.sent = True
            return "one"
        async def aclose(self):
            entered.set()
            raise RuntimeError("supplier close unconfirmed")

    class Brain:
        def stream(self, turn):
            return Iterator()

    tts = fixtures.EchoDuplexTts()
    cache = (SpeculativeStreamingBrain(Brain()) if kind == "text" else
             SpeculativeSpeechPipeline(brain=Brain(), tts=tts))
    engine = fixtures.CascadedRealtimeEngine(
        vad=fixtures.LegacyVadCapabilityAdapter(lambda: fixtures.EnergyVad(fixtures.EnergyVadConfig())),
        asr=fixtures.LegacyAsrCapabilityAdapter(fixtures.PreloadedAsrEngine("unused")),
        turn_manager=CoordinatedTurnManagerCapabilityAdapter(
            fixtures.TurnPolicy, semantic_chunks_enabled=True, response_prefetch_enabled=True,
            response_prefetcher=cache, eot_classifier=Endpoint(), chunk_stability_ms=5,
            input_evidence_journal=InMemoryConversationJournal()),
        brain=fixtures.LegacyBrainCapabilityAdapter(cache),
        speech_renderer=fixtures.DeterministicSpeechRenderer(),
        tts=fixtures.LegacyTtsCapabilityAdapter(cache if kind == "speech" else tts),
    )
    active, ctx = ActiveRealtimeConversations(), fixtures.context()
    owner = await RealtimeRuntimeFactory(engine=engine, journal=InMemoryConversationJournal(),
                                        active_conversations=active).open(context=ctx, profile=None)
    core = owner._conversation._conversation._engine_conversation
    await start(core._input_pipeline._turn_manager, ctx=ctx)
    await text(core._input_pipeline._turn_manager, "你好。", ctx=ctx)
    await asyncio.wait_for(entered.wait(), .5)
    with pytest.raises(OwnedStreamCleanupError, match="supplier close unconfirmed"):
        await owner.close()
    assert active.resolve(ctx) is None
    assert active.references_thread(tenant_id=ctx.tenant_id, user_id=ctx.user_id, thread_id=ctx.thread_id)
    with (
        pytest.raises(SessionHistoryDeletionConflict),
        active.session_deletion_guard([(ctx.tenant_id, ctx.user_id, ctx.voice_session_id)]),
    ):
        pass
    assert owner._event_pump.done()
    async with asyncio.timeout(.1):
        assert [event async for event in core.events()] == []
    actor = core._input_pipeline._turn_manager
    assert actor._evidence._closed and actor._evidence._worker.done()
    assert actor._input is None
    with pytest.raises(OwnedStreamCleanupError, match="supplier close unconfirmed"):
        await owner.close()
