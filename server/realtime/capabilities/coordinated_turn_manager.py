"""A session actor coordinating input, semantic evidence and assistant output.

Only the actor mutates lifecycle records. Models and timers return versioned
messages; they never mutate the actor or block the audio routing caller.
Canonical five-state events are a compatibility projection, not the authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from server.conversation_journal import (
    ConversationItemKind,
    ConversationJournal,
    ConversationVisibility,
    TextContent,
)
from server.conversation_journal.input_evidence import (
    EvidenceReceipt,
    InputEvidenceRecorder,
    InputEvidenceUnavailable,
)
from server.core.interaction_context import InteractionContext
from server.core.playback import CurrentSentencePermit
from server.core.turn_content import TurnContent, same_asr_utterance
from server.observability.telemetry import (
    SessionDebugLog,
    SessionTelemetry,
    TelemetryKind,
    TelemetryOutcome,
)
from server.realtime.capabilities.asr import (
    AsrCommitRejected,
    AsrEndpointHint,
    AsrTranscriptDelta,
    AsrTranscriptFinal,
)
from server.realtime.capabilities.assistant_echo import project_assistant_echo
from server.realtime.capabilities.reply_revision_controller import (
    ReplyRevision,
    ReplyRevisionController,
)
from server.realtime.capabilities.response_prefetch_controller import (
    PrefetchCandidate,
    ResponsePrefetchController,
)
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    AsrDiscardRequested,
    AssistantYieldRequested,
    DialogueStateChanged,
    LegacyTurnManagerCapabilityAdapter,
    ObserveAsrEvent,
    ObserveAssistantOutputStop,
    ObserveAssistantPlayback,
    ObserveAssistantSpokenText,
    ObserveAssistantYielded,
    ObserveConversationItem,
    ObserveResponseInvalidated,
    ObserveResponseRepairReady,
    ObserveSystemResponseCompleted,
    ObserveSystemResponseStarted,
    ObserveVadEvent,
    ReplyRepairRequested,
    SemanticInputRejected,
    TurnManagerCommand,
    TurnManagerEvent,
    UserTurnCommitted,
)
from server.realtime.capabilities.vad import VadSpeechStarted, VadSpeechStopped
from server.realtime.protocol.playback import ReplyPlayback
from server.realtime.scope import conversation_scope
from server.turn_policy.classifier_execution import ClassificationExecutor, run_classification
from server.turn_policy.coordination import (
    DefaultTurnCoordinationPolicy,
    FloorOwner,
    InterruptionDisposition,
    TurnCoordinationPolicy,
)
from server.turn_policy.dual_intent import DualIntent
from server.turn_policy.eot_classifier import (
    EotClassification,
    EotContext,
    EotDecision,
    EotHistoryMessage,
    EotRequest,
    classify_eot,
)
from server.turn_policy.input_association import (
    ConservativeInputAssociationPolicy,
    InputAssociation,
    InputAssociationPolicy,
    InputAssociationRequest,
    InputRelation,
)
from server.turn_policy.interruption_rules import InterruptionRuleContext, InterruptionRuleProvider
from server.turn_policy.plugins.rule_first_interruption_classifier import (
    ExactInterruptionRules,
    RuleFirstInterruptionClassifier,
)
from server.turn_policy.policy import TurnPolicy
from server.turn_policy.semantic_chunk_scheduler import SemanticChunkScheduler
from server.turn_policy.semantic_chunks import SemanticChunk, SemanticChunkBuffer, semantic_text
from server.turn_policy.semantic_input import SemanticInputBudget, SemanticInputState, TextBoundary
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionCandidate,
    InterruptionClassification,
    InterruptionLabel,
    InterruptionRequest,
    InterruptionVerdict,
    classify_interruption,
)
from server.turn_policy.semantic_task_registry import SemanticTaskRegistry
from server.turn_policy.states import DialogueState

logger = logging.getLogger(__name__)
_CLOSED = object()


@dataclass(slots=True)
class _Input:
    identity: str
    context: InteractionContext
    target_response: str | None
    text: str = ""
    revision: int = 0
    timestamp_us: int = 0
    speech_active: bool = False
    stop: VadSpeechStopped | None = None
    acoustic_version: int = 0
    endpoint: EotClassification | None = None
    verdict: InterruptionVerdict | None = None
    verdict_prefix: str | None = None
    yielded: bool = False
    floor_claim_confirmed: bool = False
    speech_started_ns: int | None = None
    speech_ended_ns: int | None = None
    yield_pending: bool = False
    commit_pending: bool = False
    provider_endpoint: bool = False
    boundary: TextBoundary = TextBoundary.PARTIAL
    started_us: int = 0
    last_judged_text: str = ""
    chunks: SemanticChunkScheduler | None = None
    semantic_chunk: SemanticChunk | None = None
    prior_chunks: tuple[str, ...] = ()
    chunk_feedback_only: bool = True
    vad_observed: bool = False
    assistant_text_at_onset: str = ""
    before_playback: bool = False
    continuation_text: str = ""
    continuation_of_turn_id: str | None = None
    created_ns: int = field(default_factory=time.monotonic_ns)
    observations: int = 0
    evidence_text: str = ""
    evidence_id: str | None = None
    evidence_bytes: int = 0
    blocked: bool = False
    rejected_text: str | None = None
    admission_reason: str | None = None
    sentence_wait: CurrentSentencePermit | None = None
    sentence_revoked: bool = False
    sentence_wait_playback: ReplyPlayback | None = None
    sentence_trigger_text: str = ""
    sentence_wait_initial_ns: int = 0
    sentence_prefetch_started: bool = False


@dataclass(frozen=True, slots=True)
class TurnCoordinationSnapshot:
    floor: FloorOwner
    input_id: str | None
    transcript_revision: int
    response_id: str | None
    commit_pending: bool


@dataclass(frozen=True, slots=True)
class _Result:
    identity: str
    revision: int
    kind: str
    value: EotClassification | InterruptionVerdict
    token: str
    chunk_id: str | None = None


@dataclass(frozen=True, slots=True)
class _Timer:
    identity: str
    revision: int
    acoustic_version: int
    kind: str
    chunk_prefix: str | None = None
    semantic_prefix: str | None = None


@dataclass(frozen=True, slots=True)
class _InputBudgetDeadline:
    identity: str


@dataclass(frozen=True, slots=True)
class _EvidenceFault:
    reason: str


@dataclass(frozen=True, slots=True)
class _InputRejectionResult:
    identity: str
    reason: str
    evidence_id: str | None
    saved: bool


class CoordinatedTurnManagerCapabilityAdapter(LegacyTurnManagerCapabilityAdapter):
    """Reuse deployment options, with a new actor and independently replaceable policy.

    ``policy_factory`` from the legacy constructor remains accepted for deployment
    compatibility. The actor uses ``coordination_policy_factory`` instead.
    """

    def __init__(
        self,
        *args: Any,
        coordination_policy_factory: Callable[[], TurnCoordinationPolicy] | None = None,
        recovery_timeout_ms: float = 10000,
        semantic_chunks_enabled: bool = False,
        semantic_chunk_concurrency: int = 1,
        interruption_chunk_chars: int = 5,
        chunk_stability_ms: float = 120,
        response_prefetch_enabled: bool = False,
        sentence_handoff_prefetch_enabled: bool = False,
        interruption_rules: InterruptionRuleProvider | None = None,
        telemetry: SessionTelemetry | None = None,
        debug_log: SessionDebugLog | None = None,
        input_budget: SemanticInputBudget | None = None,
        input_evidence_journal: ConversationJournal | None = None,
        input_evidence_timeout_s: float = 1,
        input_association_policy: InputAssociationPolicy | None = None,
        **kwargs: Any,
    ) -> None:
        if args and (len(args) != 1 or args[0] is not TurnPolicy):
            raise ValueError("Use coordination_policy_factory to replace coordinator decisions")
        super().__init__(*(args or (TurnPolicy,)), **kwargs)
        if not math.isfinite(input_evidence_timeout_s) or input_evidence_timeout_s <= 0:
            raise ValueError("input evidence timeout must be finite and positive")
        self.input_budget = input_budget or SemanticInputBudget()
        self.input_evidence_journal = input_evidence_journal
        self.input_evidence_timeout_s = input_evidence_timeout_s
        self.input_association_policy = (input_association_policy if input_association_policy is not None
                                         else ConservativeInputAssociationPolicy())
        if not math.isfinite(recovery_timeout_ms) or recovery_timeout_ms <= 0:
            raise ValueError("recovery_timeout_ms must be finite and positive")
        for value in (
            self._asr_idle_stop_s,
            self._incomplete_timeout_s,
            self._uncertain_wait_ms,
            self._semantic_interruption_idle_ms,
            self._semantic_interruption_timeout_ms,
            self._endpoint_gate._classifier_timeout_s,
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError("coordination timings must be finite and non-negative")
        if not math.isfinite(chunk_stability_ms) or chunk_stability_ms < 0:
            raise ValueError("chunk stability must be finite and non-negative")
        SemanticChunkBuffer(character_limit=interruption_chunk_chars)
        self.interruption_rules = interruption_rules if interruption_rules is not None else ExactInterruptionRules()
        self.response_prefetch_enabled = response_prefetch_enabled
        self.sentence_handoff_prefetch_enabled = sentence_handoff_prefetch_enabled
        SemanticChunkScheduler(character_limit=interruption_chunk_chars, max_concurrency=semantic_chunk_concurrency)
        self.semantic_chunk_concurrency = semantic_chunk_concurrency
        self.semantic_chunks_enabled = semantic_chunks_enabled
        self.interruption_chunk_chars = interruption_chunk_chars
        self.chunk_stability_ms = chunk_stability_ms
        self.recovery_timeout_ms = recovery_timeout_ms
        self.coordination_policy_factory = coordination_policy_factory or (
            lambda: DefaultTurnCoordinationPolicy(
                self._incomplete_timeout_s * 1000,
                self._uncertain_wait_ms,
            )
        )
        self._telemetry = telemetry
        self._debug_log = debug_log

    async def open(self, *, context: InteractionContext) -> CoordinatedTurnManagerSession:  # type: ignore[override]
        return CoordinatedTurnManagerSession(self, context)


class CoordinatedTurnManagerSession:
    def __init__(
        self, provider: CoordinatedTurnManagerCapabilityAdapter, context: InteractionContext
    ) -> None:
        self._provider = provider
        if provider._telemetry is not None:
            provider._telemetry.record("interaction.collection_ready", attributes={"measurement": "server_vad_receipt_estimate"})
        self._context = context
        self._policy = provider.coordination_policy_factory()
        self._input: _Input | None = None
        self._response_id: str | None = None
        self._response_context: InteractionContext | None = None
        self._last_committed: tuple[str, str] | None = None
        self._awaiting_response = False
        self._revisions = ReplyRevisionController()
        self._deferred_context_repair: ObserveResponseRepairReady | None = None
        self._response_playback_started = False
        self._assistant_text = ""
        self._history: dict[str, tuple[int, EotHistoryMessage]] = {}
        self._state = DialogueState.IDLE
        self._floor = FloorOwner.USER
        self._inbox: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        self._outbox: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        self._tasks = SemanticTaskRegistry()
        self._classifier_executor = ClassificationExecutor(provider.semantic_chunk_concurrency)
        self._jobs = self._tasks.jobs
        self._all_jobs = self._tasks.all_tasks
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._failure: Exception | None = None
        self._deferred_input: list[ObserveVadEvent | ObserveAsrEvent] = []
        self._evidence_fault_reported = False
        self._revision_evidence_failure: str | None = None
        self._evidence = InputEvidenceRecorder(
            provider.input_evidence_journal, context=context, on_failure=self._notify_evidence_failure,
            write_timeout_s=provider.input_evidence_timeout_s,
        ) if provider.input_evidence_journal is not None else None
        self._interruption_decider = RuleFirstInterruptionClassifier(model_call=self._classify_interruption_model, rules=provider.interruption_rules)
        self._prefetch = ResponsePrefetchController(provider._response_prefetcher,
            enabled=provider.response_prefetch_enabled, is_current=self._prefetch_is_current,
            observer=lambda operation, generation, attributes: self._log_prefetch(operation, generation, **attributes))
        self._actor = asyncio.create_task(self._run(), name="turn-coordinator")

    def set_prefetch_turn_builder(self, builder: Callable[[PrefetchCandidate], Awaitable[TurnContent]]) -> None:
        self._prefetch.set_turn_builder(builder)

    def response_delivery_allowed(self, response_id: str) -> bool:
        """Read-only permission, also checked when queued output is drained."""
        return (not self._closed and self._failure is None and not self._evidence_fault_reported
                and self._revision_evidence_failure is None
                and (self._evidence is None or self._evidence.failure is None)
                and (self._input is None or self._input.sentence_wait is None)
                and self._revisions.delivery_allowed(response_id))

    def sentence_playback_permit_current(self, permit: CurrentSentencePermit) -> bool:
        return (not self._closed and self._failure is None and not self._evidence_fault_reported
                and self._revision_evidence_failure is None
                and (self._evidence is None or self._evidence.failure is None)
                and self._revisions.sentence_playback_permit_current(permit, now_ns=time.monotonic_ns()))

    def response_revision(self, response_id: str) -> ReplyRevision | None:
        reply = self._revisions.reply
        return reply if reply is not None and reply.response_id == response_id else None

    async def invalidate_response(self, response_id: str, *, context: InteractionContext, reason: str) -> None:
        await self.send(ObserveResponseInvalidated(context=context, response_id=response_id, reason=reason))

    def _record_revision(self, event: str, context: InteractionContext, detail: dict[str, Any]) -> None:
        # Output sentence text already lives in speech/Journal records. Do not
        # duplicate it into the input-evidence budget on every identity transition.
        playback = detail.get("playback", detail)
        if isinstance(playback, dict) and isinstance(playback.get("current_sentence"), dict):
            sentence = playback["current_sentence"]
            text = sentence.pop("text")
            sentence["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            sentence["text_length"] = len(text)
        if self._provider._telemetry is not None:
            self._provider._telemetry.record("response.revision", generation=context.generation,
                attributes={"operation": event, **detail})
        if self._evidence is not None:
            current = self._revisions.input
            try:
                self._evidence.offer(current.input_id if current else context.turn_id,
                                     event, detail, context=context)
            except InputEvidenceUnavailable:
                self._notify_evidence_failure("input_evidence_unavailable")

    def _revoke_response(self, response_id: str, *, reason: str) -> None:
        before = self._revisions.reply
        revoked = self._revisions.revoke(response_id, reason=reason)
        if revoked is not None and before is not None and before.sentence_permit is not None and revoked.sentence_permit is None:
            permit = before.sentence_permit
            item = self._input
            if item is not None and item.sentence_wait == permit:
                item.sentence_revoked = True
                self._prefetch.invalidate(reason)
                self._timer("sentence_stop_ack", self._provider.recovery_timeout_ms * 2 + 250, item)
            self._outbox.put_nowait(AssistantYieldRequested(
                context=replace(item.context if item and item.target_response == response_id else permit.context, response_id=response_id),
                reason=reason, revokes_sentence_permit_id=permit.permit_id))
        if revoked is not None and before is not None and revoked != before:
            self._record_revision("reply_invalidated", self._response_context or self._context,
                                  asdict(revoked))

    def _notify_evidence_failure(self, reason: str) -> None:
        if self._closed:
            return
        self._revision_evidence_failure = reason
        try:
            self._inbox.put_nowait((_EvidenceFault(reason), None))
        except asyncio.QueueFull:
            pass  # Every queued event also checks recorder.failure before changing input state.

    def _record_input_evidence(self, item: _Input, event: str, detail: dict[str, Any], *, snapshot: str | None = None) -> EvidenceReceipt | None:
        if self._evidence is None or item.blocked:
            return None
        try:
            receipt = self._evidence.offer(item.identity, event, {
                "generation": item.context.generation, "turn_id": item.context.turn_id,
                "revision": item.revision, "target_response_id": item.target_response, **detail,
            }, context=item.context)
        except InputEvidenceUnavailable:
            self._begin_input_rejection(item, "input_evidence_unavailable", item.text if snapshot is None else snapshot,
                                        observed_revision=detail.get("revision", item.revision))
            return None
        item.evidence_bytes += receipt.size_bytes
        if item.evidence_bytes > self._provider.input_budget.max_evidence_bytes:
            self._begin_input_rejection(item, "input_evidence_bytes", item.text if snapshot is None else snapshot,
                                        observed_revision=detail.get("revision", item.revision))
        return receipt

    def _begin_input_rejection(self, item: _Input, reason: str, text: str, *, observed_revision: int | None = None) -> None:
        if item.blocked:
            return
        item.blocked = True
        if self._response_id is not None:
            self._revoke_response(self._response_id, reason=reason)
        item.rejected_text = text
        self._deferred_input.clear()
        self._tasks.clear()
        if item.chunks is not None:
            item.chunks.cancel_active()
        self._prefetch.invalidate(reason)
        receipt = None
        captured = False
        if self._evidence is not None:
            # Capture a complete terminal snapshot when it fits the separate evidence limit.
            # Unexpectedly huge provider payloads are explicitly marked uncaptured, never sliced.
            captured = len(text) <= 16 * 1024 and len(text.encode("utf-8")) <= 32 * 1024
            try:
                receipt = self._evidence.offer(item.identity, "input_rejected", {
                    "reason": reason, "accepted_revision": item.revision,
                    "rejected_revision": item.revision if observed_revision is None else observed_revision,
                    "capture_complete": captured,
                    "text": text if captured else None, "characters": len(text),
                }, context=item.context)
            except InputEvidenceUnavailable:
                pass  # The actor retains rejected_text and reports the missing commit explicitly.

        async def finish() -> None:
            saved = False
            if receipt is not None:
                try:
                    async with asyncio.timeout(self._provider.input_evidence_timeout_s + 0.1):
                        committed = await asyncio.shield(receipt.committed)
                        saved = captured and receipt.durable and committed.item_id == receipt.item_id
                except (InputEvidenceUnavailable, TimeoutError):
                    pass
            await self._inbox.put((_InputRejectionResult(
                item.identity, reason, receipt.item_id if receipt is not None else None, saved,
            ), None))

        self._job("input_rejection", finish())

    def _prefetch_is_current(self, candidate: PrefetchCandidate) -> bool:
        item = self._input
        if (item is None or item.blocked or item.identity != candidate.identity or item.commit_pending
            or item.context.generation != candidate.generation
            or not same_asr_utterance(item.text, candidate.observed_text)):
            return False
        if candidate.sentence_handoff:
            permit = item.sentence_wait
            return bool(permit is not None and not item.sentence_revoked and item.yielded
                and not item.speech_active and item.stop is not None
                and permit == candidate.sentence_permit
                and item.sentence_wait_playback is not None
                and item.sentence_wait_playback.current_sentence == candidate.permitted_sentence
                and self.sentence_playback_permit_current(permit)
                and self._last_committed is not None
                and self._last_committed[0] == candidate.continuation_of_turn_id)
        return item.target_response is None

    def _log_prefetch(self, operation: str, generation: int, **attributes: Any) -> None:
        if self._provider._telemetry is not None:
            self._provider._telemetry.record("response.prefetch", generation=generation,
                attributes={"operation": operation, **attributes})
        if self._provider._debug_log is not None:
            self._provider._debug_log.log("llm", "prefetch", operation, generation=generation, detail=attributes)

    def _maybe_prefetch(self, item: _Input) -> None:
        if item.blocked:
            return
        permit = item.sentence_wait
        if permit is not None:
            if (not self._provider.sentence_handoff_prefetch_enabled or item.sentence_prefetch_started
                or item.sentence_revoked or not item.yielded or item.speech_active or item.stop is None
                or not self.sentence_playback_permit_current(permit) or not self._is_ordinary_supplement(item)):
                return
            assert self._last_committed is not None
            parent_id, parent_text = self._last_committed
            cumulative = parent_text + "\n" + item.text
            if self._provider.input_budget.violation(cumulative, revisions=item.observations,
                    elapsed_ms=(time.monotonic_ns() - item.created_ns) / 1e6):
                return  # Formal final input retains the existing explicit rejection path.
            item.sentence_prefetch_started = True
            self._prefetch.prepare(PrefetchCandidate(identity=item.identity, generation=item.context.generation,
                text=cumulative, source_text=item.text, revision=item.revision, speech_active=False,
                interrupted=True, continuation=True, committed=item.commit_pending,
                continuation_of_turn_id=parent_id, sentence_permit=permit,
                permitted_sentence=item.sentence_wait_playback.current_sentence if item.sentence_wait_playback else None))
            return
        self._prefetch.prepare(PrefetchCandidate(identity=item.identity, generation=item.context.generation,
            text=item.text, revision=item.revision, speech_active=item.speech_active,
            interrupted=item.target_response is not None, continuation=bool(item.continuation_of_turn_id),
            committed=item.commit_pending))

    def snapshot(self) -> TurnCoordinationSnapshot:
        item = self._input
        return TurnCoordinationSnapshot(
            self._floor,
            item.identity if item else None,
            item.revision if item else 0,
            self._response_id,
            item.commit_pending if item else False,
        )

    async def send(self, command: TurnManagerCommand) -> None:
        if self._closed or self._actor.done():
            raise RuntimeError("Turn coordinator is closed") from self._failure
        if isinstance(command, ObserveConversationItem) and any(
            getattr(command.item.context, name) != getattr(self._context, name)
            for name in ("tenant_id", "user_id", "thread_id")
        ):
            raise ValueError("History item belongs to another conversation")
        supplied = getattr(command, "context", None)
        if isinstance(command, (ObserveAsrEvent, ObserveVadEvent)):
            supplied = command.event.context
        if supplied is not None and any(
            getattr(supplied, name) != getattr(self._context, name)
            for name in ("tenant_id", "user_id", "device_id", "voice_session_id", "thread_id")
        ):
            raise ValueError("Turn coordinator context belongs to another session")
        done = asyncio.get_running_loop().create_future()
        await self._inbox.put((command, done))
        if self._actor.done() and not done.done():
            done.set_exception(RuntimeError("Turn coordinator stopped"))
        await done

    async def events(self) -> AsyncGenerator[TurnManagerEvent, None]:
        while True:
            event = await self._outbox.get()
            if event is _CLOSED:
                if self._failure:
                    raise self._failure
                return
            yield event

    async def _run(self) -> None:
        done = None
        try:
            while True:
                event, done = await self._inbox.get()
                try:
                    await self._handle(event)
                    if done is not None and not done.done():
                        done.set_result(None)
                except Exception as error:
                    if done is not None and not done.done():
                        done.set_exception(error)
                    raise
        except asyncio.CancelledError:
            pass
        except Exception as error:
            self._failure = error
            logger.exception("Turn coordination failed")
            self._tasks.clear()
            await self._outbox.put(_CLOSED)
        finally:
            if done is not None and not done.done():
                done.set_exception(RuntimeError("Turn coordinator stopped"))
            while not self._inbox.empty():
                _, done = self._inbox.get_nowait()
                if done is not None and not done.done():
                    done.set_exception(RuntimeError("Turn coordinator stopped"))

    def _job(self, key: str, operation: Any) -> None:
        self._tasks.start(key, operation)

    def _cancel(self, *keys: str) -> None:
        self._tasks.cancel(*keys)

    def _timer(self, kind: str, delay_ms: float, item: _Input) -> None:
        if not math.isfinite(delay_ms) or delay_ms < 0:
            raise ValueError("coordination wait must be finite and non-negative")
        message = _Timer(
            item.identity,
            item.revision,
            item.acoustic_version,
            kind,
            item.chunks.stability_prefix if item.chunks else None,
            semantic_text(item.text) if kind == "commit" and item.chunks else None,
        )

        async def wait() -> None:
            await asyncio.sleep(delay_ms / 1000)
            await self._inbox.put((message, None))

        self._job(kind, wait())

    def _current(self, message: _Result | _Timer) -> _Input | None:
        item = self._input
        if item is None or item.commit_pending or item.identity != message.identity:
            return None
        if isinstance(message, _Timer):
            if message.kind == "chunks":
                return item  # Stability is checked against the scheduler in _handle.
            if message.kind == "commit" and message.semantic_prefix is not None:
                # Equivalent ASR revisions retain the same absolute commit deadline.
                # Meaningful rewrites invalidate it even if a provider reuses revision.
                return item if semantic_text(item.text) == message.semantic_prefix else None
            return item if item.revision == message.revision else None
        if item.revision == message.revision or (
            message.chunk_id is not None
            and item.chunks is not None
            and item.chunks.matches_active(message.chunk_id)
        ):
            return item
        return None

    def _defer_input(self, event: ObserveVadEvent | ObserveAsrEvent) -> None:
        if len(self._deferred_input) >= 64:
            raise RuntimeError("Input observations overflowed during ASR finalization")
        self._deferred_input.append(event)

    def _ensure_input(self, context: InteractionContext) -> _Input:
        if self._input is None:
            self._input = _Input(str(uuid.uuid4()), context, self._response_id, assistant_text_at_onset=self._assistant_text)
            identity = self._input.identity

            async def deadline() -> None:
                await asyncio.sleep(self._provider.input_budget.max_duration_ms / 1000)
                await self._inbox.put((_InputBudgetDeadline(identity), None))

            self._job("input_budget_duration", deadline())
            if self._provider.semantic_chunks_enabled:
                self._input.chunks = SemanticChunkScheduler(character_limit=self._provider.interruption_chunk_chars if self._response_id else 64, max_concurrency=self._provider.semantic_chunk_concurrency)
            if (
                self._last_committed and (self._awaiting_response or (
                    self._response_id and not self._response_playback_started
                    and self._response_context
                    and self._last_committed[0] == self._response_context.turn_id
                ))
            ):
                self._input.continuation_of_turn_id, self._input.continuation_text = self._last_committed
                self._input.before_playback = True
        return self._input

    def _history_snapshot(self) -> tuple[EotHistoryMessage, ...]:
        entries = [message for _, message in sorted(self._history.values(), key=lambda v: v[0])]
        entries = entries[-self._provider._history_max_messages :]
        budget = self._provider._history_max_chars
        selected: list[EotHistoryMessage] = []
        for index, message in enumerate(reversed(entries)):
            reserve = 1 if index == 0 and len(entries) > 1 and budget > 1 else 0
            size = min(len(message.content), budget - reserve)
            if size <= 0:
                break
            selected.append(
                EotHistoryMessage(
                    message.role,
                    message.content[-size:],
                    message.truncated or size < len(message.content),
                )
            )
            budget -= size
        return tuple(reversed(selected))

    async def _project(self, context: InteractionContext) -> None:
        item = self._input
        self._floor = (
            FloorOwner.ASSISTANT
            if self._response_id or (item and item.commit_pending)
            else FloorOwner.USER
        )
        state = (
            DialogueState.DUAL
            if self._response_id and item and not item.commit_pending
            else DialogueState.SPEAK
            if self._floor is FloorOwner.ASSISTANT
            else DialogueState.LISTEN
            if item
            else DialogueState.IDLE
        )
        if state is not self._state:
            await self._outbox.put(
                DialogueStateChanged(
                    context=context,
                    from_state=self._state,
                    to_state=state,
                    transition="coordinated",
                    occurred_at=datetime.now(UTC),
                )
            )
            self._state = state

    async def _resume_context_repair(self) -> None:
        ready = self._deferred_context_repair
        if ready is None:
            return
        if (self._closed or self._awaiting_response or self._revision_evidence_failure is not None
            or self._evidence is not None and self._evidence.failure):
            self._deferred_context_repair = None
            return
        if self._input is not None:
            return  # One bounded hint; no generation while input is unresolved.
        self._deferred_context_repair = None
        now_ns = time.monotonic_ns()
        reply = self._revisions.reply
        existing = reply.context_repair_permit if reply is not None and reply.response_id == ready.response_id else None
        if existing is not None:
            if self._revisions.context_repair_permit_current(existing, now_ns=now_ns):
                await self._outbox.put(ReplyRepairRequested(context=ready.context, permit=existing))
            return
        permit = self._revisions.offer_context_repair(ready.response_id, ready.context,
            minimum_thread_sequence=ready.minimum_thread_sequence, deadline_ns=ready.deadline_ns, now_ns=now_ns)
        if permit is not None:
            self._record_revision("context_repair_offered", ready.context, asdict(permit))
            await self._outbox.put(ReplyRepairRequested(context=ready.context, permit=permit))

    async def _handle(self, event: Any) -> None:
        if self._evidence is not None and (self._evidence.failure or self._revision_evidence_failure) and not self._evidence_fault_reported:
            self._evidence_fault_reported = True
            self._deferred_context_repair = None
            if self._input is not None:
                self._begin_input_rejection(self._input, "input_evidence_unavailable", self._input.text)
            else:
                self._tasks.clear()
                self._prefetch.invalidate("input_evidence_unavailable")
                if self._response_id is not None:
                    self._revoke_response(self._response_id, reason="input_evidence_unavailable")
                await self._outbox.put(SemanticInputRejected(
                    context=self._context, reason="input_evidence_unavailable",
                    evidence_id=None, evidence_saved=False,
                ))
        if isinstance(event, _EvidenceFault):
            return
        if isinstance(event, _InputBudgetDeadline):
            item = self._input
            if item is not None and item.identity == event.identity and not item.commit_pending:
                self._begin_input_rejection(item, "input_duration", item.text)
            return
        if isinstance(event, _InputRejectionResult):
            item = self._input
            if item is None or item.identity != event.identity or not item.blocked:
                return
            await self._outbox.put(SemanticInputRejected(
                context=item.context, reason=event.reason, evidence_id=event.evidence_id,
                evidence_saved=event.saved,
            ))
            if event.saved:
                await self._outbox.put(AsrDiscardRequested(context=item.context, reason=event.reason))
                self._input = None
            self._tasks.clear()
            return
        if isinstance(event, (_Result, _Timer)):
            if isinstance(event, _Timer) and event.kind == "sentence_expiry":
                pending = self._input
                if pending and pending.identity == event.identity and pending.sentence_wait is not None:
                    await self._withdraw_sentence_wait(pending, "sentence_permit_deadline")
                return
            if isinstance(event, _Timer) and event.kind in {"asr_final", "yield_ack", "sentence_stop_ack"}:
                pending = self._input
                if (
                    pending
                    and pending.identity == event.identity
                    and (
                        pending.commit_pending
                        if event.kind == "asr_final"
                        else pending.sentence_wait is not None if event.kind == "sentence_stop_ack"
                        else pending.yield_pending
                    )
                ):
                    raise TimeoutError(f"Turn coordination missing {event.kind}")
                return
            item = self._current(event)
            if item is None or item.blocked:
                return
            if isinstance(event, _Result):
                if not self._tasks.accept(event.kind, event.chunk_id, event.token):
                    return
                chunk = None
                if event.chunk_id is not None:
                    feedback = None
                    if isinstance(event.value, InterruptionVerdict):
                        disposition = self._policy.interruption(event.value)
                        feedback = (
                            event.value.label is InterruptionLabel.BACKCHANNEL
                            and event.value.source != "fallback"
                            and not disposition.stop_response
                            and not disposition.admit_input
                        )
                    chunk = item.chunks.complete(event.chunk_id, feedback=feedback) if item.chunks else None
                    if chunk is None:
                        return
                    self._log_chunk(item, chunk, "result", {"outcome": "accepted", "result": str(event.value)})
                label = event.value.label if isinstance(event.value, InterruptionVerdict) else event.value.decision
                self._record_input_evidence(item, "classification_result", {
                    "chunk_id": event.chunk_id,
                    "semantic_end": chunk.semantic_end if chunk is not None else None,
                    "current_asr_evidence_id": item.evidence_id, "candidate_revision": event.revision,
                    "request_token": event.token,
                    "kind": event.kind, "label": label.value, "source": event.value.source,
                    "confidence": event.value.confidence,
                })
                if item.blocked:
                    return
                if isinstance(event.value, EotClassification):
                    if event.chunk_id is None or (chunk is not None and chunk.semantic_end == len(semantic_text(item.text))):
                        item.endpoint = event.value
                else:
                    if item.floor_claim_confirmed or item.yield_pending:
                        return
                    # Before STOP is issued, a full-input negative verdict supersedes
                    # an older positive prefix. After STOP, the lock above wins.
                    # Full-input means the entire candidate snapshot, not SentenceEnd.
                    # Retaining input (admit_input) is separate from rejecting stale STOP.
                    # Only the tail-rule feedback proof needs permission to discard it.
                    full_prefix = semantic_text(item.text)
                    latest_rejects_stop = (
                        item.verdict is not None
                        and item.verdict_prefix == full_prefix
                        and item.verdict.label in {InterruptionLabel.IGNORE, InterruptionLabel.BACKCHANNEL}
                    )
                    if (event.chunk_id is not None and chunk is not None
                            and chunk.semantic_end != len(full_prefix)
                            and (item.yielded or not event.value.should_stop or latest_rejects_stop)):
                        self._log_chunk(item, chunk, "result_ignored", {
                            "reason": "playback_completed_prefix" if item.yielded else "superseded_by_full_input" if latest_rejects_stop else "non_stopping_prefix",
                        })
                        self._drain_chunks(item)
                        await self._advance(item)
                        return
                    item.verdict = event.value
                    item.verdict_prefix = full_prefix[:chunk.semantic_end] if event.chunk_id is not None and chunk is not None else full_prefix
                    action = self._policy.interruption(event.value)
                    if action.stop_response and not item.yielded:
                        item.floor_claim_confirmed = True
                        self._cancel("interruption_model", "chunks")
                        if item.chunks is not None:
                            item.chunks.cancel_active()
                        await self._yield(item)
                if event.chunk_id is not None:
                    self._drain_chunks(item)
                await self._advance(item)
            elif event.kind == "chunks":
                if item.chunks is None or event.chunk_prefix != item.chunks.stability_prefix:
                    return
                self._jobs.pop("chunks", None)
                self._collect_chunks(item, stable=True)
                await self._advance(item)
            elif event.kind == "interruption":
                self._start_interruption_judge(
                    item,
                    InterruptionCandidate(
                        item.text,
                        item.context.generation,
                        item.revision,
                        InterruptionBoundary.PARTIAL,
                    ),
                    None,
                )
            elif event.kind == "recovery":
                # Persistent acoustic activity with no ASR progress is ambiguous:
                # explicitly fail into the capability recovery path, never silently
                # swallow input or manufacture a quiet audio observation.
                if item.speech_active:
                    raise TimeoutError(
                        "ASR stalled during speech; input recovery deadline exceeded"
                    )
                if item.target_response and not item.floor_claim_confirmed and not item.yielded:
                    # Ambiguous text is neither feedback proof nor a floor claim.
                    # Preserve it and report a bounded failure instead of discarding.
                    self._begin_input_rejection(item, "unresolved_overlap_deadline", item.text)
                    return
                await self._advance(item, force=True, admission_reason="recovery_deadline")
            elif event.acoustic_version == item.acoustic_version:
                if event.kind == "idle":
                    if item.speech_active:
                        return
                    if not item.text:
                        self._input = None
                        await self._project(item.context)
                        await self._resume_context_repair()
                        return
                    item.stop = item.stop or VadSpeechStopped(
                        context=item.context,
                        audio_timestamp_us=item.timestamp_us,
                        silence_duration_us=0,
                    )
                    if self._provider.semantic_chunks_enabled:
                        self._collect_chunks(item, force=True)
                    await self._advance(item)
                elif event.kind == "commit":
                    await self._advance(item, force=True, admission_reason="endpoint_wait_deadline")
            return
        if isinstance(event, ObserveConversationItem):
            journal_item = event.item
            if (
                journal_item.kind
                in {ConversationItemKind.USER_INPUT, ConversationItemKind.ASSISTANT_OUTPUT}
                and ConversationVisibility.MODEL in journal_item.visibility
            ):
                text = "\n".join(
                    part.text for part in journal_item.content if isinstance(part, TextContent)
                )
                if self._revisions.restore_item(journal_item):
                    self._last_committed = (journal_item.context.turn_id, text)
                if text.strip():
                    self._history[journal_item.item_id] = (
                        journal_item.sequence,
                        EotHistoryMessage(
                            "user"
                            if journal_item.kind is ConversationItemKind.USER_INPUT
                            else "assistant",
                            text,
                        ),
                    )
                    if len(self._history) > self._provider._history_max_messages:
                        oldest = min(self._history, key=lambda key: self._history[key][0])
                        del self._history[oldest]
            return
        if isinstance(event, ObserveResponseInvalidated):
            self._revoke_response(event.response_id, reason=event.reason)
            return
        if isinstance(event, ObserveResponseRepairReady):
            self._deferred_context_repair = event
            await self._resume_context_repair()
            return
        if isinstance(event, ObserveSystemResponseStarted):
            preparing_ns = time.monotonic_ns()
            if event.input_item is not None and event.repair is None:
                supplied_context = event.context or self._context
                previous_input = self._revisions.input
                if (self._input is not None and self._input.context.generation > supplied_context.generation
                    and (previous_input is None or (previous_input.turn_id, previous_input.generation)
                         != (supplied_context.turn_id, supplied_context.generation))):
                    return
                if not self._revisions.admit_projected_input(event.input_item, supplied_context):
                    return  # Expected stale admission; do not terminate the actor.
                if self._revisions.input is not previous_input:
                    manual_text = "\n".join(part.text for part in event.input_item.content if isinstance(part, TextContent))
                    self._last_committed = (supplied_context.turn_id, manual_text)
                    # A new durable manual commit supersedes older uncommitted
                    # ASR, but starting an ASR-backed reply never discards its
                    # subsequent voice supplement.
                    if self._input is not None:
                        self._record_input_evidence(self._input, "manual_input_superseded", {
                            "text": self._input.text, "replacement_item_id": event.input_item.item_id,
                        }, snapshot=self._input.text)
                        if self._input.blocked:
                            return  # Retain failed evidence ownership and its explicit rejection.
                        await self._outbox.put(AsrDiscardRequested(context=self._input.context, reason="manual_text_committed"))
                        self._input = None
                        self._tasks.clear()
                        self._prefetch.invalidate("manual_text_committed")
            if event.repair is not None and (self._input is not None or self._awaiting_response
                or self._revision_evidence_failure is not None
                or not self._revisions.context_repair_permit_current(event.repair, now_ns=preparing_ns)):
                if (self._input is not None and self._revisions.context_repair_permit_current(event.repair, now_ns=preparing_ns)):
                    self._deferred_context_repair = ObserveResponseRepairReady(context=event.repair.context,
                        response_id=event.repair.predecessor_response_id,
                        minimum_thread_sequence=event.repair.minimum_thread_sequence, deadline_ns=event.repair.deadline_ns)
                return  # A stale repair is an expected race, not an actor failure.
            if (
                event.context
                and self._response_context
                and event.context.generation < self._response_context.generation
            ):
                return
            if self._response_id == event.response_id:
                if not event.preparing:
                    await self._project(event.context or self._context)
                return
            prior_reply = self._revisions.reply
            if self._input is not None and self._input.sentence_wait is not None:
                await self._withdraw_sentence_wait(self._input, "response_replaced")
            bound = self._revisions.bind_response(event.response_id, event.context or self._context,
                repair=event.repair, now_ns=preparing_ns)
            if prior_reply is None or prior_reply.response_id != event.response_id:
                self._record_revision("reply_bound", event.context or self._context, asdict(bound))
            self._deferred_context_repair = None
            self._response_id = event.response_id
            self._response_context = event.context
            self._assistant_text = ""
            self._response_playback_started = False
            item = self._input
            if item and not item.commit_pending and item.target_response != event.response_id:
                self._prefetch.invalidate("target_response_changed")
                self._cancel("yield_ack", "interruption_model", "interruption", "endpoint_model", "commit")
                if self._provider.semantic_chunks_enabled:
                    item.chunks = SemanticChunkScheduler(character_limit=self._provider.interruption_chunk_chars, max_concurrency=self._provider.semantic_chunk_concurrency)
                    self._cancel("chunks")
                item.target_response = event.response_id
                item.assistant_text_at_onset = ""
                if (self._last_committed and event.context
                    and self._last_committed[0] == event.context.turn_id
                    and (self._awaiting_response or item.continuation_of_turn_id)):
                    item.continuation_of_turn_id, item.continuation_text = self._last_committed
                    item.before_playback = True
                else:
                    item.continuation_text = ""
                    item.continuation_of_turn_id = None
                item.yielded = False
                item.floor_claim_confirmed = False
                item.yield_pending = False
                item.verdict = None
                item.verdict_prefix = None
                if item.text:
                    self._judge_interruption(item, InterruptionBoundary(item.boundary.value))
            self._awaiting_response = False
            if not event.preparing:
                await self._project(event.context or self._context)
            return
        if isinstance(event, ObserveSystemResponseCompleted):
            if event.response_id != self._response_id:
                return
            self._revisions.finish(event.response_id)
            self._response_id = None
            if self._input and self._input.target_response == event.response_id:
                self._input.yielded = True
                self._input.yield_pending = False
                await self._advance(self._input)
            await self._project(event.context or self._context)
            return
        if isinstance(event, ObserveAssistantOutputStop):
            if self._revisions.observe_output_stop(event.fact):
                fact = self._revisions.output_stop
                assert fact is not None
                detail = asdict(fact)
                reply = self._revisions.reply
                assert reply is not None
                detail.update(response_id=reply.response_id, input_id=reply.input_id,
                              input_version=reply.input_version, reply_version=reply.reply_version)
                for field in ("requested_at", "observed_at", "received_at"):
                    if detail[field] is not None:
                        detail[field] = detail[field].isoformat()
                self._record_revision("reply_output_stop_observed", fact.context, detail)
            return
        if isinstance(event, ObserveAssistantPlayback):
            item = self._input
            permit = item.sentence_wait if item is not None else None
            previous = item.sentence_wait_playback if item is not None else None
            valid_wait_fact = (permit is not None and previous is not None and event.response_id == permit.response_id
                and (event.fact.output_epoch == permit.output_epoch
                     or not event.fact.terminal and event.fact.output_epoch is None and event.fact.position_precision != "sample")
                and event.fact.speech_id == permit.speech_id
                and conversation_scope(event.context) == conversation_scope(permit.context)
                and (event.context.turn_id, event.context.generation) == (permit.context.turn_id, permit.context.generation)
                and event.context.response_id in {permit.context.response_id, permit.response_id}
                and event.fact.sample_rate_hz in {None, permit.sample_rate_hz}
                and event.fact.observed_at_ns >= (item.sentence_wait_initial_ns if event.fact.terminal and item is not None
                                                  else previous.observed_at_ns)
                and event.fact.played_audio_end_us >= previous.played_audio_end_us
                and event.fact.confirmed_text_end >= previous.confirmed_text_end
                and (event.fact.played_position_samples is None or previous.played_position_samples is None
                     or event.fact.played_position_samples >= previous.played_position_samples))
            if permit is not None and event.response_id == permit.response_id and event.fact.terminal and not valid_wait_fact:
                return
            before = self._revisions.reply.playback if self._revisions.reply else None
            if self._revisions.observe_playback_fact(event.response_id, event.context, event.fact):
                if self._response_id == event.response_id:
                    self._response_playback_started |= event.fact.played_audio_end_us > 0
                assert self._revisions.reply is not None
                after = self._revisions.reply.playback
                assert after is not None
                if permit is not None and item is not None and event.response_id == permit.response_id and not event.fact.terminal:
                    # A legacy/unknown observation still advances the physical
                    # frontier, even though it cannot keep sentence authority.
                    item.sentence_wait_playback = after
                if (permit is not None and not event.fact.terminal
                    and not self._revisions.sentence_playback_permit_current(permit, now_ns=time.monotonic_ns())):
                    assert item is not None
                    await self._withdraw_sentence_wait(item, "sentence_playback_evidence_changed")
                # Record identity/precision transitions, not every sample tick.
                if (before is None or before.current_sentence != after.current_sentence
                    or before.terminal != after.terminal
                    or before.position_precision != after.position_precision):
                    self._record_revision("reply_playback_observed", event.context, asdict(after))
            if valid_wait_fact:
                # Retain the original output's validated physical frontier even
                # after a replacement has become the revision ledger's current reply.
                assert item is not None and permit is not None
                item.sentence_wait_playback = replace(event.fact, output_epoch=permit.output_epoch)
                if event.fact.terminal:
                    self._prefetch.confirm_sentence_stop(permit, event.fact)
                    if (event.fact.position_precision != "sample" or event.fact.played_position_samples is None
                        or event.fact.sample_rate_hz is None):
                        # Stop confirmation releases the input wait, but unknown
                        # physical position cannot validate a sentence candidate.
                        self._prefetch.invalidate("sentence_playback_evidence_changed")
                    item.sentence_wait = None
                    item.sentence_wait_playback = None
                    self._cancel("sentence_expiry", "sentence_stop_ack")
                    await self._advance(item)
            return
        if isinstance(event, ObserveAssistantSpokenText):
            reply = self._revisions.reply
            if (event.playback_started and reply is not None
                    and event.context.response_id == reply.response_id
                    and event.context.turn_id == reply.turn_id
                    and event.context.generation == reply.generation):
                # Generation completion can precede the renderer's first playback
                # receipt. Keep the fact even after _response_id was released.
                self._revisions.observe_playback(reply.response_id)
            if (
                self._response_id is not None
                and event.context.generation == (self._response_context or self._context).generation
                and event.context.turn_id == (self._response_context or self._context).turn_id
                and event.context.response_id == self._response_id
            ):
                self._assistant_text = event.text
                self._response_playback_started |= event.playback_started
            return
        if isinstance(event, ObserveAssistantYielded):
            item = self._input
            if (
                item
                and item.yield_pending
                and event.context.generation == item.context.generation
                and event.context.turn_id == item.context.turn_id
                and event.context.response_id == item.target_response
            ):
                if self._response_id == item.target_response:
                    self._response_id = None
                item.yield_pending = False
                item.yielded = True
                self._cancel("yield_ack")
                await self._advance(item)
                await self._project(item.context)
            return
        if isinstance(event, ObserveVadEvent):
            observation = event.event
            item = self._ensure_input(observation.context)
            if item.commit_pending:
                self._defer_input(event)
                return
            item.acoustic_version += 1
            item.vad_observed = True
            item.timestamp_us = max(item.timestamp_us, observation.audio_timestamp_us)
            if isinstance(observation, VadSpeechStarted):
                item.speech_started_ns = item.speech_started_ns or time.monotonic_ns()
                item.speech_ended_ns = None
                self._prefetch.invalidate("speech_resumed")
                if not item.started_us:
                    item.started_us = observation.audio_timestamp_us
                item.speech_active = True
                item.stop = None
                self._cancel("idle", "commit")
            elif isinstance(observation, VadSpeechStopped):
                item.speech_ended_ns = time.monotonic_ns() - max(0, observation.silence_duration_us) * 1000
                item.speech_active = False
                item.stop = observation
                if item.text:
                    if self._provider.semantic_chunks_enabled:
                        self._collect_chunks(item, force=True)
                    if item.target_response:
                        self._judge_interruption(item, InterruptionBoundary.SENTENCE_END)
                    await self._advance(item)
                else:
                    self._timer("idle", self._provider._asr_idle_stop_s * 1000, item)
            await self._project(observation.context)
            return
        if isinstance(event, ObserveAsrEvent):
            await self._asr(event.event)
            return
        raise TypeError(f"Unsupported coordinator event: {type(event).__name__}")

    async def _asr(self, event: Any) -> None:
        if isinstance(event, (AsrTranscriptFinal, AsrCommitRejected)):
            item = self._input
            if (
                item is None
                or item.blocked
                or not item.commit_pending
                or event.context.generation != item.context.generation
                or event.context.turn_id != item.context.turn_id
            ):
                return
            if isinstance(event, AsrTranscriptFinal):
                violation = self._provider.input_budget.violation(
                    event.text, revisions=item.observations + 1,
                    elapsed_ms=(time.monotonic_ns() - item.created_ns) / 1e6,
                )
                if violation:
                    self._begin_input_rejection(item, violation, event.text, observed_revision=event.revision)
                    return
                self._record_input_evidence(item, "asr_final", {
                    "text": event.text, "revision": event.revision,
                }, snapshot=event.text)
                if item.blocked:
                    return
                parent = self._last_committed
                association_error: str | None = None
                try:
                    association = self._provider.input_association_policy.associate(InputAssociationRequest(
                        text=event.text, previous_turn_id=parent[0] if parent else None,
                        verdict=item.verdict,
                    ))
                    if not isinstance(association, InputAssociation):
                        raise TypeError("association policy returned an unsupported result")
                    if association.related_turn_id is not None and (
                        parent is None or association.related_turn_id != parent[0]
                    ):
                        raise ValueError("input association must reference the current committed parent")
                    if association.continues_input and (parent is None or association.related_turn_id is None):
                        raise ValueError("input continuation requires an identified parent")
                except Exception as error:
                    association_error = type(error).__name__
                    logger.warning("Input association failed; retaining separate final input", exc_info=True)
                    association = InputAssociation(
                        InputRelation.UNRESOLVED if parent else InputRelation.NEW_TOPIC,
                        parent[0] if parent else None, "association_error",
                    )
                item.continuation_of_turn_id = association.related_turn_id if association.continues_input else None
                item.continuation_text = parent[1] if parent and association.continues_input else ""
                reply = self._revisions.reply
                supersedes_unplayed_reply = bool(association.continues_input and reply is not None
                    and parent is not None and reply.turn_id == parent[0] and not reply.playback_started
                    and reply.invalidation_reason != "journal_restored")
                committed_text = (
                    item.continuation_text + "\n" + event.text
                    if item.continuation_text else event.text
                )
                violation = self._provider.input_budget.violation(
                    committed_text, revisions=item.observations + 1,
                    elapsed_ms=(time.monotonic_ns() - item.created_ns) / 1e6,
                )
                if violation:
                    self._begin_input_rejection(item, violation, committed_text, observed_revision=event.revision)
                    return
                self._record_input_evidence(item, "input_associated", {
                    "relation": association.relation.value, "source": association.source,
                    "related_turn_id": association.related_turn_id,
                    "supersedes_unplayed_reply": supersedes_unplayed_reply,
                    "final_transcript_revision": event.revision,
                    "revision": event.revision,
                    "error_type": association_error,
                }, snapshot=committed_text)
                if item.blocked:
                    return
                committed_context = event.context
                if parent is not None and parent[0] == event.context.turn_id:
                    committed_context = replace(
                        event.context, turn_id=str(uuid.uuid4()), generation=event.context.generation + 1,
                    )
                if (association.relation is not InputRelation.NEW_TOPIC
                    and not (association.relation is InputRelation.SUPPLEMENT
                        and self._prefetch.matches_continuation(committed_text, committed_context.generation,
                            association.related_turn_id))):
                    self._prefetch.invalidate("input_association_finalized")
                self._prefetch.finalize(committed_text, committed_context.generation)
                self._deferred_context_repair = None
                version = self._revisions.commit_input(
                    input_id=item.identity, context=committed_context, text=committed_text,
                    transcript_revision=event.revision,
                    continuation_of_turn_id=item.continuation_of_turn_id,
                    admission_reason=item.admission_reason or "semantic_complete",
                )
                self._record_input_evidence(item, "input_committed", {
                    **asdict(version),
                    "input_revision": asdict(version),
                    "logical_input_id": version.input_id,
                    "revision": event.revision,
                    "endpoint_decision": item.endpoint.decision.value if item.endpoint else None,
                    "endpoint_source": item.endpoint.source if item.endpoint else None,
                }, snapshot=committed_text)
                if item.blocked:
                    return
                self._last_committed = (committed_context.turn_id, committed_text)
                self._awaiting_response = True
                await self._outbox.put(
                    UserTurnCommitted(
                        context=committed_context,
                        text=committed_text,
                        continuation_of_turn_id=item.continuation_of_turn_id,
                        transcript_revision=event.revision,
                        provider_endpoint_observed=item.provider_endpoint,
                        committed_at=datetime.now(UTC),
                        speech_ended_ns=item.speech_ended_ns,
                        input_id=version.input_id,
                        input_observation_id=version.observation_id,
                        input_version=version.input_version,
                        admission_reason=version.admission_reason,
                        endpoint_decision=item.endpoint.decision.value if item.endpoint else None,
                        endpoint_source=item.endpoint.source if item.endpoint else None,
                        input_relation=association.relation.value,
                        input_relation_source=association.source,
                        related_turn_id=association.related_turn_id,
                        supersedes_unplayed_reply=supersedes_unplayed_reply,
                    )
                )
            if isinstance(event, AsrCommitRejected):
                self._prefetch.invalidate("commit_rejected")
            self._input = None
            self._tasks.clear()
            deferred, self._deferred_input = self._deferred_input, []
            final_revision = event.revision if isinstance(event, AsrTranscriptFinal) else None
            for observation in deferred:
                # Final text already owns revisions through its acknowledged version.
                if (
                    isinstance(event, AsrTranscriptFinal)
                    and isinstance(observation, ObserveAsrEvent)
                    and isinstance(observation.event, (AsrTranscriptDelta, AsrEndpointHint, AsrTranscriptFinal))
                    and observation.event.context.generation == event.context.generation
                    and observation.event.context.turn_id == event.context.turn_id
                    and final_revision is not None
                    and observation.event.revision <= final_revision
                ):
                    continue
                await self._handle(observation)
            await self._project(event.context)
            return
        if not isinstance(event, (AsrTranscriptDelta, AsrEndpointHint)):
            return
        text = event.accumulated_text if isinstance(event, AsrTranscriptDelta) else event.text
        if self._response_context and event.context.generation < self._response_context.generation:
            return
        if (
            self._response_id
            and self._assistant_text
            and project_assistant_echo(text, self._assistant_text) is None
        ):
            await self._outbox.put(
                AsrDiscardRequested(context=event.context, reason="assistant_playback_echo")
            )
            return
        item = self._ensure_input(event.context)
        if item.blocked:
            return
        if self._evidence is not None and self._evidence.failure:
            self._begin_input_rejection(item, "input_evidence_unavailable", text, observed_revision=event.revision)
            return
        if item.commit_pending:
            violation = self._provider.input_budget.violation(
                text, revisions=item.observations + len(self._deferred_input) + 1,
                elapsed_ms=(time.monotonic_ns() - item.created_ns) / 1e6,
            )
            if violation:
                self._begin_input_rejection(item, violation, text, observed_revision=event.revision)
                return
            self._defer_input(ObserveAsrEvent(event=event))
            return
        if event.revision < item.revision:
            return
        changed = item.text != text or item.revision != event.revision
        observed_boundary = TextBoundary.SENTENCE_END if isinstance(event, AsrEndpointHint) else TextBoundary.PARTIAL
        if changed or item.boundary != observed_boundary:
            violation = self._provider.input_budget.violation(
                text, revisions=item.observations + 1,
                elapsed_ms=(time.monotonic_ns() - item.created_ns) / 1e6,
            )
            if violation:
                self._begin_input_rejection(item, violation, text, observed_revision=event.revision)
                return
            common = 0
            for previous, current in zip(item.evidence_text, text):
                if previous != current:
                    break
                common += 1
            receipt = self._record_input_evidence(item, "asr_revision", {
                "revision": event.revision, "boundary": "sentence_end" if isinstance(event, AsrEndpointHint) else "partial",
                "replace_from": common, "suffix": text[common:], "previous_item_id": item.evidence_id,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }, snapshot=text)
            if item.blocked:
                item.rejected_text = text
                return
            item.observations += 1
            item.evidence_text = text
            item.evidence_id = receipt.item_id if receipt is not None else None
        same_semantic_snapshot = (
            self._provider.semantic_chunks_enabled
            and semantic_text(item.text) == semantic_text(text)
        )
        previous_boundary = item.boundary
        item.boundary = (
            TextBoundary.SENTENCE_END
            if isinstance(event, AsrEndpointHint)
            else TextBoundary.PARTIAL
        )
        item.provider_endpoint |= isinstance(event, AsrEndpointHint)
        item.timestamp_us = max(item.timestamp_us, getattr(event, "audio_timestamp_us", 0))
        if changed:
            self._prefetch.observe_text(text)
            item.text, item.revision = text, event.revision
            if item.sentence_wait is not None and (
                not semantic_text(text).startswith(semantic_text(item.sentence_trigger_text))
                or not self._is_ordinary_supplement(item)
            ):
                await self._withdraw_sentence_wait(item, "supplement_revised")
            # The chunk scheduler deduplicates punctuation/whitespace-only updates.
            # Keep their accepted evidence because no replacement call will be issued.
            if not same_semantic_snapshot:
                item.endpoint = None
            if not same_semantic_snapshot and not item.yielded and not item.yield_pending:
                item.verdict = None
                item.verdict_prefix = None
            if not same_semantic_snapshot:
                self._cancel("commit")
            if not self._provider.semantic_chunks_enabled:
                self._cancel("interruption_model")
            self._judge_endpoint(item)
            self._timer("recovery", self._provider.recovery_timeout_ms, item)
        elif previous_boundary is not item.boundary:
            self._judge_endpoint(item)
        if item.target_response:
            boundary = (
                InterruptionBoundary.SENTENCE_END
                if isinstance(event, AsrEndpointHint)
                else InterruptionBoundary.PARTIAL
            )
            self._judge_interruption(item, boundary)
        if not item.speech_active:
            self._timer("idle", self._provider._asr_idle_stop_s * 1000, item)
        await self._advance(item)
        await self._project(event.context)

    def _log_chunk(self, item: _Input, chunk: SemanticChunk, event: str, detail: dict[str, Any]) -> None:
        if event != "sealed":
            self._record_input_evidence(item, "chunk_" + event, {
                "chunk_id": chunk.chunk_id, "chunk_text": chunk.text,
                "chunk_revision": chunk.revision,
                "semantic_end": chunk.semantic_end, "asr_evidence_id": item.evidence_id,
                **{key: value for key, value in detail.items() if key not in {"classified_text", "result"}},
            })
        if self._provider._debug_log is not None:
            self._provider._debug_log.log("interruption" if item.target_response else "eot", f"chunk_{event}", f"chunk {chunk.sequence}: {chunk.trigger}", generation=item.context.generation, turn_id=item.context.turn_id, detail={"chunk_id": chunk.chunk_id, "chunk_text": chunk.text, "revision": chunk.revision, "target_response_id": item.target_response, **detail})

    def _collect_chunks(self, item: _Input, *, stable: bool = False, force: bool = False) -> None:
        if item.chunks is None or not item.text or item.commit_pending or item.blocked:
            return
        if item.continuation_of_turn_id and item.target_response is None:
            return
        update = item.chunks.observe(item.text, revision=item.revision,
            stable=stable or item.boundary is TextBoundary.SENTENCE_END, force=force)
        if item.chunks.history_size > self._provider.input_budget.max_chunks:
            self._begin_input_rejection(item, "input_chunks", item.text)
            return
        for offset in range(0, len(update.sealed), 128):
            self._record_input_evidence(item, "chunks_sealed", {
                "asr_evidence_id": item.evidence_id,
                "chunks": [{"chunk_id": chunk.chunk_id, "text": chunk.text,
                            "semantic_end": chunk.semantic_end, "trigger": chunk.trigger}
                           for chunk in update.sealed[offset:offset + 128]],
            })
            if item.blocked:
                return
        for invalidated in update.invalidated_candidates:
            self._log_chunk(item, invalidated, "invalidated", {"reason": "asr_rewrite"})
            family = "interruption_model" if item.target_response else "endpoint_model"
            self._cancel(family + ":" + invalidated.chunk_id)
        for chunk in update.sealed:
            self._log_chunk(item, chunk, "sealed", {})
            if item.blocked:
                return
        if update.merged is not None:
            self._log_chunk(item, update.merged, "merged", {"source_chunk_ids": list(update.merged_sources)})
        if update.stability_changed:
            self._cancel("chunks")
            if item.chunks.stability_prefix is not None and not stable and not force:
                self._timer("chunks", self._provider.chunk_stability_ms, item)
        self._drain_chunks(item)
        if stable or force or item.boundary is TextBoundary.SENTENCE_END:
            self._maybe_prefetch(item)

    def _drain_chunks(self, item: _Input) -> None:
        if item.blocked or item.chunks is None or item.commit_pending or item.yield_pending or (item.yielded and item.floor_claim_confirmed):
            return
        while (chunk := item.chunks.begin_next()) is not None:
            cumulative_text = item.chunks.cumulative_text(chunk)
            if cumulative_text is None:
                raise RuntimeError("Semantic scheduler issued an invalid candidate")
            # Independent chunks trigger calls; EOT evaluates the cumulative meaning.
            candidate_text = chunk.text if item.target_response else cumulative_text
            frozen = replace(item, text=candidate_text, revision=chunk.revision, semantic_chunk=chunk,
                prior_chunks=item.chunks.context_before(chunk),
                chunk_feedback_only=item.chunks.feedback_only_before(chunk))
            self._log_chunk(item, chunk, "requested", {
                "classification_scope": "cumulative",
                "classified_text": cumulative_text,
                "prior_feedback_confirmed": frozen.chunk_feedback_only,
            })
            if item.blocked:
                return
            if item.target_response:
                boundary = InterruptionBoundary.SENTENCE_END if item.boundary is TextBoundary.SENTENCE_END or not item.speech_active else InterruptionBoundary.PARTIAL
                self._judge_interruption(frozen, boundary)
            else:
                self._judge_endpoint(frozen)

    def _judge_endpoint(self, item: _Input) -> None:
        if item.blocked:
            return
        if self._provider.semantic_chunks_enabled and item.semantic_chunk is None:
            self._collect_chunks(item)
            return
        if item.target_response is not None or item.continuation_of_turn_id:
            return  # Overlap input uses acoustic/ASR stopping, never semantic EOT.
        request = EotRequest(
            text=item.text,
            generation=item.context.generation,
            context=EotContext(self._history_snapshot()),
            interaction=item.context,
            input_state=SemanticInputState(
                chunk_id=item.semantic_chunk.chunk_id if item.semantic_chunk else None,
                chunk_trigger=item.semantic_chunk.trigger if item.semantic_chunk else None,
                previous_chunks=item.prior_chunks,
                transcript_revision=item.revision,
                boundary=item.boundary,
                speech_active=item.speech_active if item.vad_observed else None,
                dialogue_state=self._state,
                audio_timestamp_us=item.timestamp_us,
            ),
        )
        identity, revision = item.identity, item.revision
        token = str(uuid.uuid4())
        self._tasks.register("endpoint", item.semantic_chunk.chunk_id if item.semantic_chunk else None, token)

        async def judge() -> None:
            started_ns = time.monotonic_ns()
            outcome = TelemetryOutcome.OK
            classifier = self._provider._endpoint_gate._classifier
            try:
                if classifier:
                    result = await self._classify_eot_timed(
                        classifier, request, item.context.generation
                    )
                else:
                    result = EotClassification(EotDecision.COMPLETE, source="classifier_disabled")
            except asyncio.CancelledError:
                outcome = TelemetryOutcome.CANCELLED
                raise
            except Exception as error:
                outcome = TelemetryOutcome.TIMEOUT if isinstance(error, TimeoutError) else TelemetryOutcome.ERROR
                logger.warning("Endpoint model failed", exc_info=True)
                result = EotClassification(EotDecision.UNCERTAIN, source="classifier_error")
            finally:
                self._record_semantic_duration("turn_policy.eot_classify", item, started_ns, outcome)
            self._log_eot_decision(result, item)
            await self._inbox.put((_Result(identity, revision, "endpoint", result, token, item.semantic_chunk.chunk_id if item.semantic_chunk else None), None))

        self._job("endpoint_model" + (":" + item.semantic_chunk.chunk_id if item.semantic_chunk else ""), judge())

    def _record_semantic_duration(self, name: str, item: _Input, started_ns: int, outcome: TelemetryOutcome) -> None:
        if self._provider._telemetry is not None:
            self._provider._telemetry.record(
                name, generation=item.context.generation, turn_id=item.context.turn_id,
                kind=TelemetryKind.SPAN, outcome=outcome,
                duration_ms=(time.monotonic_ns() - started_ns) / 1_000_000,
            )

    async def _classify_eot_timed(
        self, classifier: Any, request: EotRequest, generation: int
    ) -> EotClassification:
        return await run_classification(
            lambda: classify_eot(classifier, request), operation="eot",
            executor=self._classifier_executor,
            timeout_s=self._provider._endpoint_gate._classifier_timeout_s,
            telemetry=self._provider._telemetry, generation=generation,
            attributes={"chunk_id": request.input_state.chunk_id,
                "chunk_trigger": request.input_state.chunk_trigger,
                "transcript_revision": request.input_state.transcript_revision},
        )

    def _log_eot_decision(self, result: EotClassification, item: _Input) -> None:
        debug_log = self._provider._debug_log
        if debug_log is None:
            return
        debug_log.log(
            "eot",
            "decision",
            f"EOT={result.decision.value} via {result.source}",
            generation=item.context.generation,
            turn_id=item.context.turn_id,
            detail={
                "confidence": result.confidence,
                "wait_ms": result.wait_ms,
                "text_length": len(item.text),
            },
        )

    def _rule_context(self, item: _Input, boundary: InterruptionBoundary) -> InterruptionRuleContext:
        return InterruptionRuleContext(text=item.text, boundary=boundary,
            assistant_text=item.assistant_text_at_onset,
            previous_chunks=item.prior_chunks if item.semantic_chunk is not None else (),
            previous_feedback_only=item.chunk_feedback_only, before_playback=item.before_playback)

    async def _classify_interruption_model(self, request: InterruptionRequest) -> InterruptionClassification:
        classifier = self._provider._semantic_interruption_classifier
        if classifier is not None:
            return await self._classify_interruption_timed(classifier, request, request.generation)
        item = self._input
        overlap_ms = max(0, item.timestamp_us - item.started_us) / 1000 if item else 0
        intent = await run_classification(
            lambda: self._provider._dual_intent_classifier.classify(
                generation=request.generation, overlap_ms=overlap_ms,
                text=request.cumulative_transcript or request.transcript),
            operation="interruption", executor=self._classifier_executor,
            timeout_s=self._provider._semantic_interruption_timeout_ms / 1000,
            telemetry=self._provider._telemetry, generation=request.generation,
            attributes={"classifier": "dual_intent", "chunk_id": request.input_state.chunk_id,
                "transcript_revision": request.input_state.transcript_revision},
        )
        return InterruptionClassification(InterruptionLabel.INTERRUPT if intent is DualIntent.FLOOR_CLAIM else InterruptionLabel.BACKCHANNEL, 1)

    def _judge_interruption(self, item: _Input, boundary: InterruptionBoundary) -> None:
        if item.blocked or item.floor_claim_confirmed:
            # STOP already locked this batch. Acoustic sealing must retain its
            # accepted verdict, rather than clearing it for an unusable rejudge.
            return
        if self._provider.semantic_chunks_enabled and item.semantic_chunk is None:
            if item.yielded or item.yield_pending:
                return
            rule = self._interruption_decider.match_rule(self._rule_context(item, boundary))
            if rule is not None and rule.label is InterruptionLabel.STOP:
                self._cancel("interruption_model", "chunks")
                if item.chunks is not None:
                    item.chunks.cancel_active()
                self._start_interruption_judge(item, InterruptionCandidate(item.text, item.context.generation, item.revision, boundary), rule)
            else:
                self._collect_chunks(item)
            return
        # A sentence boundary can change admission (e.g. partial "停" versus
        # final "停"); do not commit using evidence for the earlier boundary.
        item.verdict = None
        item.verdict_prefix = None
        candidate = InterruptionCandidate(
            item.text, item.context.generation, item.revision, boundary
        )
        rule = self._interruption_decider.match_rule(self._rule_context(item, boundary))
        if (
            boundary is InterruptionBoundary.PARTIAL
            and item.semantic_chunk is None
            and rule is None
            and len(item.text) - len(item.last_judged_text)
            < self._provider._semantic_interruption_partial_chars
        ):
            self._timer("interruption", self._provider._semantic_interruption_idle_ms, item)
            return
        self._start_interruption_judge(item, candidate, rule)

    def _start_interruption_judge(
        self,
        item: _Input,
        candidate: InterruptionCandidate,
        rule: InterruptionClassification | None,
    ) -> None:
        item.last_judged_text = item.text
        cumulative_text = (
            item.chunks.cumulative_text(item.semantic_chunk)
            if item.chunks is not None and item.semantic_chunk is not None
            else None
        )
        if item.semantic_chunk is not None and cumulative_text is None:
            raise RuntimeError("Interruption candidate has no valid cumulative snapshot")
        if cumulative_text is not None:
            candidate = replace(candidate, text=cumulative_text)
        request = InterruptionRequest(
            transcript=item.text,
            assistant_text=item.assistant_text_at_onset,
            generation=item.context.generation,
            boundary=candidate.boundary,
            history=self._history_snapshot(),
            interaction=item.context,
            input_state=SemanticInputState(
                chunk_id=item.semantic_chunk.chunk_id if item.semantic_chunk else None,
                chunk_trigger=item.semantic_chunk.trigger if item.semantic_chunk else None,
                previous_chunks=item.prior_chunks,
                transcript_revision=item.revision,
                boundary=TextBoundary(candidate.boundary.value),
                speech_active=item.speech_active if item.vad_observed else None,
            ),
            cumulative_transcript=cumulative_text,
        )
        identity, revision = item.identity, item.revision
        token = str(uuid.uuid4())
        self._tasks.register("interruption", item.semantic_chunk.chunk_id if item.semantic_chunk else None, token)
        async def judge() -> None:
            started_ns = time.monotonic_ns()
            outcome = TelemetryOutcome.OK
            source = "rule" if rule else "model"
            raw_classification = None
            try:
                decision = await self._interruption_decider.resolve(request, rule)
                result, source = decision.classification, decision.source
                raw_classification = result
                if result.confidence < self._provider._semantic_interruption_threshold:
                    result = InterruptionClassification(
                        InterruptionLabel.UNCERTAIN, result.confidence
                    )
            except asyncio.CancelledError:
                outcome = TelemetryOutcome.CANCELLED
                raise
            except Exception as error:
                outcome = TelemetryOutcome.TIMEOUT if isinstance(error, TimeoutError) else TelemetryOutcome.ERROR
                logger.warning("Interruption model failed", exc_info=True)
                result = InterruptionClassification(InterruptionLabel.UNCERTAIN, 0)
                source = "fallback"
            finally:
                self._record_semantic_duration("semantic_interruption.classify", item, started_ns, outcome)
            verdict = InterruptionVerdict(candidate, result, source)  # type: ignore[arg-type]
            self._log_interruption_decision(verdict, item, raw_classification=raw_classification)
            await self._inbox.put(
                (_Result(identity, revision, "interruption", verdict, token, item.semantic_chunk.chunk_id if item.semantic_chunk else None), None)
            )

        self._cancel("interruption")
        self._job("interruption_model" + (":" + item.semantic_chunk.chunk_id if item.semantic_chunk else ""), judge())

    async def _classify_interruption_timed(
        self, classifier: Any, request: InterruptionRequest, generation: int
    ) -> InterruptionClassification:
        return await run_classification(
            lambda: classify_interruption(classifier, request), operation="interruption",
            executor=self._classifier_executor,
            timeout_s=self._provider._semantic_interruption_timeout_ms / 1000,
            telemetry=self._provider._telemetry, generation=generation,
            attributes={"chunk_id": request.input_state.chunk_id,
                "chunk_trigger": request.input_state.chunk_trigger,
                "transcript_revision": request.input_state.transcript_revision},
        )

    def _log_interruption_decision(
        self, verdict: InterruptionVerdict, item: _Input,
        *, raw_classification: InterruptionClassification | None = None,
    ) -> None:
        debug_log = self._provider._debug_log
        if debug_log is None:
            return
        debug_log.log(
            "interruption",
            "decision",
            f"label={verdict.classification.label.value} source={verdict.source}",
            generation=item.context.generation,
            turn_id=item.context.turn_id,
            detail={
                "confidence": verdict.classification.confidence,
                "should_stop": verdict.should_stop,
                "creates_turn": verdict.creates_turn,
                "raw_label": raw_classification.label.value if raw_classification else None,
                "confidence_threshold": self._provider._semantic_interruption_threshold,
                "below_confidence_threshold": (
                    raw_classification.confidence < self._provider._semantic_interruption_threshold
                    if raw_classification else None
                ),
            },
        )

    def _is_ordinary_supplement(self, item: _Input) -> bool:
        if not item.text or self._last_committed is None:
            return False
        try:
            association = self._provider.input_association_policy.associate(InputAssociationRequest(
                text=item.text, previous_turn_id=self._last_committed[0], verdict=item.verdict))
            if (not isinstance(association, InputAssociation) or association.relation is not InputRelation.SUPPLEMENT
                or association.related_turn_id != self._last_committed[0]):
                return False
            # A supplement marker cannot conceal an explicit stop/correction
            # in a later clause. Reuse the existing pure policies; do not reopen JEV after STOP.
            for clause in re.split(r"(?<=[，,。.!！？?；;\n])", item.text):
                if not clause.strip():
                    continue
                relation = self._provider.input_association_policy.associate(InputAssociationRequest(
                    text=clause, previous_turn_id=self._last_committed[0]))
                rule = self._interruption_decider.match_rule(replace(
                    self._rule_context(item, InterruptionBoundary.SENTENCE_END), text=clause, previous_chunks=()))
                if (relation.relation is InputRelation.CORRECTION
                    or rule is not None and rule.label in {InterruptionLabel.STOP, InterruptionLabel.CORRECTION}):
                    return False
            return True
        except Exception:
            logger.warning("Supplement association failed; stopping immediately", exc_info=True)
            return False

    async def _withdraw_sentence_wait(self, item: _Input, reason: str) -> None:
        permit = item.sentence_wait
        if permit is None or item.sentence_revoked:
            return
        self._prefetch.invalidate(reason)
        self._revoke_response(permit.response_id, reason=reason)
        if not item.sentence_revoked:
            item.sentence_revoked = True
            await self._outbox.put(AssistantYieldRequested(
                context=replace(item.context, response_id=permit.response_id), reason=reason,
                revokes_sentence_permit_id=permit.permit_id))
        self._timer("sentence_stop_ack", self._provider.recovery_timeout_ms * 2 + 250, item)

    async def _yield(self, item: _Input) -> None:
        if item.yielded or item.yield_pending or item.target_response is None:
            return
        if self._response_id != item.target_response:
            item.yielded = True
            return
        item.floor_claim_confirmed = True
        item.yield_pending = True
        permit = None
        if item.sentence_wait is None and self._is_ordinary_supplement(item) and item.verdict is not None and item.verdict.label is InterruptionLabel.INTERRUPT and item.verdict.source != "fallback":
            permit = self._revisions.grant_current_sentence(item.target_response,
                trigger_input_id=item.identity, transcript_revision=item.revision, now_ns=time.monotonic_ns())
        if permit is not None:
            item.sentence_wait = permit
            item.sentence_prefetch_started = False
            item.sentence_revoked = False
            item.sentence_trigger_text = item.text
            item.sentence_wait_playback = self._revisions.reply.playback if self._revisions.reply is not None else None
            assert item.sentence_wait_playback is not None
            item.sentence_wait_initial_ns = item.sentence_wait_playback.observed_at_ns
        if permit is not None:
            self._prefetch.invalidate("sentence_handoff_wait")
            self._timer("sentence_expiry", (permit.expires_at_ns - time.monotonic_ns()) / 1e6, item)
        self._revoke_response(item.target_response, reason="barge_in_floor_claim")
        self._timer("yield_ack", self._provider.recovery_timeout_ms, item)
        await self._outbox.put(
            AssistantYieldRequested(
                context=replace(item.context, response_id=item.target_response),
                reason="barge_in_floor_claim",
                speech_started_ns=item.speech_started_ns,
                sentence_permit=permit,
            )
        )

    async def _advance(self, item: _Input, *, force: bool = False, admission_reason: str | None = None) -> None:
        if item.blocked or item.commit_pending or item.speech_active or item.stop is None or not item.text:
            return
        if item.sentence_wait is not None:
            self._maybe_prefetch(item)
            return
        if item.continuation_of_turn_id and item.target_response is None:
            return
        if item.target_response:
            if not force and not item.floor_claim_confirmed and (item.chunks is not None and item.chunks.busy):
                return  # Non-stopping prefix evidence cannot admit/discard the full input.
            if item.verdict is None and not force:
                return
            if item.verdict:
                if self._provider.semantic_chunks_enabled and not item.speech_active and semantic_text(item.verdict.candidate.text) == semantic_text(item.text):
                    item.verdict = replace(item.verdict, candidate=replace(item.verdict.candidate, boundary=InterruptionBoundary.SENTENCE_END))
                action = self._policy.interruption(item.verdict)
                explicit_stop = item.verdict.label is InterruptionLabel.STOP
                if (item.floor_claim_confirmed and item.yielded
                        and semantic_text(item.verdict.candidate.text) != semantic_text(item.text)):
                    # New text after a locked STOP is input admission, not a new
                    # stop decision for the already cancelled target. Exact pure
                    # controls/feedback still finish without creating a reply.
                    sealed_rule = self._interruption_decider.match_rule(
                        self._rule_context(item, InterruptionBoundary.SENTENCE_END))
                    explicit_stop = sealed_rule is not None and sealed_rule.label is InterruptionLabel.STOP
                    action = InterruptionDisposition(False, sealed_rule is None or sealed_rule.label
                        not in {InterruptionLabel.STOP, InterruptionLabel.BACKCHANNEL, InterruptionLabel.IGNORE})
                if (action.admit_input and not action.stop_response
                        and not item.floor_claim_confirmed and not item.yielded):
                    # Keep ambiguous input while playback owns the floor. Natural
                    # completion releases the floor without confirming interruption.
                    return
                question_answer = item.verdict.label is InterruptionLabel.BACKCHANNEL and any(
                    mark in item.assistant_text_at_onset for mark in ("?", "？")
                )
                if not action.admit_input and not question_answer:
                    if explicit_stop:
                        self._deferred_context_repair = None
                        reply = self._revisions.reply
                        if reply is not None:
                            self._revoke_response(reply.response_id, reason="semantic_stop")
                    if action.stop_response and not item.yielded:
                        await self._yield(item)
                        return
                    await self._outbox.put(
                        AsrDiscardRequested(
                            context=item.context, reason="semantic_control_or_feedback"
                        )
                    )
                    self._input = None
                    self._tasks.clear()
                    await self._project(item.context)
                    await self._resume_context_repair()
                    return
            if not item.yielded:
                await self._yield(item)
                return
        if item.target_response is None and item.endpoint is None and not force:
            return
        if item.target_response is None and not force and item.endpoint:
            delay = self._policy.endpoint_wait_ms(item.endpoint)
            if delay > 0:
                # One timer per version. Additional evidence cannot restart it.
                if "commit" not in self._jobs:
                    self._timer("commit", delay, item)
                return
        item.commit_pending = True
        item.admission_reason = admission_reason or (
            "interruption_confirmed" if item.floor_claim_confirmed else
            "deferred_overlap_after_playback" if item.target_response else "semantic_complete"
        )
        self._prefetch.cancel_pending()
        self._tasks.clear()
        self._timer("asr_final", self._provider.recovery_timeout_ms, item)
        await self._outbox.put(
            AsrCommitRequested(
                context=item.context,
                reason=(
                    "deferred_overlap_after_playback"
                    if item.target_response and item.yielded and not item.floor_claim_confirmed
                    else "coordinated_turn_commit"
                ),
                audio_end_timestamp_us=item.stop.audio_timestamp_us,
            )
        )
        await self._project(item.context)

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_owned(), name="coordinated-turn-close")
            self._close_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        await asyncio.shield(self._close_task)

    async def _close_owned(self) -> None:
        self._deferred_context_repair = None
        self._revisions.close()
        tasks = [self._actor, *self._all_jobs]
        for task in tasks:
            task.cancel()
        done, pending = await asyncio.wait(tasks, timeout=0.1)
        for task in done:
            if not task.cancelled():
                task.exception()
        if pending:
            logger.warning("Turn coordinator closed with %d uncooperative tasks", len(pending))
        self._tasks.clear()
        closers = [self._classifier_executor.close(), self._prefetch.close()]
        if self._evidence is not None:
            closers.append(self._evidence.close())
        try:
            results = await asyncio.gather(*closers, return_exceptions=True)
            errors = [result for result in results if isinstance(result, Exception)]
            if any(isinstance(result, asyncio.CancelledError) for result in results):
                errors.append(RuntimeError("turn coordinator resource close was cancelled before confirmation"))
            if isinstance(results[0], int) and results[0]:
                logger.warning("Turn coordinator closed with %d quarantined classifiers", results[0])
            if len(results) > 2 and isinstance(results[2], int) and results[2]:
                logger.warning("Input evidence closed with %d uncommitted records", results[2])
            if len(errors) == 1:
                raise errors[0]
            if errors:
                raise ExceptionGroup("turn coordinator resource close failed", errors)
        finally:
            self._input = None
            self._response_id = None
            # Independent queues/storage still terminate if prefetch close fails.
            while not self._outbox.empty():
                self._outbox.get_nowait()
            self._outbox.put_nowait(_CLOSED)
