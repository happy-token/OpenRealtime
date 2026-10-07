"""Fresh ASR proof and confirmed stop are prerequisites, never playback authority."""

from dataclasses import replace

import pytest

from server.realtime.capabilities.reply_revision_controller import ReplyRevisionController
from server.realtime.protocol.playback import ReplyPlayback
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionCandidate,
    InterruptionClassification,
    InterruptionLabel,
    InterruptionVerdict,
)
from tests.realtime.test_output_stop_storage import confirmed, requested
from tests.realtime.test_realtime_websocket_bridge import context


def feedback(text="嗯好的", revision=2, *, label=InterruptionLabel.BACKCHANNEL, source="rule", confidence=1,
             boundary=InterruptionBoundary.SENTENCE_END, generation=2):
    return InterruptionVerdict(InterruptionCandidate(text, generation, revision, boundary),
        InterruptionClassification(label, confidence), source)


def locked():
    revisions = ReplyRevisionController()
    owner = replace(context(), response_id="a")
    overlap = replace(context(), turn_id="overlap", generation=2)
    revisions.commit_input(input_id="original-input", context=owner, text="说两句", transcript_revision=1,
        continuation_of_turn_id=None, admission_reason="semantic_complete")
    revisions.bind_response("a", owner)
    assert revisions.lock_interruption_recovery("a", overlap, observation_id="overlap-input", revision=1,
        text="等一下换个问题", stopping_text="等一下换个问题", deadline_ns=1000)
    revisions.revoke("a", reason="barge_in_floor_claim")
    revisions.observe_output_stop(replace(requested(), context=owner, operation_sequence=1))
    return revisions, owner, overlap


def rewrite(revisions, overlap, *, text="嗯好的", revision=2, verdict=None, speech_ended=True, answering_question=False):
    revisions.observe_interruption_revision(overlap, observation_id="overlap-input", revision=revision, text=text)
    return revisions.observe_recovery_feedback(overlap, observation_id="overlap-input", text=text, revision=revision,
        verdict=verdict or feedback(text, revision), speech_ended=speech_ended,
        answering_question=answering_question, confidence_threshold=.8)


def physically_stopped(revisions, owner, *, precision="sample", position=1200):
    revisions.observe_output_stop(confirmed(replace(requested(), context=owner, operation_sequence=1)))
    revisions.observe_playback_fact("a", owner, ReplyPlayback(output_epoch="epoch", speech_id="response:a",
        played_audio_end_us=position * 1000 if position is not None else 1200000, confirmed_text_end=4, observed_at_ns=50, position_precision=precision,
        played_position_samples=position, sample_rate_hz=1000 if position is not None else None, terminal=True))


def test_plan_requires_saved_stop_and_playback_projection_without_reauthorizing_output():
    revisions, owner, overlap = locked()
    assert rewrite(revisions, overlap)
    assert revisions.plan_misinterruption_recovery(now_ns=100) is None
    revisions.observe_output_stop(confirmed(replace(requested(), context=owner, operation_sequence=1)))
    assert revisions.plan_misinterruption_recovery(now_ns=100) is None
    physically_stopped(revisions, owner)
    plan = revisions.plan_misinterruption_recovery(now_ns=100)
    assert plan is not None
    assert plan.predecessor_response_id == "a" and plan.input_id == "original-input" and plan.input_version == 1
    assert plan.predecessor_reply_version == 1 and plan.stop_command_id == "stop-1"
    assert plan.source_context == owner and plan.trigger_context == overlap
    assert plan.strategy == "regenerate_continuation" and plan.position_precision == "sample"
    assert plan.confirmed_text_end == 4 and plan.played_position_samples == 1200
    assert plan.response_context.generation == 3 and plan.response_context.turn_id == owner.turn_id
    assert plan.response_context.response_id != owner.response_id and plan.output_epoch != "epoch"
    assert revisions.recovery_plan_current(plan, now_ns=100)
    assert revisions.plan_misinterruption_recovery(now_ns=101) is None, "one plan per unchanged evidence"
    assert not revisions.reply.delivery_permitted and revisions.reply.context_repair_permit is None
    assert revisions.reply.playback.played_position_samples == 1200


