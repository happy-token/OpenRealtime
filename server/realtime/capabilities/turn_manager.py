"""Typed Turn Manager authority and adapter for the existing Turn Policy seam."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

from server.conversation_journal import (
    ConversationItem,
    ConversationItemKind,
    ConversationVisibility,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.core.playback import CurrentSentencePermit
from server.core.reply_repair import ReplyRepairPermit
from server.core.turn_content import TurnContent
from server.realtime.capabilities.asr import (
    AsrCommitRejected,
    AsrEndpointHint,
    AsrEvent,
    AsrTranscriptDelta,
    AsrTranscriptFinal,
)
from server.realtime.capabilities.assistant_echo import project_assistant_echo
from server.realtime.capabilities.vad import VadEvent, VadSpeechStarted, VadSpeechStopped
from server.realtime.protocol.playback import ReplyPlayback
from server.turn_policy.dual_intent import (
    DefaultDualIntentClassifier,
    DualIntent,
    DualIntentClassifier,
)
from server.turn_policy.eot_classifier import EotClassifierLike, EotHistoryMessage
from server.turn_policy.policy import DialoguePolicy
from server.turn_policy.semantic_endpoint import (
    EndpointActivity,
    EndpointCandidate,
    EndpointResolution,
    EndpointStop,
    SemanticEndpointGate,
    endpoint_stability_wait_ms,
)
from server.turn_policy.semantic_input import SemanticInputState, TextBoundary
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionCandidate,
    InterruptionClassifierLike,
    InterruptionVerdict,
    SemanticInterruptionGate,
    completed_interruption_creates_turn,
)
from server.turn_policy.signals import ResponseAction, Signal
from server.turn_policy.states import DialogueState

_CLOSED = object()
logger = logging.getLogger(__name__)


class ResponsePrefetcher(Protocol):
    async def prepare(self, turn: TurnContent) -> bool: ...

    async def invalidate(self, generation: int, *, reason: str) -> bool: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveVadEvent:
    event: VadEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveAsrEvent:
    event: AsrEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveSystemResponseCompleted:
    response_id: str
    context: InteractionContext | None = None

    def __post_init__(self) -> None:
        if not self.response_id:
            raise ValueError("completed response identity must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveSystemResponseStarted:
    response_id: str
    context: InteractionContext | None = None
    preparing: bool = False
    repair: ReplyRepairPermit | None = None

    def __post_init__(self) -> None:
        if not self.response_id:
            raise ValueError("started response identity must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveResponseInvalidated:
    context: InteractionContext
    response_id: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveResponseRepairReady:
    context: InteractionContext
    response_id: str
    minimum_thread_sequence: int
    deadline_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplyRepairRequested:
    context: InteractionContext
    permit: ReplyRepairPermit


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveAssistantYielded:
    context: InteractionContext


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveAssistantSpokenText:
    context: InteractionContext
    text: str
    playback_started: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveAssistantPlayback:
    context: InteractionContext
    response_id: str
    fact: ReplyPlayback


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveConversationItem:
    item: ConversationItem


@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantYieldRequested:
    context: InteractionContext
    reason: str
    speech_started_ns: int | None = None
    sentence_permit: CurrentSentencePermit | None = None
    revokes_sentence_permit_id: str | None = None

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("assistant yield reason must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class DialogueStateChanged:
    context: InteractionContext
    from_state: DialogueState
    to_state: DialogueState
    transition: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class AsrCommitRequested:
    context: InteractionContext
    reason: str
    audio_end_timestamp_us: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AsrDiscardRequested:
    context: InteractionContext
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("ASR discard reason must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticInputRejected:
    context: InteractionContext
    reason: str
    evidence_id: str | None
    evidence_saved: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class UserTurnCommitted:
    context: InteractionContext
    text: str
    transcript_revision: int
    provider_endpoint_observed: bool
    committed_at: datetime
    continuation_of_turn_id: str | None = None
    speech_ended_ns: int | None = None
    input_id: str | None = None
    input_observation_id: str | None = None
    input_version: int | None = None
    admission_reason: str | None = None
    endpoint_decision: str | None = None
    endpoint_source: str | None = None
    input_relation: str | None = None
    input_relation_source: str | None = None
    related_turn_id: str | None = None
    supersedes_unplayed_reply: bool = False

    def __post_init__(self) -> None:
        if not self.text or self.transcript_revision < 1:
            raise ValueError("committed user turn must carry revisioned text")
        if self.committed_at.tzinfo is None:
            raise ValueError("turn commit timestamp must be timezone-aware")


TurnManagerCommand = (
    ObserveVadEvent
    | ObserveAsrEvent
    | ObserveSystemResponseCompleted
    | ObserveSystemResponseStarted
    | ObserveAssistantYielded
    | ObserveAssistantSpokenText
    | ObserveAssistantPlayback
    | ObserveConversationItem
    | ObserveResponseInvalidated
    | ObserveResponseRepairReady
)
TurnManagerEvent = (
    DialogueStateChanged
    | AsrCommitRequested
    | AsrDiscardRequested
    | UserTurnCommitted
    | AssistantYieldRequested
    | SemanticInputRejected
    | ReplyRepairRequested
)


class TurnManagerCapabilitySession(Protocol):
    async def send(self, command: TurnManagerCommand) -> None: ...

    def events(self) -> AsyncIterator[TurnManagerEvent]: ...

    async def close(self) -> None: ...


class TurnManagerCapabilityProvider(Protocol):
    async def open(self, *, context: InteractionContext) -> TurnManagerCapabilitySession: ...


class LegacyTurnManagerCapabilityAdapter:
    def __init__(
        self,
        policy_factory: Callable[[], DialoguePolicy],
        *,
        dual_intent_classifier: DualIntentClassifier | None = None,
        semantic_interruption_classifier: InterruptionClassifierLike | None = None,
        semantic_interruption_partial_chars: int = 5,
        semantic_interruption_idle_ms: float = 100,
        semantic_interruption_threshold: float = 0.8,
        semantic_interruption_timeout_ms: float = 800,
        eot_classifier: EotClassifierLike | None = None,
        classifier_timeout_ms: float = 5000,
        asr_idle_stop_ms: float = 1000,
        late_asr_recovery_ms: float = 2000,
        incomplete_timeout_ms: float = 5000,
        uncertain_wait_ms: float = 300,
        history_max_messages: int = 8,
        history_max_chars: int = 4000,
        response_prefetcher: ResponsePrefetcher | None = None,
    ) -> None:
        if incomplete_timeout_ms < 0:
            raise ValueError("incomplete_timeout_ms must be non-negative")
        if asr_idle_stop_ms <= 0:
            raise ValueError("asr_idle_stop_ms must be positive")
        if late_asr_recovery_ms < 0:
            raise ValueError("late_asr_recovery_ms must be non-negative")
        if history_max_messages < 1:
            raise ValueError("history_max_messages must be positive")
        if history_max_chars < 1:
            raise ValueError("history_max_chars must be positive")
        self._policy_factory = policy_factory
        self._dual_intent_classifier = (
            dual_intent_classifier or DefaultDualIntentClassifier()
        )
        self._semantic_interruption_classifier = semantic_interruption_classifier
        self._semantic_interruption_partial_chars = semantic_interruption_partial_chars
        self._semantic_interruption_idle_ms = semantic_interruption_idle_ms
        self._semantic_interruption_threshold = semantic_interruption_threshold
        self._semantic_interruption_timeout_ms = semantic_interruption_timeout_ms
        self._endpoint_gate = SemanticEndpointGate(
            eot_classifier,
            classifier_timeout_ms=classifier_timeout_ms,
            uncertain_wait_ms=uncertain_wait_ms,
        )
        self._asr_idle_stop_s = asr_idle_stop_ms / 1000
        self._late_asr_recovery_us = round(late_asr_recovery_ms * 1000)
        self._incomplete_timeout_s = incomplete_timeout_ms / 1000
        self._uncertain_wait_ms = uncertain_wait_ms
        self._history_max_messages = history_max_messages
        self._history_max_chars = history_max_chars
        self._response_prefetcher = response_prefetcher

    async def open(
        self,
        *,
        context: InteractionContext,
    ) -> LegacyTurnManagerCapabilitySession:
        return LegacyTurnManagerCapabilitySession(
            context=context,
            policy=self._policy_factory(),
            dual_intent_classifier=self._dual_intent_classifier,
            semantic_interruption_classifier=self._semantic_interruption_classifier,
            semantic_interruption_partial_chars=self._semantic_interruption_partial_chars,
            semantic_interruption_idle_ms=self._semantic_interruption_idle_ms,
            semantic_interruption_threshold=self._semantic_interruption_threshold,
            semantic_interruption_timeout_ms=self._semantic_interruption_timeout_ms,
            endpoint_gate=self._endpoint_gate,
            asr_idle_stop_s=self._asr_idle_stop_s,
            late_asr_recovery_us=self._late_asr_recovery_us,
            incomplete_timeout_s=self._incomplete_timeout_s,
            uncertain_wait_ms=self._uncertain_wait_ms,
            history_max_messages=self._history_max_messages,
            history_max_chars=self._history_max_chars,
            response_prefetcher=self._response_prefetcher,
        )


@dataclass(slots=True)
class _PendingSemanticEndpoint:
    candidate: EndpointCandidate
    activity: EndpointActivity
    stop: EndpointStop
    stopped: VadSpeechStopped | None = None
    task: asyncio.Task[None] | None = None


class LegacyTurnManagerCapabilitySession:
    def __init__(
        self,
        *,
        context: InteractionContext,
        policy: DialoguePolicy,
        dual_intent_classifier: DualIntentClassifier,
        semantic_interruption_classifier: InterruptionClassifierLike | None,
        semantic_interruption_partial_chars: int,
        semantic_interruption_idle_ms: float,
        semantic_interruption_threshold: float,
        semantic_interruption_timeout_ms: float,
        endpoint_gate: SemanticEndpointGate,
        asr_idle_stop_s: float,
        late_asr_recovery_us: int,
        incomplete_timeout_s: float,
        uncertain_wait_ms: float,
        history_max_messages: int,
        history_max_chars: int,
        response_prefetcher: ResponsePrefetcher | None,
    ) -> None:
        self._context = context
        self._policy = policy
        self._dual_intent_classifier = dual_intent_classifier
        self._semantic_interruption_gate = (
            SemanticInterruptionGate(
                semantic_interruption_classifier,
                observer=self._observe_semantic_interruption_verdict,
                partial_chars=semantic_interruption_partial_chars,
                idle_ms=semantic_interruption_idle_ms,
                confidence_threshold=semantic_interruption_threshold,
                classifier_timeout_ms=semantic_interruption_timeout_ms,
            )
            if semantic_interruption_classifier is not None
            else None
        )
        self._endpoint_gate = endpoint_gate
        self._asr_idle_stop_s = asr_idle_stop_s
        self._late_asr_recovery_us = late_asr_recovery_us
        self._incomplete_timeout_s = incomplete_timeout_s
        self._uncertain_wait_ms = uncertain_wait_ms
        self._history_max_messages = history_max_messages
        self._history_max_chars = history_max_chars
        self._history: list[tuple[str, EotHistoryMessage]] = []
        self._history_chars = 0
        self._last_history_sequence = 0
        self._history_item_ids_by_sequence: dict[int, str] = {}
        self._response_prefetcher = response_prefetcher
        self._prefetched_generation: int | None = None
        self._events: asyncio.Queue[TurnManagerEvent | object] = asyncio.Queue(maxsize=64)
        self._provider_endpoint_revision = 0
        self._latest_transcript_text = ""
        self._latest_transcript_revision = 0
        self._latest_asr_audio_timestamp_us = 0
        self._pending_endpoint: _PendingSemanticEndpoint | None = None
        self._pending_acoustic_stop: VadSpeechStopped | None = None
        self._pending_acoustic_stop_source: str | None = None
        self._discard_asr_until_vad_onset = False
        self._asr_idle_task: asyncio.Task[None] | None = None
        self._endpoint_tasks: set[asyncio.Task[None]] = set()
        self._commit_pending = False
        self._overlap_started_us: int | None = None
        self._overlap_text = ""
        self._overlap_is_assistant_echo = False
        self._overlap_context: InteractionContext | None = None
        self._semantic_interruption_creates_turn: bool | None = None
        self._latest_assistant_text = ""
        self._pending_floor_stop: VadSpeechStopped | None = None
        self._floor_claim_pending = False
        self._assistant_yielded = False
        self._closed = False

    async def send(self, command: TurnManagerCommand) -> None:
        if self._closed:
            raise RuntimeError("Turn Manager capability session is closed")
        if isinstance(command, ObserveVadEvent):
            await self._observe_vad(command.event)
            return
        if isinstance(command, ObserveAsrEvent):
            await self._observe_asr(command.event)
            return
        if isinstance(command, ObserveSystemResponseCompleted):
            await self._evaluate(
                Signal.SYSTEM_EOT,
                context=command.context or self._context,
            )
            return
        if isinstance(command, ObserveSystemResponseStarted):
            if command.preparing:
                return
            await self._evaluate(
                Signal.PROACTIVE_TIMER,
                context=command.context or self._context,
            )
            return
        if isinstance(command, ObserveAssistantYielded):
            await self._observe_assistant_yielded(command.context)
            return
        if isinstance(command, ObserveAssistantSpokenText):
            self._latest_assistant_text = command.text
            return
        if isinstance(command, ObserveAssistantPlayback):
            return  # Legacy policy has no versioned sentence-delivery authority.
        if isinstance(command, ObserveConversationItem):
            self._observe_conversation_item(command.item)
            return
        raise TypeError(f"unsupported Turn Manager capability command: {type(command).__name__}")

    async def _observe_vad(self, event: VadEvent) -> None:
        if isinstance(event, VadSpeechStarted):
            await self._cancel_asr_idle_timer()
            self._discard_asr_until_vad_onset = False
            self._pending_acoustic_stop = None
            self._pending_acoustic_stop_source = None
            pending = self._pending_endpoint
            if pending is not None:
                pending.activity.invalidate("vad_speech")
                self._pending_endpoint = None
                await self._invalidate_prefetch(
                    pending.candidate.generation,
                    reason="vad_speech",
                )
            if self._policy.state is DialogueState.SPEAK:
                self._overlap_started_us = event.audio_timestamp_us
                self._overlap_text = ""
                self._overlap_is_assistant_echo = False
                self._overlap_context = event.context
                self._semantic_interruption_creates_turn = None
                if self._semantic_interruption_gate is not None:
                    await self._semantic_interruption_gate.begin(
                        generation=event.context.generation,
                        assistant_text=self._latest_assistant_text,
                        history=tuple(message for _, message in self._history),
                        interaction=event.context,
                        input_state=SemanticInputState(dialogue_state=DialogueState.DUAL),
                    )
                await self._evaluate(Signal.OVERLAP_DETECTED, context=event.context)
            else:
                await self._evaluate(Signal.USER_SPEECH_ONSET, context=event.context)
            return
        if isinstance(event, VadSpeechStopped):
            if self._floor_claim_pending:
                self._pending_floor_stop = event
                if self._assistant_yielded:
                    await self._finish_floor_claim()
                return
            if self._policy.state is DialogueState.DUAL:
                await self._classify_overlap(event)
                return
            await self._cancel_asr_idle_timer()
            self._pending_acoustic_stop = event
            self._pending_acoustic_stop_source = "vad_stop"
            if self._pending_endpoint is None and not self._latest_transcript_text:
                await self._evaluate(
                    Signal.USER_SPEECH_ABORTED,
                    context=event.context,
                )
                return
            if await self._confirm_semantic_endpoint(event):
                return
            await self._commit_vad_stop(event)

    async def _observe_asr(self, event: AsrEvent) -> None:
        if isinstance(event, AsrCommitRejected):
            if not self._commit_pending:
                return
            self._commit_pending = False
            self._latest_transcript_text = ""
            self._latest_transcript_revision = 0
            self._latest_asr_audio_timestamp_us = 0
            # USER_EOT_CONFIRMED moved the policy to SPEAK before the adapter
            # discovered that no transcript was available.  Close that empty
            # response cycle so a delayed provider revision can re-enter from
            # IDLE through the existing late-ASR recovery path.
            await self._evaluate(Signal.SYSTEM_EOT, context=event.context)
            await self._reset_semantic_interruption()
            return
        if isinstance(event, AsrEndpointHint):
            if self._discard_asr_until_vad_onset:
                # Drop the rest of this provider utterance, then re-arm ASR-only
                # onset recovery for a later phrase when acoustic VAD is weak.
                self._discard_asr_until_vad_onset = False
                return
            self._provider_endpoint_revision = max(
                self._provider_endpoint_revision,
                event.revision,
            )
            if self._commit_pending:
                # The ASR adapter deliberately waits for the provider's final
                # revision after the acoustic stop.  That endpoint still
                # belongs to the turn currently being committed; starting a
                # new semantic candidate here would manufacture another turn.
                self._latest_transcript_text = event.text
                self._latest_transcript_revision = event.revision
                return
            pending = await self._start_semantic_endpoint(
                context=event.context,
                text=event.text,
                revision=event.revision,
                boundary=TextBoundary.SENTENCE_END,
            )
            self._confirm_pending_acoustic_stop(pending)
            if self._pending_acoustic_stop is None:
                await self._arm_asr_idle_timer(
                    context=event.context,
                    text=event.text,
                    revision=event.revision,
                    audio_timestamp_us=self._latest_asr_audio_timestamp_us,
                )
            return
        if isinstance(event, AsrTranscriptDelta):
            if self._discard_asr_until_vad_onset:
                return
            if self._commit_pending:
                # VAD has closed the floor, but Doubao may still revise the
                # text while ``consume_transcript`` waits for ``definite``.
                # Treat it as an authoritative tail correction, not a fresh
                # SPEAK-side overlap/barge-in.  The final revision may also
                # reveal that a short, ambiguous overlap was only assistant
                # playback echo, so preserve that evidence for the commit
                # admission check below.
                self._latest_transcript_text = event.accumulated_text
                self._latest_transcript_revision = event.revision
                self._latest_asr_audio_timestamp_us = event.audio_timestamp_us
                if self._is_assistant_echo(event.accumulated_text):
                    self._overlap_is_assistant_echo = True
                return
            if self._policy.state is DialogueState.SPEAK:
                if self._is_assistant_echo(event.accumulated_text):
                    await self._events.put(
                        AsrDiscardRequested(
                            context=event.context,
                            reason="assistant_playback_echo",
                        )
                    )
                    return
                self._overlap_started_us = event.audio_timestamp_us
                self._overlap_text = ""
                self._overlap_is_assistant_echo = False
                self._overlap_context = event.context
                self._semantic_interruption_creates_turn = None
                if self._semantic_interruption_gate is not None:
                    await self._semantic_interruption_gate.begin(
                        generation=event.context.generation,
                        assistant_text=self._latest_assistant_text,
                        history=tuple(message for _, message in self._history),
                        interaction=event.context,
                        input_state=SemanticInputState(dialogue_state=DialogueState.DUAL),
                    )
                await self._evaluate(
                    Signal.OVERLAP_DETECTED,
                    context=event.context,
                )
            if (
                self._policy.state is DialogueState.DUAL
                and self._is_assistant_echo(event.accumulated_text)
            ):
                self._overlap_is_assistant_echo = True
                self._overlap_text = ""
                return
            if self._policy.state is DialogueState.IDLE:
                # A non-empty streaming ASR revision is itself strong evidence
                # that the user has the floor. This keeps the ASR-idle endpoint
                # fallback live when acoustic VAD misses a quiet/short onset.
                if not self._late_asr_is_current(event):
                    self._pending_acoustic_stop = None
                    self._pending_acoustic_stop_source = None
                    self._discard_asr_until_vad_onset = True
                    await self._events.put(
                        AsrDiscardRequested(
                            context=event.context,
                            reason="late_asr_after_aborted_vad",
                        )
                    )
                    return
                await self._evaluate(
                    Signal.USER_SPEECH_ONSET,
                    context=event.context,
                )
            if self._pending_acoustic_stop_source == "asr_idle":
                self._pending_acoustic_stop = None
                self._pending_acoustic_stop_source = None
            self._latest_transcript_text = event.accumulated_text
            self._latest_transcript_revision = event.revision
            self._latest_asr_audio_timestamp_us = event.audio_timestamp_us
            pending = self._pending_endpoint
            if pending is not None and (
                pending.candidate.transcript_revision != event.revision
                or pending.candidate.text != event.accumulated_text
            ):
                pending.activity.invalidate("asr_increment")
                self._pending_endpoint = None
                await self._invalidate_prefetch(
                    pending.candidate.generation,
                    reason="asr_increment",
                )
            if self._policy.state is DialogueState.DUAL:
                self._overlap_text = event.accumulated_text
                await self._classify_overlap_delta(event)
            if self._pending_acoustic_stop is not None:
                pending = await self._start_semantic_endpoint(
                    context=event.context,
                    text=event.accumulated_text,
                    revision=event.revision,
                )
                self._confirm_pending_acoustic_stop(pending)
            else:
                await self._arm_asr_idle_timer(
                    context=event.context,
                    text=event.accumulated_text,
                    revision=event.revision,
                    audio_timestamp_us=event.audio_timestamp_us,
                )
            return
        if isinstance(event, AsrTranscriptFinal):
            if not self._commit_pending:
                raise ValueError("ASR final arrived without a Turn Manager commit decision")
            self._commit_pending = False
            committed_text = self._latest_transcript_text or event.text
            self._latest_transcript_text = ""
            self._latest_transcript_revision = 0
            self._latest_asr_audio_timestamp_us = 0
            if self._is_assistant_echo(committed_text):
                # A short early partial can look like a real interruption and
                # make the assistant yield before ASR supplies enough text to
                # identify its own playback.  The provider final is the last
                # authoritative admission point: suppress the false user turn
                # and close the empty response cycle instead of invoking the
                # Brain with the assistant's words.
                await self._evaluate(Signal.SYSTEM_EOT, context=event.context)
                await self._reset_semantic_interruption()
                return
            await self._events.put(
                UserTurnCommitted(
                    context=event.context,
                    text=committed_text,
                    transcript_revision=event.revision,
                    provider_endpoint_observed=(self._provider_endpoint_revision >= event.revision),
                    committed_at=datetime.now(UTC),
                )
            )
            await self._reset_semantic_interruption()

    def _late_asr_is_current(self, event: AsrTranscriptDelta) -> bool:
        stopped = self._pending_acoustic_stop
        if stopped is None or self._pending_acoustic_stop_source != "vad_stop":
            return True
        delay_us = max(0, event.audio_timestamp_us - stopped.audio_timestamp_us)
        return delay_us <= self._late_asr_recovery_us

    async def _start_semantic_endpoint(
        self,
        *,
        context: InteractionContext,
        text: str,
        revision: int,
        boundary: TextBoundary = TextBoundary.PARTIAL,
    ) -> _PendingSemanticEndpoint:
        candidate = EndpointCandidate(
            text=text,
            generation=context.generation,
            transcript_revision=revision,
            history=tuple(message for _, message in self._history),
            interaction=context,
            input_state=SemanticInputState(transcript_revision=revision,
                boundary=boundary, dialogue_state=self._policy.state,
                speech_active=False if self._pending_acoustic_stop_source == "vad_stop" else None,
                silence_duration_ms=(self._pending_acoustic_stop.silence_duration_us / 1000
                    if self._pending_acoustic_stop is not None and self._pending_acoustic_stop_source == "vad_stop" else None),
                audio_timestamp_us=self._latest_asr_audio_timestamp_us),
        )
        current = self._pending_endpoint
        if current is not None and current.candidate == candidate:
            return current
        if current is not None:
            current.activity.invalidate("asr_increment")
        pending = _PendingSemanticEndpoint(
            candidate=candidate,
            activity=EndpointActivity(),
            stop=EndpointStop(),
        )
        self._pending_endpoint = pending
        if (
            self._response_prefetcher is not None
            and self._prefetched_generation != context.generation
        ):
            try:
                await self._response_prefetcher.prepare(
                    TurnContent(text=text, generation=context.generation)
                )
                self._prefetched_generation = context.generation
            except Exception:
                logger.warning("Realtime response prefetch failed", exc_info=True)
        task = asyncio.create_task(
            self._resolve_semantic_endpoint(pending),
            name=f"realtime-semantic-endpoint-{context.generation}-{revision}",
        )
        pending.task = task
        self._endpoint_tasks.add(task)
        task.add_done_callback(self._endpoint_tasks.discard)
        return pending

    def _observe_conversation_item(self, item: ConversationItem) -> None:
        known_item_id = self._history_item_ids_by_sequence.get(item.sequence)
        if item.sequence <= self._last_history_sequence:
            if known_item_id != item.item_id:
                return
        else:
            self._last_history_sequence = item.sequence
            self._history_item_ids_by_sequence[item.sequence] = item.item_id
            oldest_refreshable = max(
                0,
                self._last_history_sequence - max(32, self._history_max_messages * 4),
            )
            self._history_item_ids_by_sequence = {
                sequence: item_id
                for sequence, item_id in self._history_item_ids_by_sequence.items()
                if sequence >= oldest_refreshable
            }

        existing_index = next(
            (
                index
                for index, (item_id, _message) in enumerate(self._history)
                if item_id == item.item_id
            ),
            None,
        )
        if existing_index is not None:
            _, previous = self._history.pop(existing_index)
            self._history_chars -= len(previous.content)
        if ConversationVisibility.MODEL not in item.visibility:
            return
        role: Literal["user", "assistant"]
        if item.kind is ConversationItemKind.USER_INPUT:
            role = "user"
        elif item.kind is ConversationItemKind.ASSISTANT_OUTPUT:
            role = "assistant"
        else:
            return
        content = "\n".join(
            part.text.strip()
            for part in item.content
            if isinstance(part, TextContent) and part.text.strip()
        )
        if not content:
            return
        truncated = len(content) > self._history_max_chars
        if truncated:
            content = content[: self._history_max_chars]
        message = EotHistoryMessage(role=role, content=content, truncated=truncated)
        if role == "assistant":
            self._latest_assistant_text = content
        self._history.append((item.item_id, message))
        self._history.sort(
            key=lambda entry: next(
                (
                    sequence
                    for sequence, item_id in self._history_item_ids_by_sequence.items()
                    if item_id == entry[0]
                ),
                self._last_history_sequence,
            )
        )
        self._history_chars += len(content)
        while len(self._history) > self._history_max_messages:
            _, removed = self._history.pop(0)
            self._history_chars -= len(removed.content)
        minimum_messages = min(2, self._history_max_messages, self._history_max_chars)
        while self._history_chars > self._history_max_chars and len(self._history) > minimum_messages:
            _, removed = self._history.pop(0)
            self._history_chars -= len(removed.content)
        if self._history_chars > self._history_max_chars and len(self._history) == 2:
            # Preserve both sides of the latest exchange instead of letting a
            # long assistant answer evict the preceding user message.
            first_id, first = self._history[0]
            second_id, second = self._history[1]
            first_budget = min(len(first.content), max(1, self._history_max_chars // 2))
            second_budget = min(len(second.content), self._history_max_chars - first_budget)
            first_budget = min(len(first.content), self._history_max_chars - second_budget)
            self._history = [
                (first_id, replace(first, content=first.content[:first_budget],
                    truncated=first.truncated or len(first.content) > first_budget)),
                (second_id, replace(second, content=second.content[:second_budget],
                    truncated=second.truncated or len(second.content) > second_budget)),
            ]
            self._history_chars = first_budget + second_budget

    async def _confirm_semantic_endpoint(self, event: VadSpeechStopped) -> bool:
        self._pending_acoustic_stop = event
        self._pending_acoustic_stop_source = "vad_stop"
        pending = self._pending_endpoint
        if pending is None and self._latest_transcript_text:
            pending = await self._start_semantic_endpoint(
                context=event.context,
                text=self._latest_transcript_text,
                revision=max(1, self._latest_transcript_revision),
            )
        if pending is None:
            return False
        pending.stopped = event
        pending.stop.confirm("vad_stop")
        return True

    def _confirm_pending_acoustic_stop(
        self,
        pending: _PendingSemanticEndpoint,
    ) -> None:
        stopped = self._pending_acoustic_stop
        if stopped is None:
            return
        pending.stopped = stopped
        pending.stop.confirm(self._pending_acoustic_stop_source or "vad_stop")

    async def _arm_asr_idle_timer(
        self,
        *,
        context: InteractionContext,
        text: str,
        revision: int,
        audio_timestamp_us: int,
    ) -> None:
        await self._cancel_asr_idle_timer()
        self._asr_idle_task = asyncio.create_task(
            self._fire_asr_idle_stop(
                context=context,
                text=text,
                revision=revision,
                audio_timestamp_us=audio_timestamp_us,
            ),
            name=f"realtime-asr-idle-{context.generation}-{revision}",
        )

    async def _fire_asr_idle_stop(
        self,
        *,
        context: InteractionContext,
        text: str,
        revision: int,
        audio_timestamp_us: int,
    ) -> None:
        try:
            await asyncio.sleep(self._asr_idle_stop_s)
            if (
                self._closed
                or self._latest_transcript_revision != revision
                or self._latest_transcript_text != text
                or self._pending_acoustic_stop is not None
            ):
                return
            stopped = VadSpeechStopped(
                context=context,
                audio_timestamp_us=audio_timestamp_us,
                silence_duration_us=round(self._asr_idle_stop_s * 1_000_000),
            )
            if self._floor_claim_pending:
                self._pending_floor_stop = stopped
                if self._assistant_yielded:
                    await self._finish_floor_claim()
                return
            if self._policy.state is DialogueState.DUAL:
                await self._classify_overlap(stopped)
                return
            self._pending_acoustic_stop = stopped
            self._pending_acoustic_stop_source = "asr_idle"
            pending = await self._start_semantic_endpoint(
                context=context,
                text=text,
                revision=revision,
            )
            self._confirm_pending_acoustic_stop(pending)
        finally:
            if self._asr_idle_task is asyncio.current_task():
                self._asr_idle_task = None

    async def _cancel_asr_idle_timer(self) -> None:
        task = self._asr_idle_task
        self._asr_idle_task = None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _resolve_semantic_endpoint(
        self,
        pending: _PendingSemanticEndpoint,
    ) -> None:
        outcome = await self._endpoint_gate.resolve(
            pending.candidate,
            pending.activity,
            pending.stop,
        )
        if self._pending_endpoint is not pending:
            return
        resolution = outcome.resolution
        if resolution in {
            EndpointResolution.HOLD_INCOMPLETE,
            EndpointResolution.HOLD_UNCERTAIN,
        }:
            wait_ms = endpoint_stability_wait_ms(
                outcome,
                incomplete_timeout_ms=self._incomplete_timeout_s * 1000,
                uncertain_wait_ms=self._uncertain_wait_ms,
            )
            stable = await self._wait_for_endpoint_stability(
                pending,
                timeout_s=wait_ms / 1000,
            )
            resolution = (
                EndpointResolution.COMMIT
                if stable
                else EndpointResolution.DEFER_ACTIVITY
            )
        if self._pending_endpoint is not pending:
            return
        self._pending_endpoint = None
        if resolution is EndpointResolution.COMMIT and pending.stopped is not None:
            await self._commit_vad_stop(pending.stopped)
        elif resolution is not EndpointResolution.COMMIT:
            await self._invalidate_prefetch(
                pending.candidate.generation,
                reason="semantic_endpoint_deferred",
            )

    async def _invalidate_prefetch(self, generation: int, *, reason: str) -> None:
        if self._response_prefetcher is None:
            return
        try:
            await self._response_prefetcher.invalidate(generation, reason=reason)
        except Exception:
            logger.warning("Realtime response prefetch invalidation failed", exc_info=True)
        finally:
            if self._prefetched_generation == generation:
                self._prefetched_generation = None

    async def _wait_for_endpoint_stability(
        self,
        pending: _PendingSemanticEndpoint,
        *,
        timeout_s: float,
    ) -> bool:
        if timeout_s <= 0:
            return not pending.activity.invalidated
        try:
            await asyncio.wait_for(pending.activity.wait(), timeout=timeout_s)
        except TimeoutError:
            return self._pending_endpoint is pending and not pending.activity.invalidated
        return False

    async def _commit_vad_stop(self, event: VadSpeechStopped) -> None:
        await self._cancel_asr_idle_timer()
        self._pending_acoustic_stop = None
        self._pending_acoustic_stop_source = None
        transition = await self._evaluate(
            Signal.USER_EOT_CONFIRMED,
            context=event.context,
        )
        await self._request_asr_commit(event, transition=transition)

    async def _classify_overlap(self, event: VadSpeechStopped) -> None:
        started_us = self._overlap_started_us
        if started_us is None:
            raise ValueError("DUAL state has no overlap start timestamp")
        assistant_echo = self._overlap_is_assistant_echo
        overlap_has_text = bool(self._overlap_text)
        if assistant_echo:
            intent = DualIntent.BACKCHANNEL
        elif self._semantic_interruption_gate is not None and self._overlap_text:
            self._pending_floor_stop = event
            verdict = await self._semantic_interruption_gate.resolve(
                InterruptionCandidate(
                    text=self._overlap_text,
                    generation=event.context.generation,
                    transcript_revision=max(1, self._latest_transcript_revision),
                    boundary=InterruptionBoundary.SENTENCE_END,
                )
            )
            if self._policy.state is not DialogueState.DUAL:
                # A partial semantic verdict may have requested the yield
                # while the sentence-end classification was in flight. Reuse
                # this stop as the pending floor latch; requesting another
                # yield would create a duplicate floor-claim cycle.
                if self._floor_claim_pending:
                    self._pending_floor_stop = event
                    if self._assistant_yielded:
                        await self._finish_floor_claim()
                return
            creates_turn = completed_interruption_creates_turn(verdict)
            if verdict is None or verdict.should_stop or creates_turn:
                self._semantic_interruption_creates_turn = creates_turn
                await self._request_assistant_yield(event.context)
                return
            self._pending_floor_stop = None
            intent = DualIntent.BACKCHANNEL
        else:
            intent = await self._dual_intent_classifier.classify(
                generation=event.context.generation,
                overlap_ms=max(0, event.audio_timestamp_us - started_us) / 1_000,
                text=self._overlap_text,
            )
        self._overlap_started_us = None
        self._overlap_text = ""
        self._overlap_is_assistant_echo = False
        if intent is DualIntent.BACKCHANNEL:
            await self._evaluate(Signal.BACKCHANNEL, context=event.context)
            if assistant_echo or overlap_has_text:
                await self._events.put(
                    AsrDiscardRequested(
                        context=event.context,
                        reason=(
                            "assistant_playback_echo"
                            if assistant_echo
                            else "semantic_backchannel"
                        ),
                    )
                )
            await self._reset_semantic_interruption()
            return
        self._pending_floor_stop = event
        await self._request_assistant_yield(event.context)

    async def _classify_overlap_delta(self, event: AsrTranscriptDelta) -> None:
        started_us = self._overlap_started_us
        if started_us is None or event.audio_timestamp_us == 0:
            return
        if self._semantic_interruption_gate is not None:
            await self._semantic_interruption_gate.observe(
                InterruptionCandidate(
                    text=event.accumulated_text,
                    generation=event.context.generation,
                    transcript_revision=event.revision,
                    boundary=InterruptionBoundary.PARTIAL,
                )
            )
            return
        intent = await self._dual_intent_classifier.classify(
            generation=event.context.generation,
            overlap_ms=max(0, event.audio_timestamp_us - started_us) / 1_000,
            text=event.accumulated_text,
        )
        if intent is DualIntent.FLOOR_CLAIM:
            await self._request_assistant_yield(event.context)

    async def _observe_semantic_interruption_verdict(
        self,
        verdict: InterruptionVerdict,
    ) -> None:
        gate = self._semantic_interruption_gate
        if (
            gate is None
            or not gate.is_current(verdict)
            or self._policy.state is not DialogueState.DUAL
            or not verdict.should_stop
        ):
            return
        context = self._overlap_context
        if context is None:
            return
        self._semantic_interruption_creates_turn = verdict.creates_turn
        await self._request_assistant_yield(context)

    async def _reset_semantic_interruption(self) -> None:
        gate = self._semantic_interruption_gate
        if gate is not None:
            await gate.reset()
        self._overlap_context = None
        self._semantic_interruption_creates_turn = None

    def _is_assistant_echo(self, text: str) -> bool:
        return project_assistant_echo(text, self._latest_assistant_text) is None

    async def _request_assistant_yield(self, context: InteractionContext) -> None:
        if self._floor_claim_pending:
            return
        self._floor_claim_pending = True
        self._assistant_yielded = False
        self._overlap_started_us = None
        self._overlap_text = ""
        await self._evaluate(Signal.FLOOR_CLAIM, context=context)
        await self._events.put(
            AssistantYieldRequested(
                context=context,
                reason="barge_in_floor_claim",
            )
        )

    async def _observe_assistant_yielded(self, context: InteractionContext) -> None:
        if not self._floor_claim_pending:
            raise ValueError("assistant yielded without a pending floor claim")
        self._assistant_yielded = True
        if self._pending_floor_stop is not None:
            await self._finish_floor_claim(context=context)

    async def _finish_floor_claim(
        self,
        *,
        context: InteractionContext | None = None,
    ) -> None:
        stopped = self._pending_floor_stop
        if stopped is None:
            return
        await self._refresh_semantic_turn_admission(stopped)
        self._pending_floor_stop = None
        self._floor_claim_pending = False
        self._assistant_yielded = False
        if self._semantic_interruption_creates_turn is False:
            await self._evaluate(
                Signal.SEMANTIC_TURN_SUPPRESSED,
                context=context or stopped.context,
            )
            await self._events.put(
                AsrDiscardRequested(
                    context=stopped.context,
                    reason="semantic_interruption_suppressed",
                )
            )
            await self._reset_semantic_interruption()
            return
        if self._latest_transcript_text:
            # Interruption classification owns playback admission, not EOT.
            # An admitted barge-in may still be an unfinished utterance, so
            # route it through the same semantic endpoint latch as ordinary
            # listening instead of manufacturing a response immediately.
            await self._confirm_semantic_endpoint(stopped)
            await self._reset_semantic_interruption()
            return
        transition = await self._evaluate(
            Signal.USER_EOT_CONFIRMED,
            context=context or stopped.context,
        )
        await self._request_asr_commit(stopped, transition=transition)

    async def _refresh_semantic_turn_admission(
        self,
        stopped: VadSpeechStopped,
    ) -> None:
        """Re-evaluate the final revision after an early playback yield.

        The user can continue speaking after an initial ``stop`` partial.  The
        final ASR revision, not the early partial, owns whether a new turn is
        admitted.
        """

        gate = self._semantic_interruption_gate
        text = self._latest_transcript_text
        if gate is None or not text.strip() or self._overlap_is_assistant_echo:
            return
        verdict = await gate.resolve(
            InterruptionCandidate(
                text=text,
                generation=stopped.context.generation,
                transcript_revision=max(1, self._latest_transcript_revision),
                boundary=InterruptionBoundary.SENTENCE_END,
            )
        )
        self._semantic_interruption_creates_turn = (
            completed_interruption_creates_turn(verdict)
        )

    async def _request_asr_commit(self, event: VadSpeechStopped, *, transition) -> None:
        if transition is None or transition.action is not ResponseAction.RESPOND:
            return
        self._commit_pending = True
        await self._events.put(
            AsrCommitRequested(
                context=event.context,
                reason="turn_manager_commit",
                audio_end_timestamp_us=event.audio_timestamp_us,
            )
        )

    async def _evaluate(
        self,
        signal: Signal,
        *,
        context: InteractionContext,
    ):
        from_state = self._policy.state
        transition = await self._policy.evaluate(
            signal,
            generation=context.generation,
        )
        if transition is not None and transition.to_state is not from_state:
            await self._events.put(
                DialogueStateChanged(
                    context=context,
                    from_state=from_state,
                    to_state=transition.to_state,
                    transition=transition.name,
                    occurred_at=datetime.now(UTC),
                )
            )
        return transition

    async def events(self) -> AsyncIterator[TurnManagerEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            yield cast(TurnManagerEvent, event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._cancel_asr_idle_timer()
        pending = self._pending_endpoint
        self._pending_endpoint = None
        self._pending_acoustic_stop = None
        self._pending_acoustic_stop_source = None
        if pending is not None:
            pending.activity.invalidate("closed")
            await self._invalidate_prefetch(
                pending.candidate.generation,
                reason="turn_manager_closed",
            )
        for task in tuple(self._endpoint_tasks):
            if not task.done():
                task.cancel()
        if self._endpoint_tasks:
            await asyncio.gather(*tuple(self._endpoint_tasks), return_exceptions=True)
        if self._semantic_interruption_gate is not None:
            await self._semantic_interruption_gate.close()
        await self._events.put(_CLOSED)
