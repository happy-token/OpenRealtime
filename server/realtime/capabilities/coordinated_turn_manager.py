"""A session actor coordinating input, semantic evidence and assistant output.

Only the actor mutates lifecycle records. Models and timers return versioned
messages; they never mutate the actor or block the audio routing caller.
Canonical five-state events are a compatibility projection, not the authority.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from server.conversation_journal import ConversationItemKind, ConversationVisibility, TextContent
from server.core.interaction_context import InteractionContext
from server.observability.telemetry import SessionDebugLog, SessionTelemetry, TelemetryKind, TelemetryOutcome
from server.realtime.capabilities.asr import (
    AsrCommitRejected,
    AsrEndpointHint,
    AsrTranscriptDelta,
    AsrTranscriptFinal,
)
from server.realtime.capabilities.assistant_echo import project_assistant_echo
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    AsrDiscardRequested,
    AssistantYieldRequested,
    DialogueStateChanged,
    LegacyTurnManagerCapabilityAdapter,
    ObserveAsrEvent,
    ObserveAssistantSpokenText,
    ObserveAssistantYielded,
    ObserveConversationItem,
    ObserveSystemResponseCompleted,
    ObserveSystemResponseStarted,
    ObserveVadEvent,
    TurnManagerCommand,
    TurnManagerEvent,
    UserTurnCommitted,
)
from server.realtime.capabilities.vad import VadSpeechStarted, VadSpeechStopped
from server.turn_policy.coordination import (
    DefaultTurnCoordinationPolicy,
    FloorOwner,
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
from server.turn_policy.policy import TurnPolicy
from server.turn_policy.semantic_input import SemanticInputState, TextBoundary
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionCandidate,
    InterruptionClassification,
    InterruptionLabel,
    InterruptionRequest,
    InterruptionVerdict,
    classify_interruption,
    match_interruption_rule,
)
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
    yielded: bool = False
    yield_pending: bool = False
    commit_pending: bool = False
    provider_endpoint: bool = False
    boundary: TextBoundary = TextBoundary.PARTIAL
    started_us: int = 0
    last_judged_text: str = ""
    vad_observed: bool = False
    assistant_text_at_onset: str = ""
    before_playback: bool = False
    continuation_text: str = ""
    continuation_of_turn_id: str | None = None


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


@dataclass(frozen=True, slots=True)
class _Timer:
    identity: str
    revision: int
    acoustic_version: int
    kind: str


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
        telemetry: SessionTelemetry | None = None,
        debug_log: SessionDebugLog | None = None,
        **kwargs: Any,
    ) -> None:
        if args and (len(args) != 1 or args[0] is not TurnPolicy):
            raise ValueError("Use coordination_policy_factory to replace coordinator decisions")
        super().__init__(*(args or (TurnPolicy,)), **kwargs)
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
        self._context = context
        self._policy = provider.coordination_policy_factory()
        self._input: _Input | None = None
        self._response_id: str | None = None
        self._response_context: InteractionContext | None = None
        self._last_committed: tuple[str, str] | None = None
        self._awaiting_response = False
        self._response_playback_started = False
        self._assistant_text = ""
        self._history: dict[str, tuple[int, EotHistoryMessage]] = {}
        self._state = DialogueState.IDLE
        self._floor = FloorOwner.USER
        self._inbox: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        self._outbox: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._all_jobs: set[asyncio.Task[None]] = set()
        self._closed = False
        self._failure: Exception | None = None
        self._requests: dict[str, str] = {}
        self._deferred_input: list[ObserveVadEvent | ObserveAsrEvent] = []
        self._actor = asyncio.create_task(self._run(), name="turn-coordinator")

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
            self._cancel(*tuple(self._jobs))
            await self._outbox.put(_CLOSED)
        finally:
            if done is not None and not done.done():
                done.set_exception(RuntimeError("Turn coordinator stopped"))
            while not self._inbox.empty():
                _, done = self._inbox.get_nowait()
                if done is not None and not done.done():
                    done.set_exception(RuntimeError("Turn coordinator stopped"))

    def _job(self, key: str, operation: Any) -> None:
        previous = self._jobs.pop(key, None)
        if previous:
            previous.cancel()
        task = asyncio.create_task(operation, name=f"turn-{key}")
        self._jobs[key] = task
        self._all_jobs.add(task)
        task.add_done_callback(self._all_jobs.discard)

    def _cancel(self, *keys: str) -> None:
        for key in keys:
            task = self._jobs.pop(key, None)
            if task:
                task.cancel()

    def _timer(self, kind: str, delay_ms: float, item: _Input) -> None:
        if not math.isfinite(delay_ms) or delay_ms < 0:
            raise ValueError("coordination wait must be finite and non-negative")
        message = _Timer(item.identity, item.revision, item.acoustic_version, kind)

        async def wait() -> None:
            await asyncio.sleep(delay_ms / 1000)
            await self._inbox.put((message, None))

        self._job(kind, wait())

    def _current(self, message: _Result | _Timer) -> _Input | None:
        item = self._input
        return (
            item
            if (
                item
                and not item.commit_pending
                and item.identity == message.identity
                and item.revision == message.revision
            )
            else None
        )

    def _defer_input(self, event: ObserveVadEvent | ObserveAsrEvent) -> None:
        if len(self._deferred_input) >= 64:
            raise RuntimeError("Input observations overflowed during ASR finalization")
        self._deferred_input.append(event)

    def _ensure_input(self, context: InteractionContext) -> _Input:
        if self._input is None:
            self._input = _Input(str(uuid.uuid4()), context, self._response_id, assistant_text_at_onset=self._assistant_text)
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

    async def _handle(self, event: Any) -> None:
        if isinstance(event, (_Result, _Timer)):
            if isinstance(event, _Timer) and event.kind in {"asr_final", "yield_ack"}:
                pending = self._input
                if (
                    pending
                    and pending.identity == event.identity
                    and (
                        pending.commit_pending
                        if event.kind == "asr_final"
                        else pending.yield_pending
                    )
                ):
                    raise TimeoutError(f"Turn coordination missing {event.kind}")
                return
            item = self._current(event)
            if item is None:
                return
            if isinstance(event, _Result):
                if self._requests.get(event.kind) != event.token:
                    return
                if isinstance(event.value, EotClassification):
                    item.endpoint = event.value
                else:
                    item.verdict = event.value
                    action = self._policy.interruption(event.value)
                    if action.stop_response:
                        await self._yield(item)
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
                if item.target_response and not item.yielded:
                    await self._yield(item)
                item.endpoint = EotClassification(EotDecision.COMPLETE, source="recovery_deadline")
                await self._advance(item, force=True)
            elif event.acoustic_version == item.acoustic_version:
                if event.kind == "idle":
                    if item.speech_active:
                        return
                    if not item.text:
                        self._input = None
                        await self._project(item.context)
                        return
                    item.stop = item.stop or VadSpeechStopped(
                        context=item.context,
                        audio_timestamp_us=item.timestamp_us,
                        silence_duration_us=0,
                    )
                    await self._advance(item)
                elif event.kind == "commit":
                    await self._advance(item, force=True)
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
        if isinstance(event, ObserveSystemResponseStarted):
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
            self._response_id = event.response_id
            self._response_context = event.context
            self._assistant_text = ""
            self._response_playback_started = False
            item = self._input
            if item and not item.commit_pending and item.target_response != event.response_id:
                self._cancel("yield_ack", "interruption_model", "interruption", "endpoint_model", "commit")
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
                item.yield_pending = False
                item.verdict = None
                if item.continuation_of_turn_id and item.speech_active:
                    await self._yield(item)
                if item.text:
                    self._judge_interruption(item, InterruptionBoundary(item.boundary.value))
            self._awaiting_response = False
            if not event.preparing:
                await self._project(event.context or self._context)
            return
        if isinstance(event, ObserveSystemResponseCompleted):
            if event.response_id != self._response_id:
                return
            self._response_id = None
            if self._input and self._input.target_response == event.response_id:
                self._input.yielded = True
                self._input.yield_pending = False
                await self._advance(self._input)
            await self._project(event.context or self._context)
            return
        if isinstance(event, ObserveAssistantSpokenText):
            if (
                self._response_context is None
                or (event.context.generation == self._response_context.generation
                    and event.context.response_id == self._response_id)
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
                if not item.started_us:
                    item.started_us = observation.audio_timestamp_us
                item.speech_active = True
                item.stop = None
                self._cancel("idle", "commit")
                if item.continuation_of_turn_id and item.target_response:
                    await self._yield(item)
            elif isinstance(observation, VadSpeechStopped):
                item.speech_active = False
                item.stop = observation
                if item.text:
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
                or not item.commit_pending
                or event.context.generation != item.context.generation
                or event.context.turn_id != item.context.turn_id
            ):
                return
            if isinstance(event, AsrTranscriptFinal):
                committed_text = (
                    item.continuation_text + "\n" + event.text
                    if item.continuation_text else event.text
                )
                committed_context = event.context
                if item.continuation_of_turn_id == event.context.turn_id:
                    committed_context = replace(
                        event.context, turn_id=str(uuid.uuid4()), generation=event.context.generation + 1,
                    )
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
                    )
                )
            self._input = None
            self._cancel(*tuple(self._jobs))
            deferred, self._deferred_input = self._deferred_input, []
            for observation in deferred:
                # Final text already owns revisions through its acknowledged version.
                if (
                    isinstance(event, AsrTranscriptFinal)
                    and isinstance(observation, ObserveAsrEvent)
                    and observation.event.context.generation == event.context.generation
                    and observation.event.context.turn_id == event.context.turn_id
                    and observation.event.revision <= event.revision
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
        if item.commit_pending:
            self._defer_input(ObserveAsrEvent(event=event))
            return
        if event.revision < item.revision:
            return
        changed = item.text != text or item.revision != event.revision
        previous_boundary = item.boundary
        item.boundary = (
            TextBoundary.SENTENCE_END
            if isinstance(event, AsrEndpointHint)
            else TextBoundary.PARTIAL
        )
        item.provider_endpoint |= isinstance(event, AsrEndpointHint)
        item.timestamp_us = max(item.timestamp_us, getattr(event, "audio_timestamp_us", 0))
        if changed:
            item.text, item.revision = text, event.revision
            item.endpoint = None
            item.verdict = None
            self._cancel("commit", "interruption_model")
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

    def _judge_endpoint(self, item: _Input) -> None:
        if item.target_response is not None or item.continuation_of_turn_id:
            return  # Overlap input uses acoustic/ASR stopping, never semantic EOT.
        request = EotRequest(
            text=item.text,
            generation=item.context.generation,
            context=EotContext(self._history_snapshot()),
            interaction=item.context,
            input_state=SemanticInputState(
                transcript_revision=item.revision,
                boundary=item.boundary,
                speech_active=item.speech_active if item.vad_observed else None,
                dialogue_state=self._state,
                audio_timestamp_us=item.timestamp_us,
            ),
        )
        identity, revision = item.identity, item.revision
        token = str(uuid.uuid4())
        self._requests["endpoint"] = token

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
            await self._inbox.put((_Result(identity, revision, "endpoint", result, token), None))

        self._job("endpoint_model", judge())

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
        timeout_s = self._provider._endpoint_gate._classifier_timeout_s
        telemetry = self._provider._telemetry
        if telemetry is None:
            return await asyncio.wait_for(classify_eot(classifier, request), timeout_s)
        async with telemetry.provider_call(
            provider="eot_classifier",
            operation="classify",
            timeout_ms=timeout_s * 1000,
            generation=generation,
        ) as call:
            result = await asyncio.wait_for(classify_eot(classifier, request), timeout_s)
            call.mark_first_response()
            return result

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

    def _judge_interruption(self, item: _Input, boundary: InterruptionBoundary) -> None:
        # A sentence boundary can change admission (e.g. partial "停" versus
        # final "停"); do not commit using evidence for the earlier boundary.
        item.verdict = None
        candidate = InterruptionCandidate(
            item.text, item.context.generation, item.revision, boundary
        )
        rule = match_interruption_rule(item.text, boundary=boundary)
        if item.before_playback:
            if item.text.strip().startswith(("换个问题", "另一个问题", "新的问题", "重新开始")):
                item.continuation_text = ""
                item.continuation_of_turn_id = None
            if rule is None or rule.label is not InterruptionLabel.STOP:
                rule = InterruptionClassification(InterruptionLabel.INTERRUPT, 1)
        # Exact feedback words are not context-free: a question can invite "yes".
        question = any(mark in item.assistant_text_at_onset for mark in ("?", "？"))
        if (
            rule
            and rule.label is InterruptionLabel.BACKCHANNEL
            and (question or boundary is InterruptionBoundary.PARTIAL)
        ):
            rule = None
        if (
            boundary is InterruptionBoundary.PARTIAL
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
        request = InterruptionRequest(
            transcript=item.text,
            assistant_text=item.assistant_text_at_onset,
            generation=item.context.generation,
            boundary=candidate.boundary,
            history=self._history_snapshot(),
            interaction=item.context,
            input_state=SemanticInputState(
                transcript_revision=item.revision,
                boundary=TextBoundary(candidate.boundary.value),
                speech_active=item.speech_active if item.vad_observed else None,
            ),
        )
        identity, revision = item.identity, item.revision
        token = str(uuid.uuid4())
        self._requests["interruption"] = token
        overlap_ms = max(0, item.timestamp_us - item.started_us) / 1000

        async def judge() -> None:
            started_ns = time.monotonic_ns()
            outcome = TelemetryOutcome.OK
            source = "rule" if rule else "model"
            try:
                classifier = self._provider._semantic_interruption_classifier
                if rule is not None:
                    result = rule
                elif classifier is not None:
                    result = await self._classify_interruption_timed(
                        classifier, request, item.context.generation
                    )
                else:
                    intent = await asyncio.wait_for(
                        self._provider._dual_intent_classifier.classify(
                            generation=request.generation,
                            overlap_ms=overlap_ms,
                            text=request.transcript,
                        ),
                        self._provider._semantic_interruption_timeout_ms / 1000,
                    )
                    result = InterruptionClassification(
                        InterruptionLabel.INTERRUPT
                        if intent is DualIntent.FLOOR_CLAIM
                        else InterruptionLabel.BACKCHANNEL,
                        1,
                    )
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
            self._log_interruption_decision(verdict, item)
            await self._inbox.put(
                (_Result(identity, revision, "interruption", verdict, token), None)
            )

        self._cancel("interruption")
        self._job("interruption_model", judge())

    async def _classify_interruption_timed(
        self, classifier: Any, request: InterruptionRequest, generation: int
    ) -> InterruptionClassification:
        timeout_s = self._provider._semantic_interruption_timeout_ms / 1000
        telemetry = self._provider._telemetry
        if telemetry is None:
            return await asyncio.wait_for(classify_interruption(classifier, request), timeout_s)
        async with telemetry.provider_call(
            provider="interruption_classifier",
            operation="classify",
            timeout_ms=timeout_s * 1000,
            generation=generation,
        ) as call:
            result = await asyncio.wait_for(classify_interruption(classifier, request), timeout_s)
            call.mark_first_response()
            return result

    def _log_interruption_decision(self, verdict: InterruptionVerdict, item: _Input) -> None:
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
            },
        )

    async def _yield(self, item: _Input) -> None:
        if item.yielded or item.yield_pending or item.target_response is None:
            return
        if self._response_id != item.target_response:
            item.yielded = True
            return
        item.yield_pending = True
        self._timer("yield_ack", self._provider.recovery_timeout_ms, item)
        await self._outbox.put(
            AssistantYieldRequested(
                context=replace(item.context, response_id=item.target_response),
                reason="barge_in_floor_claim",
            )
        )

    async def _advance(self, item: _Input, *, force: bool = False) -> None:
        if item.commit_pending or item.speech_active or item.stop is None or not item.text:
            return
        if item.continuation_of_turn_id and item.target_response is None:
            return
        if item.target_response:
            if item.verdict is None and not force:
                return
            if item.verdict:
                action = self._policy.interruption(item.verdict)
                question_answer = item.verdict.label is InterruptionLabel.BACKCHANNEL and any(
                    mark in item.assistant_text_at_onset for mark in ("?", "？")
                )
                if not action.admit_input and not question_answer:
                    if action.stop_response and not item.yielded:
                        await self._yield(item)
                        return
                    await self._outbox.put(
                        AsrDiscardRequested(
                            context=item.context, reason="semantic_control_or_feedback"
                        )
                    )
                    self._input = None
                    self._cancel(*tuple(self._jobs))
                    await self._project(item.context)
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
        self._cancel(*tuple(self._jobs))
        self._timer("asr_final", self._provider.recovery_timeout_ms, item)
        await self._outbox.put(
            AsrCommitRequested(
                context=item.context,
                reason="coordinated_turn_commit",
                audio_end_timestamp_us=item.stop.audio_timestamp_us,
            )
        )
        await self._project(item.context)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = [self._actor, *self._all_jobs]
        for task in tasks:
            task.cancel()
        done, pending = await asyncio.wait(tasks, timeout=0.1)
        for task in done:
            if not task.cancelled():
                task.exception()
        if pending:
            logger.warning("Turn coordinator closed with %d uncooperative tasks", len(pending))
        self._jobs.clear()
        self._input = None
        self._response_id = None
        # Closing must not depend on a consumer draining the output queue.
        while not self._outbox.empty():
            self._outbox.get_nowait()
        await self._outbox.put(_CLOSED)
