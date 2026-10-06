"""Association must follow final semantic evidence, not playback timing alone."""

from dataclasses import replace

import pytest

from server.conversation_journal import InMemoryConversationJournal
from server.conversation_journal.input_evidence import InputEvidenceUnavailable, read_input_evidence
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    AssistantYieldRequested,
    ObserveAssistantSpokenText,
    ObserveAssistantYielded,
    ObserveSystemResponseCompleted,
    ObserveSystemResponseStarted,
    SemanticInputRejected,
    UserTurnCommitted,
)
from server.turn_policy.input_association import (
    ConservativeInputAssociationPolicy,
    InputAssociation,
    InputRelation,
)
from server.turn_policy.semantic_interruption import InterruptionLabel
from tests.realtime.test_coordinated_turn_manager import (
    Endpoint,
    Interrupt,
    context,
    opened,
    start,
    stop,
    take,
    text,
)
from tests.realtime.test_reply_revision_coordination import final


async def first_input(session, stream):
    await start(session)
    await text(session, "查北京天气")
    await stop(session)
    await take(stream, AsrCommitRequested)
    await final(session, context(), "查北京天气")
    return await take(stream, UserTurnCommitted)


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks", [False, True])
async def test_explicit_new_topic_does_not_merge_even_before_audio(chunks):
    session = await opened(eot_classifier=Endpoint(), semantic_chunks_enabled=chunks)
    stream = session.events()
    next_context = replace(context(), turn_id="next", generation=context().generation + 1)
    try:
        first = await first_input(session, stream)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context(), preparing=True))
        await start(session, next_context)
        await text(session, "换个问题，帮我查日期。", ctx=next_context)
        await stop(session, next_context)
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantYielded(context=replace(next_context, response_id="a")))
        await take(stream, AsrCommitRequested)
        await final(session, next_context, "换个问题，帮我查日期。")
        committed = await take(stream, UserTurnCommitted)
        assert committed.text == "换个问题，帮我查日期。"
        assert committed.continuation_of_turn_id is None
        assert committed.input_id != first.input_id
        assert committed.input_version == 1
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("final_text", "relation", "merged"), [
    ("上海才对。", "correction", True),
    ("换个问题，查日期。", "new_topic", False),
    ("上海的日期", "unresolved", False),
])
async def test_locked_prefix_correction_is_rechecked_against_final_asr(final_text, relation, merged):
    session = await opened(eot_classifier=Endpoint(),
                           semantic_interruption_classifier=Interrupt(InterruptionLabel.CORRECTION))
    stream = session.events()
    next_context = replace(context(), turn_id="next", generation=context().generation + 1)
    try:
        first = await first_input(session, stream)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context(), preparing=True))
        await start(session, next_context)
        await text(session, "上海才对", ctx=next_context)
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantYielded(context=replace(next_context, response_id="a")))
        await stop(session, next_context)
        await take(stream, AsrCommitRequested)
        await final(session, next_context, final_text)
        committed = await take(stream, UserTurnCommitted)
        assert committed.input_relation == relation
        assert committed.text == ("查北京天气\n" + final_text if merged else final_text)
        assert (committed.input_id == first.input_id) is merged
        if relation == "unresolved":
            assert committed.related_turn_id == first.context.turn_id
            assert committed.input_relation_source == "insufficient_evidence"
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "foreign_parent", "unsupported"])
async def test_association_plugin_failure_retains_final_input_and_records_fallback(failure):
    class FailingPolicy:
        def associate(self, request):
            if request.previous_turn_id is not None:
                if failure == "foreign_parent":
                    return InputAssociation(InputRelation.CORRECTION, "foreign-parent", "test")
                if failure == "unsupported":
                    return None
                raise RuntimeError("association failed")
            return ConservativeInputAssociationPolicy().associate(request)

    journal = InMemoryConversationJournal()
    session = await opened(eot_classifier=Endpoint(), input_association_policy=FailingPolicy(),
                           input_evidence_journal=journal)
    stream = session.events()
    next_context = replace(context(), turn_id="next", generation=context().generation + 1)
    try:
        await first_input(session, stream)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await session.send(ObserveSystemResponseCompleted(response_id="a", context=context()))
        assert session.response_delivery_allowed("a")
        await start(session, next_context)
        await text(session, "补充一下，明天", ctx=next_context)
        await stop(session, next_context)
        await take(stream, AsrCommitRequested)
        await final(session, next_context, "补充一下，后天才对")
        committed = await take(stream, UserTurnCommitted)
        assert committed.text == "补充一下，后天才对"
        assert committed.input_relation == "unresolved"
        assert committed.input_relation_source == "association_error"
        assert committed.related_turn_id == context().turn_id
        assert not session.response_delivery_allowed("a")
        assert not session._actor.done()
    finally:
        await session.close()
    evidence = await read_input_evidence(journal, context())
    details = [item["detail"] for item in evidence["records"]]
    assert any(detail["event"] == "asr_final" and detail["text"] == "补充一下，后天才对"
               for detail in details)
    assert any(detail["event"] == "input_associated" and detail["source"] == "association_error"
               for detail in details)


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["turn", "generation", "response"])
async def test_wrong_playback_identity_cannot_change_relation_or_assistant_context(identity):
    session = await opened()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        receipt = replace(context(), response_id="a")
        if identity == "turn":
            receipt = replace(receipt, turn_id="wrong-turn")
        elif identity == "generation":
            receipt = replace(receipt, generation=receipt.generation + 1)
        else:
            receipt = replace(receipt, response_id="wrong-response")
        await session.send(ObserveAssistantSpokenText(context=receipt, text="wrong playback", playback_started=True))
        assert not session.response_revision("a").playback_started
        assert session._assistant_text == ""
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["input_associated", "input_committed"])
async def test_final_evidence_failure_captures_final_cumulative_text_and_revision(monkeypatch, stage):
    journal = InMemoryConversationJournal()
    session = await opened(eot_classifier=Endpoint(), input_evidence_journal=journal)
    stream = session.events()
    next_context = replace(context(), turn_id="next", generation=context().generation + 1)
    try:
        await first_input(session, stream)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await session.send(ObserveSystemResponseCompleted(response_id="a", context=context()))
        offer = session._evidence.offer

        def fail_last(input_id, event, detail, **kwargs):
            if event == stage:
                raise InputEvidenceUnavailable("injected final step failure")
            return offer(input_id, event, detail, **kwargs)

        monkeypatch.setattr(session._evidence, "offer", fail_last)
        await start(session, next_context)
        await text(session, "补充一下，明天", ctx=next_context)
        await stop(session, next_context)
        await take(stream, AsrCommitRequested)
        from server.realtime.capabilities.asr import AsrTranscriptFinal
        from server.realtime.capabilities.turn_manager import ObserveAsrEvent
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(context=next_context, revision=2,
            text="补充一下，后天才对", reason="final")))
        assert session._input.rejected_text == "查北京天气\n补充一下，后天才对"
        await take(stream, SemanticInputRejected)
    finally:
        await session.close()
    evidence = await read_input_evidence(journal, context())
    terminal = next(item["detail"] for item in evidence["records"] if item["detail"]["event"] == "input_rejected")
    assert terminal["text"] == "查北京天气\n补充一下，后天才对"
    assert terminal["rejected_revision"] == 2
    assert terminal["capture_complete"]


