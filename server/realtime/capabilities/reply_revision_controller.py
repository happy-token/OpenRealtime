"""Actor-owned input/reply association; no I/O, timers or semantic decisions.

Generation remains the execution lease. This ledger retains only the current
input and reply; immutable history belongs to the conversation Journal.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, replace

from server.conversation_journal import (
    ConversationItem,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.core.playback import CurrentSentencePermit, sample_position_us
from server.core.reply_repair import MAX_CONTEXT_REPAIRS, ReplyRecoveryPlan, ReplyRepairPermit
from server.realtime.protocol.commands import OutputStopFact, transition_output_stop_fact
from server.realtime.protocol.playback import ReplyPlayback, sentence_identity
from server.realtime.scope import conversation_scope
from server.turn_policy.semantic_chunks import semantic_text
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionLabel,
    InterruptionVerdict,
)


@dataclass(frozen=True, slots=True)
class InputRevision:
    input_id: str
    observation_id: str
    input_version: int
    turn_id: str
    generation: int
    transcript_revision: int
    text_sha256: str
    admission_reason: str
    supersedes_turn_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReplyRevision:
    response_id: str
    turn_id: str
    generation: int
    input_id: str | None
    input_version: int | None
    reply_version: int
    supersedes_response_id: str | None = None
    delivery_permitted: bool = True
    playback_started: bool = False
    completed: bool = False
    invalidation_reason: str | None = None
    playback: ReplyPlayback | None = None
    sentence_permit: CurrentSentencePermit | None = None
    context_repair_attempt: int = 0
    context_repair_deadline_ns: int | None = None
    context_repair_permit: ReplyRepairPermit | None = None


@dataclass(slots=True)
class _InterruptionRecovery:
    response_id: str
    owner: InteractionContext
    input_id: str
    input_version: int
    reply_version: int
    overlap: InteractionContext
    observation_id: str
    stopping_revision: int
    stopping_text: str
    revision: int
    text: str
    deadline_ns: int
    feedback: InterruptionVerdict | None = None


class ReplyRevisionController:
    def __init__(self) -> None:
        self.input: InputRevision | None = None
        self.reply: ReplyRevision | None = None
        self._reply_context: InteractionContext | None = None
        self._sample_rate_hz: int | None = None
        self._output_stop: OutputStopFact | None = None
        self._interruption_recovery: _InterruptionRecovery | None = None
        self._recovery_plan: ReplyRecoveryPlan | None = None
        self._recovery_plan_basis: tuple[object, ...] | None = None
        self._closed = False
        self._live_started = False
        self._history_sequence = 0

    def restore_item(self, item: ConversationItem) -> bool:
        """Rebuild current identities during the Journal restoration barrier.

        Returns whether a user input was restored. No delivery permission,
        pending response or execution lease survives this barrier. Once live
        commits/bindings begin, their later Journal projections cannot roll
        back the actor's state. The caller enforces thread authorization.
        """
        if self._closed:
            raise RuntimeError("reply revision controller is closed")
        if self._live_started or item.sequence <= self._history_sequence:
            return False
        metadata = item.provider_metadata
        if item.kind is ConversationItemKind.USER_INPUT and item.status is ConversationItemStatus.COMPLETED:
            text = "\n".join(part.text for part in item.content if isinstance(part, TextContent))
            if not text.strip():
                self._history_sequence = item.sequence
                return False
            root = metadata.get("input_id")
            version = metadata.get("input_version")
            legacy = root is None and version is None
            if legacy:
                root, version = item.item_id, 1
            root = _identity(root, "input_id")
            version = _positive_integer(version, "input_version")
            observation_value = metadata.get("input_observation_id")
            observation = _identity(item.item_id if observation_value is None else observation_value, "observation_id")
            transcript = _positive_integer(metadata.get("transcript_revision", 1), "transcript_revision")
            reason_value = metadata.get("admission_reason")
            reason = _identity("journal_restore" if reason_value is None else reason_value, "admission_reason")
            parent = metadata.get("continuation_of_turn_id") if not legacy else None
            if parent is not None:
                parent = _identity(parent, "continuation_of_turn_id")
            previous = self.input
            if previous is not None and previous.input_id == root and (
                version <= previous.input_version or observation == previous.observation_id
            ):
                raise ValueError("restored input identity or version was reused")
            if version > 1 and (previous is None or previous.input_id != root
                    or previous.input_version + 1 != version or previous.turn_id != parent):
                raise ValueError("restored input continuation has no preceding version")
            if version == 1 and parent is not None:
                raise ValueError("restored first input version cannot have a continuation")
            self.input = InputRevision(
                input_id=root, observation_id=observation, input_version=version,
                turn_id=item.context.turn_id, generation=item.context.generation,
                transcript_revision=transcript, text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                admission_reason=reason, supersedes_turn_id=parent,
            )
            if self.reply is not None and self.reply.input_id != root:
                self.reply = None
            self._history_sequence = item.sequence
            return True
        if item.kind is ConversationItemKind.ASSISTANT_OUTPUT and metadata.get("reply_version") is not None:
            reply_version = _positive_integer(metadata["reply_version"], "reply_version")
            # Manual/external replies can carry a reply version without an
            # ASR input identity. They belong in history, not this input chain.
            if metadata.get("input_id") is None and metadata.get("input_version") is None:
                self._history_sequence = item.sequence
                return False
            root = _identity(metadata.get("input_id"), "input_id")
            version = _positive_integer(metadata.get("input_version"), "input_version")
            response_id = _identity(metadata.get("response_id"), "response_id")
            if item.context.response_id != response_id:
                raise ValueError("restored reply context and response identity disagree")
            if self.input is not None and self.input.input_id == root:
                if version > self.input.input_version:
                    raise ValueError("restored reply refers to a future input version")
                if version == self.input.input_version and (
                    item.context.turn_id, item.context.generation
                ) != (self.input.turn_id, self.input.generation):
                    raise ValueError("restored reply belongs to a different input context")
                predecessor = metadata.get("supersedes_response_id")
                if predecessor is not None:
                    predecessor = _identity(predecessor, "supersedes_response_id")
                if self.reply is None or reply_version > self.reply.reply_version:
                    self.reply = ReplyRevision(
                        response_id=response_id, turn_id=item.context.turn_id, generation=item.context.generation,
                        input_id=root, input_version=version, reply_version=reply_version,
                        supersedes_response_id=predecessor, delivery_permitted=False,
                        completed=True, invalidation_reason="journal_restored",
                    )
        self._history_sequence = item.sequence
        return False

    def commit_input(
        self, *, input_id: str, context: InteractionContext, text: str,
        transcript_revision: int, continuation_of_turn_id: str | None,
        admission_reason: str,
    ) -> InputRevision:
        if self._closed:
            raise RuntimeError("reply revision controller is closed")
        if not input_id or not text or transcript_revision < 1 or not admission_reason:
            raise ValueError("input revision requires identity, text, revision and admission reason")
        previous = self.input
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if previous is not None and previous.observation_id == input_id:
            if (previous.turn_id, previous.generation, previous.text_sha256,
                previous.transcript_revision, previous.admission_reason,
                previous.supersedes_turn_id) != (
                    context.turn_id, context.generation, digest, transcript_revision,
                    admission_reason, continuation_of_turn_id):
                raise ValueError("input observation identity was reused with different content")
            return previous
        if continuation_of_turn_id is not None and (
            previous is None or previous.turn_id != continuation_of_turn_id
        ):
            raise ValueError("input continuation has no current parent")
        self._live_started = True
        parent = previous if continuation_of_turn_id is not None else None
        self.input = InputRevision(
            input_id=parent.input_id if parent is not None else input_id,
            observation_id=input_id,
            input_version=parent.input_version + 1 if parent is not None else 1,
            turn_id=context.turn_id, generation=context.generation,
            transcript_revision=transcript_revision, text_sha256=digest,
            admission_reason=admission_reason, supersedes_turn_id=continuation_of_turn_id,
        )
        if self.reply is not None:
            self.revoke(self.reply.response_id, reason="input_replaced")
        return self.input

    def bind_response(self, response_id: str, context: InteractionContext, *,
                      repair: ReplyRepairPermit | None = None, now_ns: int | None = None) -> ReplyRevision:
        if self._closed:
            raise RuntimeError("reply revision controller is closed")
        if not response_id:
            raise ValueError("response identity must be non-empty")
        self._live_started = True
        previous = self.reply
        if repair is not None and (now_ns is None or not self.context_repair_permit_current(repair, now_ns=now_ns)
            or (context.turn_id, context.generation) != (repair.context.turn_id, repair.context.generation)
            or conversation_scope(context) != conversation_scope(repair.context)
            or response_id != repair.response_id):
            raise ValueError("reply repair permission is no longer current")
        if previous is not None and previous.response_id == response_id:
            if (previous.turn_id, previous.generation) != (context.turn_id, context.generation):
                raise ValueError("response identity was reused for another input")
            return previous  # Repeated started never restores a revoked permission.
        current = self.input
        if current is not None and (current.turn_id, current.generation) != (
            context.turn_id, context.generation
        ):
            current = None
        ancestor = (previous if current is not None and previous is not None
                    and previous.input_id == current.input_id else None)
        self._reply_context = context
        self._sample_rate_hz = None
        self._output_stop = None
        self._clear_interruption_recovery()
        self.reply = ReplyRevision(
            response_id=response_id, turn_id=context.turn_id, generation=context.generation,
            input_id=current.input_id if current is not None else None,
            input_version=current.input_version if current is not None else None,
            reply_version=ancestor.reply_version + 1 if ancestor is not None else 1,
            supersedes_response_id=ancestor.response_id if ancestor is not None else None,
            context_repair_attempt=repair.attempt if repair is not None else 0,
            context_repair_deadline_ns=repair.deadline_ns if repair is not None else None,
        )
        return self.reply

    def admit_projected_input(self, item: ConversationItem, context: InteractionContext) -> bool:
        """Bind trusted, already durable manual text without replaying ASR history."""
        text = "\n".join(part.text for part in item.content if isinstance(part, TextContent))
        if (self._closed or item.kind is not ConversationItemKind.USER_INPUT
            or item.status is not ConversationItemStatus.COMPLETED or not text.strip()
            or ConversationVisibility.MODEL not in item.visibility
            or conversation_scope(item.context) != conversation_scope(context)
            or (item.context.turn_id, item.context.generation) != (context.turn_id, context.generation)):
            return False
        previous = self.input
        if previous is not None and (previous.turn_id, previous.generation) == (context.turn_id, context.generation):
            return previous.text_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
        if (previous is not None and context.generation <= previous.generation
            or item.provider_metadata.get("input_id") is not None
            or item.provider_metadata.get("input_version") is not None):
            return False  # Old/mismatched ASR identities cannot become a new manual input.
        self.commit_input(input_id=item.item_id, context=context, text=text, transcript_revision=1,
                          continuation_of_turn_id=None, admission_reason="manual_text_committed")
        return True

    def offer_context_repair(self, response_id: str, context: InteractionContext, *,
                             minimum_thread_sequence: int, deadline_ns: int, now_ns: int) -> ReplyRepairPermit | None:
        reply, current, owner = self.reply, self.input, self._reply_context
        if (self._closed or reply is None or current is None or owner is None
            or reply.response_id != response_id or reply.delivery_permitted
            or reply.invalidation_reason != "response_invalidated" or reply.context_repair_permit is not None
            or (reply.input_id, reply.input_version) != (current.input_id, current.input_version)
            or (context.turn_id, context.generation) != (current.turn_id, current.generation)
            or conversation_scope(context) != conversation_scope(owner)
            or reply.context_repair_attempt >= MAX_CONTEXT_REPAIRS):
            return None
        deadline = reply.context_repair_deadline_ns or deadline_ns
        if now_ns >= deadline:
            return None
        permit = ReplyRepairPermit(permit_id=str(uuid.uuid4()), context=owner,
            predecessor_response_id=response_id, response_id=str(uuid.uuid4()),
            input_id=current.input_id, input_version=current.input_version,
            predecessor_reply_version=reply.reply_version, minimum_thread_sequence=minimum_thread_sequence,
            attempt=reply.context_repair_attempt + 1, deadline_ns=deadline)
        self.reply = replace(reply, context_repair_permit=permit)
        return permit

    def context_repair_permit_current(self, permit: ReplyRepairPermit, *, now_ns: int) -> bool:
        reply, current = self.reply, self.input
        return bool(not self._closed and reply is not None and current is not None
            and reply.context_repair_permit == permit and now_ns < permit.deadline_ns
            and reply.invalidation_reason == "response_invalidated" and not reply.delivery_permitted
            and (current.input_id, current.input_version, current.turn_id, current.generation) ==
                (permit.input_id, permit.input_version, permit.context.turn_id, permit.context.generation))

    def delivery_allowed(self, response_id: str) -> bool:
        return bool(not self._closed and self.reply is not None
                    and self.reply.response_id == response_id and self.reply.delivery_permitted)

    def revoke(self, response_id: str, *, reason: str) -> ReplyRevision | None:
        if not reason:
            raise ValueError("reply invalidation reason must be non-empty")
        if self.reply is None or self.reply.response_id != response_id:
            return None
        if self.reply.invalidation_reason == "semantic_stop" and reason in {"response_invalidated", "barge_in_floor_claim"}:
            return self.reply  # Late Core invalidation cannot undo explicit user STOP.
        if reason != "barge_in_floor_claim":
            self._clear_interruption_recovery()
        retained = self.reply.sentence_permit if reason == "barge_in_floor_claim" else None
        repair = self.reply.context_repair_permit if reason == "response_invalidated" else None
        if (self.reply.delivery_permitted or self.reply.sentence_permit != retained
            or self.reply.context_repair_permit != repair or self.reply.invalidation_reason != reason):
            self.reply = replace(self.reply, delivery_permitted=False, invalidation_reason=reason,
                sentence_permit=retained, context_repair_permit=repair)
        return self.reply

    def grant_current_sentence(self, response_id: str, *, trigger_input_id: str,
                               transcript_revision: int, now_ns: int) -> CurrentSentencePermit | None:
        reply, owner = self.reply, self._reply_context
        if (not self.delivery_allowed(response_id) or reply is None or owner is None
            or reply.input_id is None or reply.input_version is None):
            return None
        fact = reply.playback
        if (fact is None or fact.terminal or fact.position_precision != "sample"
            or fact.current_sentence is None or fact.output_epoch is None
            or fact.played_position_samples is None or fact.sample_rate_hz is None):
            return None
        sentence, rate = fact.current_sentence, fact.sample_rate_hz
        age_ns = now_ns - fact.observed_at_ns
        if not 0 <= age_ns <= 250_000_000 or fact.played_audio_end_us + age_ns // 1000 >= sentence.audio_end_us:
            return None
        start = (sentence.audio_start_us * rate + 500_000) // 1_000_000
        end = (sentence.audio_end_us * rate + 500_000) // 1_000_000
        if (sample_position_us(start, rate) != sentence.audio_start_us
            or sample_position_us(end, rate) != sentence.audio_end_us
            or not start < fact.played_position_samples < end
            or fact.confirmed_text_end > sentence.text_start):
            return None
        wait_ms = (sentence.audio_end_us - fact.played_audio_end_us + 999) // 1000 + 250
        if wait_ms > 1500:
            return None
        permit = CurrentSentencePermit(permit_id=str(uuid.uuid4()), context=owner,
            input_id=reply.input_id, input_version=reply.input_version, response_id=reply.response_id,
            reply_version=reply.reply_version, output_epoch=fact.output_epoch, speech_id=fact.speech_id,
            sentence_id=sentence.sentence_id, audio_start_samples=start, audio_end_samples=end, sample_rate_hz=rate,
            trigger_input_id=trigger_input_id, trigger_transcript_revision=transcript_revision,
            issued_at_ns=now_ns, expires_at_ns=now_ns + wait_ms * 1_000_000,
            confirmed_text_end=fact.confirmed_text_end)
        self.reply = replace(reply, sentence_permit=permit)
        return permit

    def sentence_playback_permit_current(self, permit: CurrentSentencePermit, *, now_ns: int) -> bool:
        reply = self.reply
        fact = reply.playback if reply is not None else None
        return bool(not self._closed and reply is not None and reply.sentence_permit == permit
            and now_ns < permit.expires_at_ns and fact is not None and not fact.terminal
            and fact.position_precision == "sample" and fact.output_epoch == permit.output_epoch
            and fact.speech_id == permit.speech_id and fact.sample_rate_hz == permit.sample_rate_hz
            and fact.current_sentence is not None and fact.current_sentence.sentence_id == permit.sentence_id
            and fact.played_position_samples is not None
            and permit.audio_start_samples < fact.played_position_samples < permit.audio_end_samples)

    def _clear_interruption_recovery(self) -> None:
        self._interruption_recovery = None
        self._recovery_plan = None
        self._recovery_plan_basis = None

    def invalidate_recovery_planning(self) -> None:
        """New speech/input ownership supersedes any unconsumed recovery intention."""
        self._clear_interruption_recovery()

    def lock_interruption_recovery(self, response_id: str, overlap: InteractionContext, *,
                                   observation_id: str, revision: int, text: str,
                                   stopping_text: str, deadline_ns: int) -> bool:
        """Freeze the original accepted stop snapshot before revoking delivery."""
        reply, current, owner = self.reply, self.input, self._reply_context
        stopping = semantic_text(stopping_text)
        if (self._closed or self._interruption_recovery is not None or reply is None or current is None or owner is None
            or reply.response_id != response_id or not reply.delivery_permitted
            or (reply.input_id, reply.input_version) != (current.input_id, current.input_version)
            or conversation_scope(overlap) != conversation_scope(owner) or overlap.generation < reply.generation
            or not observation_id or revision < 1 or deadline_ns < 1
            or not stopping or not semantic_text(text).startswith(stopping)):
            return False
        self._interruption_recovery = _InterruptionRecovery(response_id, owner, current.input_id, current.input_version,
            reply.reply_version, overlap, observation_id, revision, stopping, revision, text, deadline_ns)
        return True

    def _matches_recovery_observation(self, context: InteractionContext, observation_id: str) -> bool:
        anchor = self._interruption_recovery
        return bool(not self._closed and anchor is not None and observation_id == anchor.observation_id
            and conversation_scope(context) == conversation_scope(anchor.overlap)
            and (context.turn_id, context.generation) == (anchor.overlap.turn_id, anchor.overlap.generation))

    def observe_interruption_revision(self, context: InteractionContext, *, observation_id: str,
                                      revision: int, text: str) -> bool:
        if not self._matches_recovery_observation(context, observation_id):
            return False
        anchor = self._interruption_recovery
        assert anchor is not None
        if revision < anchor.revision:
            return False
        if revision == anchor.revision:
            if text != anchor.text:
                self._clear_interruption_recovery()  # Reused revisions cannot establish fresh proof order.
                return False
            return True
        anchor.revision, anchor.text, anchor.feedback = revision, text, None
        self._recovery_plan = None
        self._recovery_plan_basis = None
        return True

    def observe_recovery_feedback(self, context: InteractionContext, *, observation_id: str,
                                  revision: int, text: str, verdict: InterruptionVerdict,
                                  speech_ended: bool, answering_question: bool, confidence_threshold: float) -> bool:
        """Accept caller-verified full revised feedback, never an old same-batch result."""
        if isinstance(confidence_threshold, bool) or not math.isfinite(confidence_threshold) or not 0 <= confidence_threshold <= 1:
            raise ValueError("recovery confidence threshold must be finite and between zero and one")
        if not self._matches_recovery_observation(context, observation_id):
            return False
        anchor = self._interruption_recovery
        assert anchor is not None
        revised = semantic_text(text)
        if (not speech_ended or answering_question or not revised
            or revision != anchor.revision or text != anchor.text or revision <= anchor.stopping_revision
            or revised.startswith(anchor.stopping_text)
            or verdict.source not in {"rule", "model"} or verdict.confidence < confidence_threshold
            or (verdict.candidate.generation, verdict.candidate.transcript_revision, verdict.candidate.boundary) !=
                (context.generation, revision, InterruptionBoundary.SENTENCE_END)
            or semantic_text(verdict.candidate.text) != revised):
            return False
        if verdict.label not in {InterruptionLabel.BACKCHANNEL, InterruptionLabel.IGNORE}:
            # Current complete contrary evidence revokes only the unconsumed plan.
            # Already-issued physical stop and old delivery revocation stay locked.
            anchor.feedback = None
            self._recovery_plan = None
            self._recovery_plan_basis = None
            return False
        anchor.feedback = verdict
        return True

    def _recovery_state(self, now_ns: int) -> tuple[_InterruptionRecovery, OutputStopFact, ReplyPlayback] | None:
        anchor, reply, current, stop = self._interruption_recovery, self.reply, self.input, self._output_stop
        if (self._closed or anchor is None or anchor.feedback is None or reply is None or current is None or stop is None
            or now_ns >= anchor.deadline_ns or reply.delivery_permitted or reply.invalidation_reason != "barge_in_floor_claim"
            or (reply.response_id, reply.reply_version, reply.input_id, reply.input_version) !=
                (anchor.response_id, anchor.reply_version, anchor.input_id, anchor.input_version)
            or (current.input_id, current.input_version) != (anchor.input_id, anchor.input_version)
            or stop.state != "STOP_CONFIRMED" or reply.playback is None or not reply.playback.terminal
            or reply.playback.output_epoch != stop.output_epoch or reply.playback.speech_id != stop.speech_id):
            return None
        return anchor, stop, reply.playback

    @staticmethod
    def _recovery_basis(state: tuple[_InterruptionRecovery, OutputStopFact, ReplyPlayback]) -> tuple[object, ...]:
        anchor, stop, playback = state
        return (anchor.observation_id, anchor.revision, anchor.text, anchor.feedback, stop, playback)

    def recovery_plan_current(self, plan: ReplyRecoveryPlan, *, now_ns: int) -> bool:
        state = self._recovery_state(now_ns)
        return bool(state is not None and self._recovery_plan == plan and self._recovery_plan_basis == self._recovery_basis(state))

    def plan_misinterruption_recovery(self, *, now_ns: int) -> ReplyRecoveryPlan | None:
        """Emit one immutable plan per current fact set; execution needs separate admission."""
        state = self._recovery_state(now_ns)
        if state is None:
            return None
        basis = self._recovery_basis(state)
        if self._recovery_plan is not None and self._recovery_plan_basis == basis:
            return None
        anchor, stop, playback = state
        assert anchor.feedback is not None
        exact = (playback.position_precision == "sample" and playback.played_position_samples == stop.played_position_samples
                 and playback.sample_rate_hz is not None)
        response_id = str(uuid.uuid4())
        plan = ReplyRecoveryPlan(plan_id=str(uuid.uuid4()), source_context=anchor.owner, trigger_context=anchor.overlap,
            response_context=replace(anchor.owner, generation=max(anchor.owner.generation, anchor.overlap.generation) + 1,
                                     response_id=response_id),
            predecessor_response_id=anchor.response_id, input_id=anchor.input_id, input_version=anchor.input_version,
            predecessor_reply_version=anchor.reply_version, observation_id=anchor.observation_id,
            transcript_revision=anchor.revision, revised_text_sha256=hashlib.sha256(anchor.text.encode("utf-8")).hexdigest(),
            feedback_label="backchannel" if anchor.feedback.label is InterruptionLabel.BACKCHANNEL else "ignore",
            feedback_source="rule" if anchor.feedback.source == "rule" else "model", feedback_confidence=anchor.feedback.confidence,
            stop_command_id=stop.stop_command_id, stopped_output_epoch=stop.output_epoch,
            operation_sequence=stop.operation_sequence, output_epoch=str(uuid.uuid4()), confirmed_text_end=playback.confirmed_text_end,
            played_audio_end_us=playback.played_audio_end_us, position_precision="sample" if exact else "unknown",
            played_position_samples=playback.played_position_samples if exact else None,
            sample_rate_hz=playback.sample_rate_hz if exact else None, deadline_ns=anchor.deadline_ns)
        self._recovery_plan, self._recovery_plan_basis = plan, basis
        return plan

    @property
    def output_stop(self) -> OutputStopFact | None:
        return None if self._closed else self._output_stop

    def observe_output_stop(self, fact: OutputStopFact) -> bool:
        """Observe the current target's saved stop, never grant delivery authority."""
        reply, owner = self.reply, self._reply_context
        if (self._closed or reply is None or owner is None
            or conversation_scope(fact.context) != conversation_scope(owner)
            or (fact.context.turn_id, fact.context.generation) != (reply.turn_id, reply.generation)
            or fact.context.response_id not in {owner.response_id, reply.response_id}
            or fact.speech_id not in {reply.response_id, f"response:{reply.response_id}"}
            or reply.playback is not None and reply.playback.output_epoch not in {None, fact.output_epoch}):
            return False
        previous = self._output_stop
        if previous is not None and previous.stop_command_id != fact.stop_command_id:
            if (previous.output_epoch != fact.output_epoch or previous.operation_sequence is None
                or fact.operation_sequence is None or fact.operation_sequence <= previous.operation_sequence):
                return False  # An unordered/older operation cannot replace current evidence.
            previous = None
        saved = transition_output_stop_fact(previous, fact)
        if saved == self._output_stop:
            return False
        self._output_stop = saved
        return True

    def observe_playback(self, response_id: str) -> None:
        if not self._closed and self.reply is not None and self.reply.response_id == response_id:
            self.reply = replace(self.reply, playback_started=True)

    def observe_playback_fact(self, response_id: str, context: InteractionContext, fact: ReplyPlayback) -> bool:
        """Only the actor calls this mutation; observations cannot restore permission."""
        reply, owner = self.reply, self._reply_context
        if (self._closed or reply is None or owner is None or reply.response_id != response_id
            or conversation_scope(context) != conversation_scope(owner)
            or (context.turn_id, context.generation) != (reply.turn_id, reply.generation)
            or context.response_id not in {owner.response_id, response_id}
            or fact.speech_id not in {response_id, f"response:{response_id}"}
            or self._sample_rate_hz is not None and fact.sample_rate_hz not in {None, self._sample_rate_hz}):
            return False
        previous = reply.playback
        if fact.current_sentence is not None and (previous is None or previous.current_sentence != fact.current_sentence):
            if (previous is not None and previous.current_sentence is not None
                and previous.current_sentence.sentence_id == fact.current_sentence.sentence_id):
                raise ValueError("playback sentence identity was reused with different boundaries")
            if fact.current_sentence.sentence_id != sentence_identity(
                context, fact.speech_id, fact.current_sentence.text, fact.current_sentence.text_start,
            ):
                raise ValueError("playback sentence belongs to another output")
        if previous is not None:
            if (fact.observed_at_ns < previous.observed_at_ns and not fact.terminal
                or fact.played_audio_end_us < previous.played_audio_end_us
                or previous.played_position_samples is not None and fact.played_position_samples is not None
                    and fact.played_position_samples < previous.played_position_samples
                or fact.confirmed_text_end < previous.confirmed_text_end
                or previous.output_epoch is not None and fact.output_epoch not in {None, previous.output_epoch}):
                return False
            if previous.terminal:
                if previous.position_precision == "unknown":
                    # A later projection can refine reported history, not certify
                    # an already uncertain final stop position or its PCM clock.
                    fact = replace(fact, position_precision="unknown", current_sentence=None,
                                   played_position_samples=None, sample_rate_hz=None)
                # A late in-flight progress report may refine the heard frontier,
                # but cannot change when this output first became terminal.
                fact = replace(fact, terminal=True, current_sentence=None,
                               observed_at_ns=previous.observed_at_ns)
            if fact.output_epoch is None:
                # An estimated/legacy receipt invalidates current-sentence certainty.
                # Keep the attachment identity and monotonic heard frontier separately.
                fact = replace(fact, output_epoch=previous.output_epoch, current_sentence=None)
            if fact.played_audio_end_us == previous.played_audio_end_us and not fact.terminal:
                fact = replace(fact, observed_at_ns=previous.observed_at_ns)
        if fact.sample_rate_hz is not None:
            self._sample_rate_hz = fact.sample_rate_hz
        self.reply = replace(reply, playback=fact,
            sentence_permit=None if fact.terminal else reply.sentence_permit,
            playback_started=reply.playback_started or fact.played_audio_end_us > 0)
        return self.reply != reply

    def finish(self, response_id: str) -> None:
        if self.reply is not None and self.reply.response_id == response_id:
            self.reply = replace(self.reply, completed=True)

    def close(self) -> None:
        self._closed = True
        if self.reply is not None:
            self.revoke(self.reply.response_id, reason="session_closed")


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"restored {name} must be a non-empty string")
    return value


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"restored {name} must be a positive integer")
    return value
