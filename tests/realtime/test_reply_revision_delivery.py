import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    InMemoryConversationJournal,
    TextContent,
)
from server.realtime import (
    AudioDelta,
    CancelResponse,
    DisplayContentDelta,
    ProjectCommittedItem,
    RequestResponse,
    ResponseCancelled,
    SpokenContentDelta,
)
from server.realtime.capabilities import (
    DeterministicSpeechRenderer,
    LegacyAsrCapabilityAdapter,
    LegacyBrainCapabilityAdapter,
    LegacyTtsCapabilityAdapter,
    LegacyVadCapabilityAdapter,
)
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.cascaded import CascadedRealtimeEngine
from server.signals.energy_vad import EnergyVad, EnergyVadConfig
from server.speech.asr import PreloadedAsrEngine
from server.turn_policy.policy import TurnPolicy
from tests.realtime.test_cascaded_engine import (
    EchoDuplexTts,
    GatedStreamingBrain,
    context,
)
from tests.realtime.test_coordinated_turn_manager import Interrupt, start, text


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_source", ["semantic", "command"])
async def test_revoked_response_already_queued_text_and_audio_are_not_delivered(cancel_source):
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(lambda: EnergyVad(EnergyVadConfig())),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=CoordinatedTurnManagerCapabilityAdapter(
            TurnPolicy, semantic_interruption_classifier=Interrupt()),
        brain=LegacyBrainCapabilityAdapter(GatedStreamingBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    try:
        journal = InMemoryConversationJournal()
        item = (await journal.append(ConversationItemDraft(
            item_id="user", context=context(), kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMPLETED, producer="test",
            content=(TextContent("查北京天气"),), occurred_at=datetime.now(UTC)),
        )).item
        await core.send(ProjectCommittedItem(command_id="project", idempotency_key="project",
            context=context(), item=item))
        await core.send(RequestResponse(command_id="request", idempotency_key="request",
            context=context(), response_id="a", minimum_thread_sequence=1))
        # Delay the transport consumer until old audio is demonstrably queued.
        async with asyncio.timeout(.5):
            while not any(isinstance(event, AudioDelta) for event in core._events._queue):
                await asyncio.sleep(.001)
        manager = core._input_pipeline._turn_manager
        if cancel_source == "semantic":
            updated = replace(context(), turn_id="correction", generation=2)
            await start(manager, updated)
            await text(manager, "不是，查上海天气", ctx=updated)
        else:
            await core.send(CancelResponse(command_id="cancel", idempotency_key="cancel",
                context=context(), response_id="a", reason="user_cancelled"))
        async with asyncio.timeout(.5):
            while not any(isinstance(event, ResponseCancelled) for event in core._events._queue):
                await asyncio.sleep(.001)
        delivered = []
        async with asyncio.timeout(.5):
            async for event in core.events():
                delivered.append(event)
                if isinstance(event, ResponseCancelled):
                    break
        assert not any(isinstance(event, (DisplayContentDelta, SpokenContentDelta, AudioDelta))
                       for event in delivered)
        assert not manager.response_delivery_allowed("a")
    finally:
        await core.close()
