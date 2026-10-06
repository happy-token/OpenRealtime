"""Normalized input → actor → engine → Journal → automatic Brain request.

ASR finals and renderer receipts are deterministic doubles, not physical audio.
"""

import asyncio
from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemKind,
    InMemoryConversationJournal,
    JournalScope,
)
from server.realtime import (
    ActiveRealtimeConversations,
    AudioDelta,
    CancelResponse,
    ReportPlaybackProgress,
    RequestResponse,
)
from server.realtime.capabilities import (
    DeterministicSpeechRenderer,
    LegacyAsrCapabilityAdapter,
    LegacyBrainCapabilityAdapter,
    LegacyTtsCapabilityAdapter,
    LegacyVadCapabilityAdapter,
)
from server.realtime.capabilities.asr import CommitAsrInput
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.cascaded import CascadedRealtimeEngine
from server.realtime.control_plane import RealtimeTurnController
from server.realtime.journaled import JournaledRealtimeConversation
from server.realtime.runtime import RealtimeRuntimeFactory
from server.signals.energy_vad import EnergyVad, EnergyVadConfig
from server.speech.asr import PreloadedAsrEngine
from server.turn_policy.policy import TurnPolicy
from tests.realtime.test_cascaded_engine import EchoDuplexTts, context
from tests.realtime.test_coordinated_turn_manager import Endpoint, Interrupt, start, stop, text
from tests.realtime.test_reply_revision_coordination import final


class RecordingBrain:
    def __init__(self, *, block_first=False):
        self.turns = []
        self.block_first = block_first

    async def stream(self, turn):
        self.turns.append(turn)
        yield "北京今天晴。"
        if self.block_first and len(self.turns) == 1:
            await asyncio.Event().wait()


class RecordingInterrupt(Interrupt):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def classify_request(self, request):
        self.requests.append(request)
        return await super().classify_request(request)


async def wait_for(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(.001)


@pytest.mark.asyncio
async def test_runtime_restoration_preserves_input_identity_through_a_real_correction(monkeypatch):
    journal, brain = InMemoryConversationJournal(), RecordingBrain()
    engine = CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(lambda: EnergyVad(EnergyVadConfig())),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=CoordinatedTurnManagerCapabilityAdapter(TurnPolicy, eot_classifier=Endpoint()),
        brain=LegacyBrainCapabilityAdapter(brain), speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    )
    cores = []
    open_engine = engine.open

    async def recording_open(**kwargs):
        core = await open_engine(**kwargs)
        cores.append(core)
        send_asr = core._input_pipeline._asr.send

        async def controlled_asr(command):
            if not isinstance(command, CommitAsrInput):
                await send_asr(command)

        monkeypatch.setattr(core._input_pipeline._asr, "send", controlled_asr)
        return core

    monkeypatch.setattr(engine, "open", recording_open)
    factory = RealtimeRuntimeFactory(engine=engine, journal=journal,
                                    active_conversations=ActiveRealtimeConversations())

    async def submit(value, ctx):
        actor = cores[-1]._input_pipeline._turn_manager
        await start(actor, ctx)
        await text(actor, value, ctx=ctx)
        await stop(actor, ctx)
        await wait_for(lambda: actor.snapshot().commit_pending)
        await final(actor, ctx, value)

    first = await factory.open(context=context(), profile=None)
    try:
        await submit("查北京天气", context())
        await wait_for(lambda: len(brain.turns) == 1 and cores[-1]._active_response_id is None
                       and any(item.kind is ConversationItemKind.ASSISTANT_OUTPUT
                               for item in cores[-1]._projected_items.values()))
        original = cores[-1]._input_pipeline._turn_manager._revisions.input
        old_reply = cores[-1]._input_pipeline._turn_manager._revisions.reply
    finally:
        await first.close()
    current = replace(context(), voice_session_id="new-voice", device_id="new-device", turn_id="new-turn")
    restored = await factory.open(context=current, profile=None)
    try:
        actor = cores[-1]._input_pipeline._turn_manager
        assert actor._revisions.input == original
        assert len(brain.turns) == 1
        assert not actor.response_delivery_allowed(old_reply.response_id)
        await submit("不是，上海", current)
        await wait_for(lambda: len(brain.turns) == 2 and cores[-1]._active_response_id is None
                       and sum(item.kind is ConversationItemKind.ASSISTANT_OUTPUT
                               for item in cores[-1]._projected_items.values()) == 2)
        users = [item for item in await journal.read(JournalScope.from_context(current))
                 if item.kind is ConversationItemKind.USER_INPUT]
        assert users[-1].provider_metadata["input_id"] == original.input_id
        assert users[-1].provider_metadata["input_version"] == 2
        assert users[-1].provider_metadata["input_observation_id"] == actor._revisions.input.observation_id
        assert users[-1].context.voice_session_id == "new-voice"
        assert users[0].context.voice_session_id == context().voice_session_id
        assert brain.turns[-1].text == "查北京天气\n不是，上海"
        assert actor._revisions.reply.reply_version == 2
        assert actor._revisions.reply.supersedes_response_id == old_reply.response_id
    finally:
        await restored.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["correction_unplayed", "correction_played", "unresolved",
                                  "cancelled_then_played", "played_after_correction_commit", "multi_reply_same_turn"])