@pytest.mark.asyncio
async def test_unrelated_unplayed_input_is_retained_without_automatic_concatenation():
    session = await opened(eot_classifier=Endpoint())
    stream = session.events()
    next_context = replace(context(), turn_id="next", generation=context().generation + 1)
    try:
        first = await first_input(session, stream)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context(), preparing=True))
        await start(session, next_context)
        await text(session, "帮我查今天的日期", ctx=next_context)
        await take(stream, AssistantYieldRequested)
        await session.send(ObserveAssistantYielded(context=replace(next_context, response_id="a")))
        await stop(session, next_context)
        await take(stream, AsrCommitRequested)
        await final(session, next_context, "帮我查今天的日期")
        committed = await take(stream, UserTurnCommitted)
        assert committed.text == "帮我查今天的日期"
        assert committed.continuation_of_turn_id is None
        assert committed.input_id != first.input_id
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("late_playback", [False, True])
async def test_explicit_correction_after_completed_playback_retains_logical_parent(late_playback):
    session = await opened(eot_classifier=Endpoint())
    stream = session.events()
    next_context = replace(context(), turn_id="next", generation=context().generation + 1)
    try:
        first = await first_input(session, stream)
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        if late_playback:
            await session.send(ObserveSystemResponseCompleted(response_id="a", context=context()))
        await session.send(ObserveAssistantSpokenText(context=replace(context(), response_id="a"),
                                                    text="北京今天晴。", playback_started=True))
        if not late_playback:
            await session.send(ObserveSystemResponseCompleted(response_id="a", context=context()))
        await start(session, next_context)
        await text(session, "不是，上海", ctx=next_context)
        await stop(session, next_context)
        await take(stream, AsrCommitRequested)
        await final(session, next_context, "不是，上海")
        committed = await take(stream, UserTurnCommitted)
        assert committed.text == "查北京天气\n不是，上海"
        assert committed.continuation_of_turn_id == first.context.turn_id
        assert committed.input_id == first.input_id
        assert committed.input_version == 2
        assert committed.input_relation == "correction"
        assert not committed.supersedes_unplayed_reply
    finally:
        await session.close()