@pytest.mark.parametrize("precision,position", [("unknown", None), ("sample", 1300)])
def test_confirmed_stop_with_uncertain_position_plans_explicit_continuation(precision, position):
    revisions, owner, overlap = locked()
    rewrite(revisions, overlap)
    physically_stopped(revisions, owner, precision=precision, position=position)
    plan = revisions.plan_misinterruption_recovery(now_ns=100)
    assert plan.strategy == "regenerate_continuation"
    assert plan.position_precision == "unknown" and plan.played_position_samples is None and plan.sample_rate_hz is None
    assert plan.confirmed_text_end == 4 and not revisions.reply.delivery_permitted


@pytest.mark.parametrize("text,revision,verdict", [
    ("等一下换个问题", 1, feedback("等一下换个问题", 1)),
    ("等一下换个问题。", 2, feedback("等一下换个问题。")),
    ("等一下换个问题嗯好的", 2, feedback("等一下换个问题嗯好的")),
    ("嗯好的", 2, feedback(source="fallback")),
    ("嗯好的", 2, feedback(confidence=.79)),
    ("嗯好的", 2, feedback(boundary=InterruptionBoundary.PARTIAL)),
    ("嗯好的", 2, feedback("嗯")),
    ("嗯好的", 2, feedback(generation=1)),
    ("嗯好的", 2, feedback(label=InterruptionLabel.UNCERTAIN)),
    ("嗯好的", 2, feedback(label=InterruptionLabel.CORRECTION)),
])
def test_same_batch_append_equivalence_partial_fallback_and_uncertain_cannot_plan(text, revision, verdict):
    revisions, owner, overlap = locked()
    assert not rewrite(revisions, overlap, text=text, revision=revision, verdict=verdict)
    physically_stopped(revisions, owner)
    assert revisions.plan_misinterruption_recovery(now_ns=100) is None


@pytest.mark.parametrize("speech_ended,answering_question", [(False, False), (True, True)])
def test_active_speech_and_actual_question_answer_are_not_recovery_feedback(speech_ended, answering_question):
    revisions, owner, overlap = locked()
    assert not rewrite(revisions, overlap, speech_ended=speech_ended, answering_question=answering_question)
    physically_stopped(revisions, owner)
    assert revisions.plan_misinterruption_recovery(now_ns=100) is None


@pytest.mark.parametrize("change", ["scope", "lease", "observation"])
def test_rewrite_from_another_input_cannot_supply_recovery_proof(change):
    revisions, owner, overlap = locked()
    supplied = replace(overlap, user_id="other") if change == "scope" else replace(overlap, turn_id="other") if change == "lease" else overlap
    observation = "other" if change == "observation" else "overlap-input"
    assert not revisions.observe_interruption_revision(supplied, observation_id=observation, revision=2, text="嗯好的")
    assert not revisions.observe_recovery_feedback(supplied, observation_id=observation, revision=2, text="嗯好的",
        verdict=feedback(), speech_ended=True, answering_question=False, confidence_threshold=.8)
    physically_stopped(revisions, owner)
    assert revisions.plan_misinterruption_recovery(now_ns=100) is None


def test_asr_reversion_and_later_revision_do_not_revive_old_plans():
    revisions, owner, overlap = locked()
    rewrite(revisions, overlap)
    physically_stopped(revisions, owner)
    plan = revisions.plan_misinterruption_recovery(now_ns=100)
    revisions.observe_interruption_revision(overlap, observation_id="overlap-input", revision=3, text="等一下换个问题")
    assert not revisions.recovery_plan_current(plan, now_ns=101)
    revisions.observe_interruption_revision(overlap, observation_id="overlap-input", revision=4, text="嗯好的")
    assert revisions.plan_misinterruption_recovery(now_ns=101) is None
    assert not revisions.recovery_plan_current(plan, now_ns=101)


