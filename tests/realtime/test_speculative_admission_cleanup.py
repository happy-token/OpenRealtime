"""Rejected admission must not permanently poison actual capability cleanup."""

import asyncio
from dataclasses import replace

import pytest

from server.core.turn_content import TurnContent
from server.realtime.capabilities.brain import (
    BrainResponseFailed,
    LegacyBrainCapabilityAdapter,
    RequestBrainResponse,
)
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
from server.realtime.capabilities.tts import (
    AppendTtsText,
    CommitTts,
    LegacyTtsCapabilityAdapter,
    StartTts,
    TtsFailed,
)
from tests.realtime.test_cascaded_capabilities import context
from tests.realtime.test_cascaded_engine import EchoDuplexTts


@pytest.mark.parametrize("kind", ["brain_text", "brain_speech", "tts"])
async def test_rejected_admission_closes_after_retired_supplier_actually_exits(kind):
    entered, release, exited = (asyncio.Event() for _ in range(3))
    calls, cancelled = [], []

    class Provider:
        async def stream(self, turn):
            calls.append(turn.text)
            try:
                entered.set()
                await release.wait()
                yield "旧候选"
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
            finally:
                exited.set()

    cache = (SpeculativeStreamingBrain(Provider()) if kind == "brain_text" else
             SpeculativeSpeechPipeline(brain=Provider(), tts=EchoDuplexTts()))
    await cache.prepare(TurnContent(text="old", generation=1))
    supplier = cache._state.task
    await asyncio.wait_for(entered.wait(), .5)
    await cache.invalidate(1, reason="correction")
    session = await (LegacyTtsCapabilityAdapter(cache) if kind == "tts" else
                     LegacyBrainCapabilityAdapter(cache)).open(context=replace(context(), generation=2))
    events = session.events()
    closing = None
    try:
        if kind == "tts":
            await session.send(StartTts(speech_id="corrected"))
            await session.send(AppendTtsText(speech_id="corrected", text_sequence=1,
                                           delta="corrected"))
            await session.send(CommitTts(speech_id="corrected"))
        else:
            await session.send(RequestBrainResponse(response_id="corrected", request_token="attempt",
                turn=TurnContent(text="corrected", generation=2)))
        async with asyncio.timeout(.5):
            async for event in events:
                if isinstance(event, (BrainResponseFailed, TtsFailed)):
                    assert "pending" in event.error
                    if isinstance(event, TtsFailed):
                        assert not event.cleanup_failed
                    break
        assert calls == ["old"] and not cancelled and not exited.is_set()
        assert supplier in cache._cleanup._retired
        # Core's actor owns unsolicited candidates separately from a formal
        # Brain request; close both owners as the production session does.
        async def close_owners():
            await asyncio.gather(session.close(), cache.close())
        closing = asyncio.create_task(close_owners())
        await asyncio.sleep(.02)
        assert not closing.done(), "close must join the still-owned old supplier"
        release.set()
        await asyncio.wait_for(closing, .5)
        assert exited.is_set() and supplier.done()
        assert calls == ["old"] and not cancelled
        assert not cache._cleanup._retired
        await session.close()
    finally:
        release.set()
        await asyncio.gather(supplier, *([closing] if closing else []), return_exceptions=True)
        await events.aclose()
        await asyncio.gather(session.close(), return_exceptions=True)
