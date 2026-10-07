"""Fresh ASR proof and confirmed stop are prerequisites, never playback authority."""

import asyncio
from contextlib import asynccontextmanager
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


@pytest.mark.parametrize("chunks", [False, True])
@pytest.mark.parametrize("concurrency", [1, 2])
@pytest.mark.parametrize("label,confidence,fail,question", [
    (InterruptionLabel.BACKCHANNEL, 1, False, False), (InterruptionLabel.IGNORE, 1, False, False),
    (InterruptionLabel.INTERRUPT, 1, False, False), (InterruptionLabel.CORRECTION, 1, False, False),
    (InterruptionLabel.STOP, 1, False, False), (InterruptionLabel.UNCERTAIN, 1, False, False),
    (InterruptionLabel.BACKCHANNEL, .1, False, False), (InterruptionLabel.BACKCHANNEL, 1, True, False),
    (InterruptionLabel.BACKCHANNEL, 1, False, True),
])
async def test_actual_actor_uses_one_fresh_full_model_review_after_material_rewrite(chunks, concurrency, label, confidence, fail, question):
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

    class Model:
        def __init__(self):
            self.requests = []

        async def classify_request(self, request):
            self.requests.append(request)
            if request.transcript == "我只是随口附和":
                if fail:
                    raise RuntimeError("provider failed")
                return InterruptionClassification(label, confidence)
            return InterruptionClassification(InterruptionLabel.INTERRUPT, 1)

    model = Model()
    actor = await opened(eot_classifier=Endpoint(), semantic_interruption_classifier=model,
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
        await take(stream, UserTurnCommitted)
        await actor.send(ObserveSystemResponseStarted(response_id="a", context=owner))
        await actor.send(ObserveAssistantPlayback(context=owner, response_id="a", fact=ReplyPlayback(
            output_epoch="epoch", speech_id="response:a", played_audio_end_us=500000, confirmed_text_end=0,
            observed_at_ns=50, position_precision="sample", played_position_samples=500, sample_rate_hz=1000)))
        await start(actor, overlap)
        await text(actor, "等一下换个问题", ctx=overlap)
        await take(stream, AssistantYieldRequested)
        await actor.send(ObserveAssistantYielded(context=replace(overlap, response_id="a")))
        await actor.send(ObserveAssistantOutputStop(fact=confirmed(replace(requested(), context=owner, operation_sequence=1))))
        await actor.send(ObserveAssistantPlayback(context=owner, response_id="a", fact=ReplyPlayback(
            output_epoch="epoch", speech_id="response:a", played_audio_end_us=1200000, confirmed_text_end=4,
            observed_at_ns=100, position_precision="sample", played_position_samples=1200, sample_rate_hz=1000, terminal=True)))
        if question:
            actor._input.assistant_text_at_onset = "你同意吗？"
        calls_before_rewrite = len(model.requests)
        await text(actor, "我只是", revision=2, ctx=overlap)
        await text(actor, "我只是随口", revision=3, ctx=overlap)
        await text(actor, "我只是随口附和", revision=4, ctx=overlap)
        assert len(model.requests) == calls_before_rewrite, "rewritten partials cannot each call the model"
        await stop(actor, overlap)
        recovery = label in {InterruptionLabel.BACKCHANNEL, InterruptionLabel.IGNORE} and confidence == 1 and not fail and not question
        control_stop = label is InterruptionLabel.STOP and confidence == 1 and not fail
        await take(stream, AsrDiscardRequested if recovery or control_stop else AsrCommitRequested)
        reviews = [r for r in model.requests if r.transcript == "我只是随口附和"]
        assert len(reviews) == 1, "one independent sealed full-text review, separate from locked old STOP"
        assert reviews[0].boundary is InterruptionBoundary.SENTENCE_END
        assert reviews[0].input_state.transcript_revision == 4
        assert reviews[0].input_state.speech_active is False
        plan = actor._revisions._recovery_plan
        if recovery:
            assert plan is not None and plan.feedback_source == "model" and plan.transcript_revision == 4
        else:
            assert plan is None
            assert actor.snapshot().commit_pending is not control_stop
        assert not actor.response_delivery_allowed("a"), "feedback does not restore the old reply"
    finally:
        await actor.close()
        await stream.aclose()


@asynccontextmanager
async def recoverable_actor(model, *, concurrency=2, confirm_yield=True):
    from server.realtime.capabilities.turn_manager import (
        AsrCommitRequested,
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

    actor = await opened(eot_classifier=Endpoint(), semantic_interruption_classifier=model,
        semantic_chunks_enabled=True, semantic_chunk_concurrency=concurrency)
    stream = actor.events()
    owner = replace(actor._context, response_id="a")
    overlap = replace(owner, turn_id="overlap", generation=owner.generation + 1, response_id=None)
    try:
        await start(actor, owner)
        await text(actor, "说两句", ctx=owner)
        await stop(actor, owner)
        await take(stream, AsrCommitRequested)
        await final(actor, owner, "说两句")
        await take(stream, UserTurnCommitted)
        await actor.send(ObserveSystemResponseStarted(response_id="a", context=owner))
        await actor.send(ObserveAssistantPlayback(context=owner, response_id="a", fact=ReplyPlayback(
            output_epoch="epoch", speech_id="response:a", played_audio_end_us=500000, confirmed_text_end=0,
            observed_at_ns=50, position_precision="sample", played_position_samples=500, sample_rate_hz=1000)))
        await start(actor, overlap)
        await text(actor, "等一下换个问题", ctx=overlap)
        await take(stream, AssistantYieldRequested)
        if confirm_yield:
            await actor.send(ObserveAssistantYielded(context=replace(overlap, response_id="a")))
        await actor.send(ObserveAssistantOutputStop(fact=confirmed(replace(requested(), context=owner, operation_sequence=1))))
        await actor.send(ObserveAssistantPlayback(context=owner, response_id="a", fact=ReplyPlayback(
            output_epoch="epoch", speech_id="response:a", played_audio_end_us=1200000, confirmed_text_end=4,
            observed_at_ns=100, position_precision="sample", played_position_samples=1200, sample_rate_hz=1000, terminal=True)))
        yield actor, stream, owner, overlap
    finally:
        await actor.close()
        await stream.aclose()


class HeldRecoveryModel:
    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.requests = []

    async def classify_request(self, request):
        self.requests.append(request)
        if request.transcript != "我只是随口附和":
            return InterruptionClassification(InterruptionLabel.INTERRUPT, 1)
        self.started.set()
        try:
            while not self.release.is_set():
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.cancelled.set()  # Deliberately noncooperative provider stays owned.
            return InterruptionClassification(InterruptionLabel.BACKCHANNEL, 1)
        finally:
            self.finished.set()


@pytest.mark.parametrize("termination", ["rewrite", "speech", "reply", "close", "deadline"])
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_actual_actor_bounds_recovery_review_and_fences_late_noncooperative_model(termination, concurrency):
    from server.realtime.capabilities.turn_manager import (
        AsrCommitRequested,
        ObserveSystemResponseStarted,
    )
    from tests.realtime.test_coordinated_turn_manager import start, stop, take, text

    model = HeldRecoveryModel()
    try:
        async with recoverable_actor(model, concurrency=concurrency) as (actor, stream, owner, overlap):
            await text(actor, "我只是随口附和", revision=2, ctx=overlap)
            anchor = actor._revisions._interruption_recovery
            original_deadline = anchor.deadline_ns
            await stop(actor, overlap)
            await asyncio.wait_for(model.started.wait(), .5)
            assert not actor.snapshot().commit_pending
            if termination == "rewrite":
                await text(actor, "现在问北京天气", revision=3, ctx=overlap)
                await take(stream, AsrCommitRequested)
            elif termination == "speech":
                await start(actor, overlap)
                assert actor._revisions._interruption_recovery is None
                assert not actor.snapshot().commit_pending
            elif termination == "reply":
                await actor.send(ObserveSystemResponseStarted(response_id="b",
                    context=replace(owner, response_id="b", generation=overlap.generation + 1)))
            elif termination == "close":
                await asyncio.wait_for(actor.close(), .5)
                assert actor._classifier_executor.pending_count == 1, "uncooperative child stays quarantined until exit"
            else:
                await take(stream, AsrCommitRequested)
                assert anchor.deadline_ns == original_deadline
                assert actor._revisions._recovery_plan is None
            await asyncio.wait_for(model.cancelled.wait(), .5)
            assert actor._revisions._recovery_plan is None
            model.release.set()
            await asyncio.wait_for(model.finished.wait(), .5)
            assert actor._revisions._recovery_plan is None, "late success cannot revive any plan"
    finally:
        model.release.set()
        if model.started.is_set():
            await asyncio.wait_for(model.finished.wait(), .5)


@pytest.mark.parametrize("seal", ["endpoint", "idle"])
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_vad_stop_before_asr_tail_waits_for_endpoint_or_stable_idle_seal(seal, concurrency):
    from server.realtime.capabilities.asr import AsrEndpointHint
    from server.realtime.capabilities.turn_manager import (
        AsrDiscardRequested,
        ObserveAsrEvent,
        ObserveAssistantYielded,
    )
    from tests.realtime.test_coordinated_turn_manager import stop, take, text

    class TailModel:
        def __init__(self):
            self.requests = []
            self.release = asyncio.Event()

        async def classify_request(self, request):
            self.requests.append(request)
            if not request.transcript.startswith("我只是"):
                return InterruptionClassification(InterruptionLabel.INTERRUPT, 1)
            await self.release.wait()
            return InterruptionClassification(InterruptionLabel.BACKCHANNEL, 1)

    model = TailModel()
    async with recoverable_actor(model, concurrency=concurrency, confirm_yield=False) as (actor, stream, _owner, overlap):
        actor._provider._asr_idle_stop_s = .03
        await stop(actor, overlap)
        initial_calls = len(model.requests)
        for revision, transcript in enumerate(["我只是", "我只是随口", "我只是随口附和"], start=2):
            await text(actor, transcript, revision=revision, ctx=overlap)
            if revision == 2:
                await actor.send(ObserveAssistantYielded(context=replace(overlap, response_id="a")))
            for _ in range(8):
                await asyncio.sleep(0)
            assert len(model.requests) == initial_calls, "acoustic stop cannot seal each trailing partial"
        if seal == "endpoint":
            await actor.send(ObserveAsrEvent(event=AsrEndpointHint(context=overlap, revision=4, text="我只是随口附和")))
        model.release.set()
        await take(stream, AsrDiscardRequested)
        reviews = model.requests[initial_calls:]
        assert len(reviews) == 1 and reviews[0].transcript == "我只是随口附和"
        assert reviews[0].boundary is InterruptionBoundary.SENTENCE_END
        assert actor._revisions._recovery_plan is not None