@pytest.mark.parametrize("termination", ["unknown_stop", "new_stop", "semantic_stop", "new_input", "new_reply", "close", "deadline"])
def test_plans_are_fenced_by_stop_operation_versions_input_reply_and_absolute_deadline(termination):
    revisions, owner, overlap = locked()
    rewrite(revisions, overlap)
    if termination == "unknown_stop":
        revisions.observe_output_stop(replace(requested(), context=owner, operation_sequence=1,
            state="STOP_UNKNOWN", failure_reason="receipt_deadline"))
        assert revisions.plan_misinterruption_recovery(now_ns=100) is None
        return
    physically_stopped(revisions, owner)
    plan = revisions.plan_misinterruption_recovery(now_ns=100)
    if termination == "new_stop":
        revisions.observe_output_stop(replace(requested(), context=owner, operation_sequence=2, stop_command_id="stop-2"))
    elif termination == "semantic_stop":
        revisions.revoke("a", reason="semantic_stop")
    elif termination == "new_input":
        revisions.commit_input(input_id="new", context=overlap, text="新问题", transcript_revision=3,
            continuation_of_turn_id=None, admission_reason="semantic_complete")
    elif termination == "new_reply":
        revisions.bind_response("b", owner)
    elif termination == "close":
        revisions.close()
    assert not revisions.recovery_plan_current(plan, now_ns=1000 if termination == "deadline" else 101)
    assert revisions.plan_misinterruption_recovery(now_ns=1000 if termination == "deadline" else 101) is None


def test_repeated_lock_and_asr_progress_cannot_extend_recovery_deadline():
    revisions, owner, overlap = locked()
    assert not revisions.lock_interruption_recovery("a", overlap, observation_id="overlap-input", revision=1,
        text="等一下换个问题", stopping_text="等一下换个问题", deadline_ns=9000)
    rewrite(revisions, overlap)
    physically_stopped(revisions, owner)
    assert revisions.plan_misinterruption_recovery(now_ns=1000) is None


@pytest.mark.parametrize("facts_first", [False, True])
@pytest.mark.parametrize("chunks", [False, True])
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_actual_actor_records_fresh_recovery_plan_after_both_fact_orders(facts_first, chunks, concurrency):
    from server.conversation_journal import InMemoryConversationJournal
    from server.conversation_journal.input_evidence import read_input_evidence
    from server.realtime.capabilities.turn_manager import (
        AsrCommitRequested,
        AsrDiscardRequested,
        AssistantYieldRequested,
        ObserveAssistantOutputStop,
        ObserveAssistantPlayback,
        ObserveAssistantYielded,
        ObserveSystemResponseStarted,
        UserTurnCommitted,
    )
    from tests.realtime.test_coordinated_turn_manager import (
        Endpoint,
        opened,
        start,
        stop,
        take,
        text,
    )
    from tests.realtime.test_reply_revision_coordination import final

    journal = InMemoryConversationJournal()
    actor = await opened(eot_classifier=Endpoint(), input_evidence_journal=journal,
        semantic_chunks_enabled=chunks, semantic_chunk_concurrency=concurrency)
    stream = actor.events()
    owner = replace(actor._context, response_id="a")
    overlap = replace(owner, turn_id="overlap", generation=owner.generation + 1, response_id=None)
    try:
        await start(actor, owner)
        await text(actor, "说两句", ctx=owner)
        await stop(actor, owner)
        await take(stream, AsrCommitRequested)
        await final(actor, owner, "说两句")
        root = await take(stream, UserTurnCommitted)
        await actor.send(ObserveSystemResponseStarted(response_id="a", context=owner))
        await actor.send(ObserveAssistantPlayback(context=owner, response_id="a", fact=ReplyPlayback(
            output_epoch="epoch", speech_id="response:a", played_audio_end_us=500000, confirmed_text_end=0,
            observed_at_ns=50, position_precision="sample", played_position_samples=500, sample_rate_hz=1000)))
        await start(actor, overlap)
        await text(actor, "等一下换个问题", ctx=overlap)
        await take(stream, AssistantYieldRequested)
        await actor.send(ObserveAssistantYielded(context=replace(overlap, response_id="a")))
        fact = confirmed(replace(requested(), context=owner, operation_sequence=1))

        async def stopped():
            await actor.send(ObserveAssistantOutputStop(fact=fact))
            await actor.send(ObserveAssistantPlayback(context=owner, response_id="a", fact=ReplyPlayback(
                output_epoch="epoch", speech_id="response:a", played_audio_end_us=1200000, confirmed_text_end=4,
                observed_at_ns=100, position_precision="sample", played_position_samples=1200, sample_rate_hz=1000, terminal=True)))

        if facts_first:
            await stopped()
        await text(actor, "好的", revision=2, ctx=overlap)
        await stop(actor, overlap)
        await take(stream, AsrDiscardRequested)
        if not facts_first:
            await stopped()
        plan = actor._revisions._recovery_plan
        assert plan is not None, "fresh rewritten feedback needs an actionable plan, not just silent discard"
        assert plan.input_id == root.input_id and plan.input_version == root.input_version
        assert plan.predecessor_response_id == "a" and plan.transcript_revision == 2
        assert not actor.response_delivery_allowed("a")
        assert actor._revisions.reply.response_id == "a", "planning cannot restore or bind a reply"
    finally:
        await actor.close()
    evidence = await read_input_evidence(journal, owner)
    plans = [row["detail"] for row in evidence["records"] if row["detail"]["event"] == "reply_recovery_planned"]
    assert len(plans) == 1 and plans[0]["plan_id"] == plan.plan_id


