import asyncio
from dataclasses import replace

import pytest

from server.conversation_journal import InMemoryConversationJournal
from server.conversation_journal.input_evidence import read_input_evidence
from server.realtime.capabilities.asr import AsrTranscriptFinal
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    AssistantYieldRequested,
    ObserveAsrEvent,
    ObserveAssistantYielded,
    ObserveSystemResponseStarted,
    SemanticInputRejected,
    UserTurnCommitted,
)
from server.turn_policy.eot_classifier import EotClassification, EotDecision
from server.turn_policy.policy import TurnPolicy
from server.turn_policy.semantic_interruption import InterruptionLabel
from tests.realtime.test_coordinated_turn_manager import (
    Endpoint,
    Interrupt,
    context,
    start,
    stop,
    take,
    text,
)


async def final(session, ctx, value):
    await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(
        context=ctx, revision=1, text=value, reason="final")))


@pytest.mark.asyncio
@pytest.mark.parametrize("reuse_asr_turn", [False, True])
async def test_unplayed_correction_revokes_before_yield_ack_and_records_versions(reuse_asr_turn):
    journal = InMemoryConversationJournal()
    session = await CoordinatedTurnManagerCapabilityAdapter(
        TurnPolicy, eot_classifier=Endpoint(), semantic_interruption_classifier=Interrupt(),
        input_evidence_journal=journal,
    ).open(context=context())
    stream = session.events()
    original = context()
    updated = original if reuse_asr_turn else replace(original, turn_id="next", generation=original.generation + 1)
    try:
        await start(session, original)
        await text(session, "查北京天气", ctx=original)
        await stop(session, original)
        await take(stream, AsrCommitRequested)
        await final(session, original, "查北京天气")
        first = await take(stream, UserTurnCommitted)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=original, preparing=True))
        assert session.response_delivery_allowed("a")
        await start(session, updated)
        await text(session, "不是，上海", ctx=updated)
        await take(stream, AssistantYieldRequested)
        assert not session.response_delivery_allowed("a")
        await session.send(ObserveAssistantYielded(context=replace(updated, response_id="a")))
        await stop(session, updated)
        await take(stream, AsrCommitRequested)
        await final(session, updated, "不是，上海")
        second = await take(stream, UserTurnCommitted)
        assert second.text == "查北京天气\n不是，上海"
        assert second.input_id == first.input_id
        assert (first.input_version, second.input_version) == (1, 2)
        assert second.context.turn_id != first.context.turn_id
        assert second.context.generation == first.context.generation + 1
        await session.send(ObserveSystemResponseStarted(response_id="b", context=second.context, preparing=True))
        assert session.response_revision("b").supersedes_response_id == "a"
    finally:
        await session.close()
    evidence = await read_input_evidence(journal, context())
    events = [record["detail"]["event"] for record in evidence["records"]]
    assert "input_committed" in events
    assert "reply_bound" in events
    assert "reply_invalidated" in events
    commits = [record["detail"] for record in evidence["records"]
               if record["detail"]["event"] == "input_committed"]
    assert commits[0]["logical_input_id"] == commits[1]["logical_input_id"] == first.input_id
    assert commits[0]["input_id"] != commits[1]["input_id"]
    assert commits[1]["input_revision"]["turn_id"] == second.context.turn_id
    assert commits[1]["input_revision"]["generation"] == second.context.generation


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["bound", "invalidated"])
async def test_revision_evidence_queue_full_is_a_sticky_failure(operation):
    class GatedJournal(InMemoryConversationJournal):
        blocked = False

        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()

        async def append(self, draft, **kwargs):
            if self.blocked:
                await self.release.wait()
            return await super().append(draft, **kwargs)

    journal = GatedJournal()
    session = await CoordinatedTurnManagerCapabilityAdapter(
        TurnPolicy, input_evidence_journal=journal,
    ).open(context=context())
    stream = session.events()
    try:
        if operation == "invalidated":
            await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
            async with asyncio.timeout(.5):
                while session._evidence._pending:
                    await asyncio.sleep(.001)
        journal.blocked = True
        for index in range(32):
            session._evidence.offer("filler", "filler", {"index": index})
        assert session._evidence.failure is None
        if operation == "bound":
            await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        else:
            await session.invalidate_response("a", context=context(), reason="cancelled")
        assert not session.response_delivery_allowed("a")
        rejected = await take(stream, SemanticInputRejected)
        assert rejected.reason == "input_evidence_unavailable"
        assert not rejected.evidence_saved
        assert session._evidence_fault_reported
    finally:
        journal.release.set()
        await session.close()


@pytest.mark.asyncio
async def test_recovery_admission_preserves_original_model_decision():
    class Incomplete(Endpoint):
        async def classify_request(self, request):
            return EotClassification(EotDecision.INCOMPLETE, source="model", confidence=.8)

    session = await CoordinatedTurnManagerCapabilityAdapter(
        TurnPolicy, eot_classifier=Incomplete(), incomplete_timeout_ms=1000,
        recovery_timeout_ms=25,
    ).open(context=context())
    stream = session.events()
    try:
        await start(session)
        await text(session, "我想问一下")
        await stop(session)
        await take(stream, AsrCommitRequested)
        await final(session, context(), "我想问一下")
        committed = await take(stream, UserTurnCommitted)
        assert committed.endpoint_decision == "incomplete"
        assert committed.endpoint_source == "model"
        assert committed.admission_reason == "recovery_deadline"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_unresolved_overlap_deadline_reports_failure_instead_of_silent_discard():
    session = await CoordinatedTurnManagerCapabilityAdapter(
        TurnPolicy, semantic_interruption_classifier=Interrupt(InterruptionLabel.UNCERTAIN),
        recovery_timeout_ms=25,
    ).open(context=context())
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await start(session)
        await text(session, "还有明天的天气呢")
        await stop(session)
        rejected = await take(stream, SemanticInputRejected)
        assert rejected.reason == "unresolved_overlap_deadline"
        assert not rejected.evidence_saved
        assert session._input.rejected_text == "还有明天的天气呢"
    finally:
        await session.close()