async def test_final_association_reaches_journal_and_brain_without_extra_classifier_calls(monkeypatch, case):
    cancelled = case in {"cancelled_then_played", "played_after_correction_commit"}
    brain, endpoint, interruption = RecordingBrain(block_first=cancelled), Endpoint(), RecordingInterrupt()
    journal = InMemoryConversationJournal()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(lambda: EnergyVad(EnergyVadConfig())),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=CoordinatedTurnManagerCapabilityAdapter(TurnPolicy, eot_classifier=endpoint,
            semantic_interruption_classifier=interruption,
            input_evidence_journal=journal),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(), tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    actor = core._input_pipeline._turn_manager
    send_asr = core._input_pipeline._asr.send

    async def controlled_asr(command):
        if not isinstance(command, CommitAsrInput):
            await send_asr(command)

    monkeypatch.setattr(core._input_pipeline._asr, "send", controlled_asr)
    conversation = RealtimeTurnController(context=context(), conversation=JournaledRealtimeConversation(
        context=context(), journal=journal, engine_conversation=core))

    async def submit(value, ctx):
        await start(actor, ctx)
        await text(actor, value, ctx=ctx)
        await stop(actor, ctx)
        await wait_for(lambda: actor.snapshot().commit_pending)
        calls = (len(endpoint.requests), len(interruption.requests))
        await final(actor, ctx, value)
        return calls

    try:
        await submit("查北京天气", context())
        if cancelled:
            await wait_for(lambda: len(brain.turns) == 1 and any(isinstance(event, AudioDelta)
                           for event in conversation._events._queue))
            await conversation.send(CancelResponse(command_id="cancel", idempotency_key="cancel",
                context=context(), response_id=actor._revisions.reply.response_id, reason="user_cancelled"))
        await wait_for(lambda: len(brain.turns) == 1 and core._active_response_id is None
                       and any(item.kind is ConversationItemKind.ASSISTANT_OUTPUT
                               for item in core._projected_items.values()))
        first_reply = actor.response_revision(actor._revisions.reply.response_id)
        old_assistant = next(item for item in core._projected_items.values()
                             if item.kind is ConversationItemKind.ASSISTANT_OUTPUT)
        if case in {"correction_played", "cancelled_then_played", "multi_reply_same_turn"}:
            # Generation has finished; only this receipt confirms actual playback.
            await conversation.send(ReportPlaybackProgress(command_id="heard", idempotency_key="heard",
                context=replace(context(), response_id=first_reply.response_id),
                speech_id=f"response:{first_reply.response_id}", delivered_text_end=len("北京今天晴。"),
                played_audio_end_us=500_000, completed=not cancelled, stopped=cancelled))
            assert actor.response_revision(first_reply.response_id).playback_started
            if cancelled:
                assert not actor.response_delivery_allowed(first_reply.response_id)
        if case == "multi_reply_same_turn":
            # Two replies share one input turn: only A was heard. An unplayed B
            # cannot invalidate A's confirmed history merely by sharing turn_id.
            await conversation.send(RequestResponse(command_id="extra", idempotency_key="extra",
                context=context(), response_id="extra", minimum_thread_sequence=1))
            await wait_for(lambda: len(brain.turns) == 2 and core._active_response_id is None
                           and sum(item.kind is ConversationItemKind.ASSISTANT_OUTPUT
                                   for item in core._projected_items.values()) == 2)
            assert not actor.response_revision("extra").playback_started
        second_text = "帮我查日期" if case == "unresolved" else "不是，上海"
        calls_before_final = await submit(second_text, replace(context(), turn_id="next", generation=2))
        await wait_for(lambda: len(brain.turns) == (3 if case == "multi_reply_same_turn" else 2))
        items = await journal.read(JournalScope.from_context(context()))
        users = [item for item in items if item.kind is ConversationItemKind.USER_INPUT]
        assert len(users) == 2
        metadata = users[-1].provider_metadata
        turn = brain.turns[-1]
        if case == "played_after_correction_commit":
            assert metadata["supersedes_unplayed_reply"]
            await conversation.send(ReportPlaybackProgress(command_id="late-heard", idempotency_key="late-heard",
                context=replace(context(), response_id=first_reply.response_id),
                speech_id=f"response:{first_reply.response_id}", delivered_text_end=len("北京今天晴。"),
                played_audio_end_us=500_000, stopped=True))
            # The commit-time flag is immutable; future context uses refined
            # delivery facts, never permanently deletes all assistants in a turn.
            rebuilt = await core._turn_from_projection(users[-1].sequence, generation=2)
            assert "北京今天晴。" in rebuilt.conversation_context
        prior_ids = {item.item_id for item in core._prior_model_items(users[-1].sequence)}
        if case == "unresolved":
            assert metadata["input_relation"] == "unresolved"
            assert metadata["related_turn_id"] == users[0].context.turn_id
            assert metadata["continuation_of_turn_id"] is None
            assert turn.text == second_text
            assert turn.input_relation_unresolved
            assert "关联尚未确认" in turn.model_text
            assert "查北京天气" in turn.model_text
        else:
            assert metadata["input_relation"] == "correction"
            assert metadata["input_version"] == 2
            assert metadata["input_id"] == users[0].provider_metadata["input_id"]
            assert turn.text == "查北京天气\n不是，上海"
            played_before_commit = case in {"correction_played", "cancelled_then_played"}
            assert metadata["supersedes_unplayed_reply"] is not played_before_commit
            assert (old_assistant.item_id in prior_ids) is (played_before_commit or case in {
                "played_after_correction_commit", "multi_reply_same_turn"})
            if played_before_commit or case == "multi_reply_same_turn":
                assert "北京今天晴。" in turn.conversation_context
        assert len(endpoint.requests) == (2 if case == "correction_played" or cancelled else 1)
        assert (len(endpoint.requests), len(interruption.requests)) == calls_before_final
    finally:
        await conversation.close()