@pytest.mark.parametrize("changes", [
    {"output_epoch": "epoch"}, {"input_version": 0}, {"deadline_ns": True}, {"feedback_source": "fallback"},
    {"feedback_confidence": float("nan")}, {"position_precision": "unknown"}, {"strategy": "blind_resume"},
    {"response_context": replace(context(), response_id="a")},
    {"trigger_context": replace(context(), user_id="other")},
])
def test_recovery_plan_contract_rejects_invalid_or_fabricated_evidence(changes):
    revisions, owner, overlap = locked()
    rewrite(revisions, overlap)
    physically_stopped(revisions, owner)
    plan = revisions.plan_misinterruption_recovery(now_ns=100)
    with pytest.raises(ValueError):
        replace(plan, **changes)


def test_reused_asr_revision_with_different_text_invalidates_recovery_order():
    revisions, owner, overlap = locked()
    rewrite(revisions, overlap)
    physically_stopped(revisions, owner)
    plan = revisions.plan_misinterruption_recovery(now_ns=100)
    assert not revisions.observe_interruption_revision(overlap, observation_id="overlap-input", revision=2, text="别说了")
    assert not revisions.recovery_plan_current(plan, now_ns=101)
    assert revisions.plan_misinterruption_recovery(now_ns=101) is None


@pytest.mark.parametrize("label", [InterruptionLabel.INTERRUPT, InterruptionLabel.CORRECTION, InterruptionLabel.STOP, InterruptionLabel.UNCERTAIN])
def test_current_complete_opposite_feedback_invalidates_unconsumed_plan(label):
    revisions, owner, overlap = locked()
    assert rewrite(revisions, overlap, verdict=feedback(source="model"))
    physically_stopped(revisions, owner)
    plan = revisions.plan_misinterruption_recovery(now_ns=100)
    assert revisions.recovery_plan_current(plan, now_ns=100)
    assert not revisions.observe_recovery_feedback(overlap, observation_id="overlap-input", revision=2, text="嗯好的",
        verdict=feedback(label=label, source="model"), speech_ended=True, answering_question=False, confidence_threshold=.8)
    assert not revisions.recovery_plan_current(plan, now_ns=101)
    assert revisions.plan_misinterruption_recovery(now_ns=101) is None
    assert not revisions.reply.delivery_permitted


@pytest.mark.parametrize("verdict", [feedback(label=InterruptionLabel.INTERRUPT, revision=1),
    feedback(label=InterruptionLabel.INTERRUPT, boundary=InterruptionBoundary.PARTIAL),
    feedback(label=InterruptionLabel.INTERRUPT, generation=1),
    feedback(label=InterruptionLabel.INTERRUPT, confidence=.79),
    feedback(label=InterruptionLabel.INTERRUPT, source="fallback")])
def test_old_partial_foreign_or_unreliable_opposite_feedback_cannot_invalidate_current_plan(verdict):
    revisions, owner, overlap = locked()
    rewrite(revisions, overlap)
    physically_stopped(revisions, owner)
    plan = revisions.plan_misinterruption_recovery(now_ns=100)
    assert not revisions.observe_recovery_feedback(overlap, observation_id="overlap-input", revision=2, text="嗯好的",
        verdict=verdict, speech_ended=True, answering_question=False, confidence_threshold=.8)
    assert revisions.recovery_plan_current(plan, now_ns=101)
