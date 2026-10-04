"""Semantic interruption arbitration for assistant-playback overlap.

This module answers one narrow question: while the assistant is speaking,
should the current playback stop now?  It deliberately does not decide when
the user has finished speaking; ``SemanticEndpointGate`` remains the sole EOT
authority.

The gate is a deep module around three timing-sensitive details:

* exact local rules for obvious stop/backchannel phrases;
* revision-aware scheduling of partial ASR text; and
* one latest-wins model task, so stale transcript revisions cannot stop a
  newer playback generation.

It has no dependency on a speech vendor or on the Conversation Kernel.  A
host injects a ``SemanticInterruptionClassifier`` and an optional verdict
observer, then feeds normalized ASR revisions through ``observe``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from server.core.interaction_context import InteractionContext
from server.turn_policy.eot_classifier import EotHistoryMessage
from server.turn_policy.semantic_input import SemanticInputState, TextBoundary


class InterruptionBoundary(str, Enum):
    PARTIAL = "partial"
    SENTENCE_END = "sentence_end"


class InterruptionLabel(str, Enum):
    STOP = "stop"
    CORRECTION = "correction"
    INTERRUPT = "interrupt"
    BACKCHANNEL = "backchannel"
    IGNORE = "ignore"
    UNCERTAIN = "uncertain"


STOP_ACTION_LABELS = frozenset(
    {
        InterruptionLabel.STOP,
        InterruptionLabel.CORRECTION,
        InterruptionLabel.INTERRUPT,
    }
)
TURN_CREATING_LABELS = frozenset({InterruptionLabel.CORRECTION, InterruptionLabel.INTERRUPT})


@dataclass(frozen=True, slots=True)
class InterruptionCandidate:
    text: str
    generation: int
    transcript_revision: int
    boundary: InterruptionBoundary


@dataclass(frozen=True, slots=True)
class InterruptionClassification:
    label: InterruptionLabel
    confidence: float

    def __post_init__(self) -> None:
        if not isinstance(self.label, InterruptionLabel):
            raise TypeError("semantic interruption label is invalid")
        if (
            isinstance(self.confidence, bool)
            or not math.isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("semantic interruption confidence must be finite and between 0 and 1")


VerdictSource = Literal["rule", "model", "fallback"]


@dataclass(frozen=True, slots=True)
class InterruptionVerdict:
    candidate: InterruptionCandidate
    classification: InterruptionClassification
    source: VerdictSource

    @property
    def label(self) -> InterruptionLabel:
        return self.classification.label

    @property
    def confidence(self) -> float:
        return self.classification.confidence

    @property
    def should_stop(self) -> bool:
        return self.label in STOP_ACTION_LABELS

    @property
    def creates_turn(self) -> bool:
        return self.label in TURN_CREATING_LABELS


def completed_interruption_creates_turn(
    verdict: InterruptionVerdict | None,
) -> bool:
    """Return whether a completed non-echo transcript must be admitted.

    Semantic classification may stop playback early, but model-only negative
    verdicts are not precise enough to erase a complete user utterance. Turn
    suppression is therefore reserved for exact local backchannel rules and
    explicit playback-only stop commands. This is deliberately fail-open: one
    extra interruption is safer than a user turn that disappears.
    """

    if verdict is None:
        return True
    if verdict.should_stop:
        return verdict.creates_turn
    return verdict.source != "rule"


class SemanticInterruptionClassifier(Protocol):
    async def classify(
        self,
        *,
        assistant_text: str,
        transcript: str,
        boundary: InterruptionBoundary,
        generation: int,
    ) -> InterruptionClassification: ...


@dataclass(frozen=True, slots=True)
class InterruptionRequest:
    transcript: str
    assistant_text: str
    generation: int
    boundary: InterruptionBoundary
    history: tuple[EotHistoryMessage, ...] = ()
    input_state: SemanticInputState = field(default_factory=SemanticInputState)
    interaction: InteractionContext | None = None
    language: str | None = None
    contract_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.contract_version != 1
            or isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 0
        ):
            raise ValueError("invalid interruption request version or generation")
        if not isinstance(self.history, tuple) or not all(
            isinstance(item, EotHistoryMessage) for item in self.history
        ):
            raise ValueError("interruption history must be an immutable tuple of messages")
        if not isinstance(self.input_state, SemanticInputState):
            raise TypeError("invalid interruption input state")
        if not self.transcript.strip() or not isinstance(self.boundary, InterruptionBoundary):
            raise ValueError("invalid interruption request text or boundary")
        if self.interaction is not None and self.interaction.generation != self.generation:
            raise ValueError("interruption request generation does not match interaction")


@runtime_checkable
class RequestInterruptionClassifier(Protocol):
    async def classify_request(
        self, request: InterruptionRequest
    ) -> InterruptionClassification: ...


InterruptionClassifierLike = SemanticInterruptionClassifier | RequestInterruptionClassifier


async def classify_interruption(
    classifier: InterruptionClassifierLike,
    request: InterruptionRequest,
) -> InterruptionClassification:
    if isinstance(classifier, RequestInterruptionClassifier):
        result = await classifier.classify_request(request)
    else:
        result = await classifier.classify(
            assistant_text=request.assistant_text,
            transcript=request.transcript,
            boundary=request.boundary,
            generation=request.generation,
        )
    if not isinstance(result, InterruptionClassification):
        raise TypeError("unsupported interruption classification")
    return result


_IMMEDIATE_STOP_PHRASES = frozenset(
    {
        "别说了",
        "不要说了",
        "先别说了",
        "闭嘴",
        "够了",
        "不用说了",
        "别讲了",
        "不要讲了",
        "wait",
        "holdon",
        "hangon",
    }
)
_BOUNDARY_STOP_PHRASES = frozenset({"停", "停止", "别说", "stop"})
_BACKCHANNEL_PHRASES = frozenset(
    {
        "嗯",
        "嗯嗯",
        "啊",
        "哦",
        "噢",
        "好",
        "好的",
        "行",
        "可以",
        "对",
        "是的",
        "没错",
        "继续",
        "你继续",
        "哈哈",
        "哈哈哈",
        "mhm",
        "mmhmm",
        "okay",
        "yes",
    }
)
_TRAILING_PUNCTUATION = "。！？，；：.!?,;:"


def _normalize_rule_text(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold().rstrip(_TRAILING_PUNCTUATION)


def match_interruption_rule(
    text: str,
    *,
    boundary: InterruptionBoundary,
    stable: bool = False,
) -> InterruptionClassification | None:
    """Return only exact, deterministic rule matches.

    Short boundary words such as ``停`` are delayed until stable input so a
    partial prefix such as ``停电了吗`` cannot cut off the assistant.
    """

    normalized = _normalize_rule_text(text)
    if normalized in _IMMEDIATE_STOP_PHRASES:
        return InterruptionClassification(InterruptionLabel.STOP, 1.0)
    if normalized in _BOUNDARY_STOP_PHRASES and (
        stable or boundary is InterruptionBoundary.SENTENCE_END
    ):
        return InterruptionClassification(InterruptionLabel.STOP, 1.0)
    if normalized in _BACKCHANNEL_PHRASES:
        return InterruptionClassification(InterruptionLabel.BACKCHANNEL, 1.0)
    return None


def parse_interruption_classification(content: str) -> InterruptionClassification:
    """Parse the strict two-field model contract."""

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("semantic interruption output is not valid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"label", "confidence"}:
        raise ValueError("semantic interruption output has an invalid schema")
    try:
        label = InterruptionLabel(payload["label"])
    except (TypeError, ValueError) as error:
        raise ValueError("semantic interruption label is invalid") from error
    confidence = payload["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("semantic interruption confidence must be numeric")
    normalized_confidence = float(confidence)
    if not math.isfinite(normalized_confidence) or not 0 <= normalized_confidence <= 1:
        raise ValueError("semantic interruption confidence must be between 0 and 1")
    return InterruptionClassification(label, normalized_confidence)


@dataclass(frozen=True, slots=True)
class ScheduledInterruption:
    candidate: InterruptionCandidate
    reason: Literal["sentence_end", "chars", "idle"]
    stable: bool


class InterruptionRevisionScheduler:
    """Pure debounce/character scheduler for cumulative ASR revisions."""

    def __init__(self, *, partial_chars: int = 5, idle_ms: float = 100) -> None:
        if partial_chars <= 0:
            raise ValueError("partial_chars must be positive")
        if idle_ms < 0:
            raise ValueError("idle_ms must be non-negative")
        self.partial_chars = partial_chars
        self.idle_ms = idle_ms
        self._latest: InterruptionCandidate | None = None
        self._last_submitted_text = ""
        self._idle_due_ms: float | None = None

    def reset(self) -> None:
        self._latest = None
        self._last_submitted_text = ""
        self._idle_due_ms = None

    def observe(
        self,
        candidate: InterruptionCandidate,
        *,
        now_ms: float,
    ) -> ScheduledInterruption | None:
        previous = self._latest
        previous_text = previous.text if previous is not None else ""
        exact_duplicate = candidate == previous
        self._latest = candidate

        if candidate.boundary is InterruptionBoundary.SENTENCE_END:
            self._idle_due_ms = None
            self._last_submitted_text = candidate.text
            if exact_duplicate:
                return None
            return ScheduledInterruption(candidate, "sentence_end", True)

        if exact_duplicate:
            return None
        if candidate.text != previous_text:
            self._idle_due_ms = now_ms + self.idle_ms
        is_append = candidate.text.startswith(previous_text)
        extends_last_submission = candidate.text.startswith(self._last_submitted_text)
        if (
            is_append
            and extends_last_submission
            and len(candidate.text) - len(self._last_submitted_text) >= self.partial_chars
        ):
            self._last_submitted_text = candidate.text
            self._idle_due_ms = None
            return ScheduledInterruption(candidate, "chars", False)
        return None

    def on_idle(self, *, now_ms: float) -> ScheduledInterruption | None:
        if (
            self._latest is None
            or self._latest.boundary is InterruptionBoundary.SENTENCE_END
            or self._idle_due_ms is None
            or now_ms < self._idle_due_ms
        ):
            return None
        latest = self._latest
        self._idle_due_ms = None
        self._last_submitted_text = latest.text
        return ScheduledInterruption(latest, "idle", True)


VerdictObserver = Callable[[InterruptionVerdict], Awaitable[None] | None]


class SemanticInterruptionGate:
    """Latest-wins semantic interruption coordinator.

    ``observe`` never waits for the model.  It performs rules synchronously,
    replaces the sole model task when the transcript changes, and reports a
    current verdict through the observer.  ``resolve`` is the quiet-boundary
    adapter: it upgrades the latest revision to a stable boundary and waits
    only for that one current classification.
    """

    def __init__(
        self,
        classifier: InterruptionClassifierLike | None,
        *,
        observer: VerdictObserver | None = None,
        partial_chars: int = 5,
        idle_ms: float = 100,
        confidence_threshold: float = 0.8,
        classifier_timeout_ms: float = 800,
    ) -> None:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if classifier_timeout_ms <= 0:
            raise ValueError("classifier_timeout_ms must be positive")
        self._classifier = classifier
        self._observer = observer
        self._scheduler = InterruptionRevisionScheduler(
            partial_chars=partial_chars,
            idle_ms=idle_ms,
        )
        self._confidence_threshold = confidence_threshold
        self._classifier_timeout_s = classifier_timeout_ms / 1000
        self._generation: int | None = None
        self._assistant_text = ""
        self._history: tuple[EotHistoryMessage, ...] = ()
        self._interaction: InteractionContext | None = None
        self._input_state = SemanticInputState()
        self._latest_candidate: InterruptionCandidate | None = None
        self._latest: InterruptionVerdict | None = None
        self._classification_task: asyncio.Task[None] | None = None
        self._classification_tasks: set[asyncio.Task[None]] = set()
        self._idle_task: asyncio.Task[None] | None = None

    @property
    def active(self) -> bool:
        return self._generation is not None

    @property
    def latest(self) -> InterruptionVerdict | None:
        return self._latest

    async def begin(
        self,
        *,
        generation: int,
        assistant_text: str,
        history: tuple[EotHistoryMessage, ...] = (),
        interaction: InteractionContext | None = None,
        input_state: SemanticInputState | None = None,
    ) -> None:
        if self._generation == generation:
            return
        await self.reset()
        self._generation = generation
        self._assistant_text = assistant_text
        self._history = history
        self._interaction = interaction
        self._input_state = input_state or SemanticInputState()

    async def observe(
        self,
        candidate: InterruptionCandidate,
    ) -> InterruptionVerdict | None:
        if candidate.generation != self._generation:
            return None
        previous = self._latest_candidate
        if previous == candidate:
            return self._latest if self._latest and self._latest.candidate == candidate else None
        if previous is not None and candidate.transcript_revision < previous.transcript_revision:
            return None

        # Update the latest token before yielding. An in-flight classification
        # may finish, but its commit is rejected when it no longer matches this
        # token. Only a newly scheduled classification replaces the provider
        # request; ordinary ASR partial revisions merely re-arm the idle gate.
        self._latest_candidate = candidate
        self._latest = None
        self._cancel_idle_task()

        scheduled = self._scheduler.observe(
            candidate,
            now_ms=asyncio.get_running_loop().time() * 1000,
        )
        rule = match_interruption_rule(
            candidate.text,
            boundary=candidate.boundary,
            stable=candidate.boundary is InterruptionBoundary.SENTENCE_END,
        )
        if rule is not None:
            self._cancel_classification_task()
            return await self._commit(candidate, rule, source="rule")
        if scheduled is not None:
            self._submit(scheduled)
        elif candidate.boundary is InterruptionBoundary.PARTIAL:
            self._arm_idle()
        return None

    async def resolve(
        self,
        candidate: InterruptionCandidate,
    ) -> InterruptionVerdict | None:
        """Resolve the latest quiet boundary without duplicating model work."""

        if candidate.boundary is not InterruptionBoundary.SENTENCE_END:
            candidate = replace(candidate, boundary=InterruptionBoundary.SENTENCE_END)
        immediate = await self.observe(candidate)
        if immediate is not None:
            return immediate
        task = self._classification_task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        verdict = self._latest
        return verdict if verdict is not None and verdict.candidate == candidate else None

    def is_current(self, verdict: InterruptionVerdict) -> bool:
        return (
            verdict.candidate == self._latest_candidate
            and verdict.candidate.generation == self._generation
        )

    async def wait(self) -> None:
        while self._classification_tasks:
            await asyncio.gather(
                *tuple(self._classification_tasks),
                return_exceptions=True,
            )

    async def reset(self) -> None:
        self._generation = None
        self._assistant_text = ""
        self._history = ()
        self._interaction = None
        self._input_state = SemanticInputState()
        self._latest_candidate = None
        self._latest = None
        self._scheduler.reset()
        tasks = tuple(self._classification_tasks)
        self._cancel_classification_task()
        self._cancel_idle_task()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        await self.reset()

    def _submit(self, scheduled: ScheduledInterruption) -> None:
        if self._classifier is None:
            return
        self._cancel_classification_task()
        task = asyncio.create_task(
            self._classify(scheduled),
            name=(
                "semantic-interruption-"
                f"{scheduled.candidate.generation}-"
                f"{scheduled.candidate.transcript_revision}"
            ),
        )
        self._classification_task = task
        self._classification_tasks.add(task)
        task.add_done_callback(self._classification_tasks.discard)
        task.add_done_callback(self._clear_current_classification_task)

    async def _classify(self, scheduled: ScheduledInterruption) -> None:
        assert self._classifier is not None
        candidate = scheduled.candidate
        try:
            classification = await asyncio.wait_for(
                classify_interruption(
                    self._classifier,
                    InterruptionRequest(
                        assistant_text=self._assistant_text,
                        transcript=candidate.text,
                        boundary=candidate.boundary,
                        generation=candidate.generation,
                        history=self._history,
                        interaction=self._interaction,
                        input_state=replace(
                            self._input_state,
                            transcript_revision=candidate.transcript_revision,
                            boundary=TextBoundary(candidate.boundary.value),
                        ),
                    ),
                ),
                timeout=self._classifier_timeout_s,
            )
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001 - deliberate fail-open boundary
            classification = InterruptionClassification(
                InterruptionLabel.INTERRUPT if candidate.text.strip() else InterruptionLabel.IGNORE,
                0.0,
            )
            source: VerdictSource = "fallback"
        else:
            if (
                classification.label in STOP_ACTION_LABELS
                and classification.confidence < self._confidence_threshold
            ):
                classification = replace(
                    classification,
                    label=InterruptionLabel.UNCERTAIN,
                )
            source = "model"
        await self._commit(candidate, classification, source=source)

    async def _commit(
        self,
        candidate: InterruptionCandidate,
        classification: InterruptionClassification,
        *,
        source: VerdictSource,
    ) -> InterruptionVerdict | None:
        if candidate != self._latest_candidate or candidate.generation != self._generation:
            return None
        verdict = InterruptionVerdict(candidate, classification, source)
        self._latest = verdict
        if self._observer is not None:
            observed = self._observer(verdict)
            if inspect.isawaitable(observed):
                await observed
        return verdict

    def _arm_idle(self) -> None:
        self._idle_task = asyncio.create_task(self._after_idle())

    async def _after_idle(self) -> None:
        try:
            await asyncio.sleep(self._scheduler.idle_ms / 1000)
            scheduled = self._scheduler.on_idle(
                now_ms=asyncio.get_running_loop().time() * 1000,
            )
            if scheduled is None:
                return
            rule = match_interruption_rule(
                scheduled.candidate.text,
                boundary=scheduled.candidate.boundary,
                stable=True,
            )
            if rule is not None:
                await self._commit(scheduled.candidate, rule, source="rule")
            else:
                self._submit(scheduled)
        except asyncio.CancelledError:
            return
        finally:
            if self._idle_task is asyncio.current_task():
                self._idle_task = None

    def _cancel_classification_task(self) -> None:
        task = self._classification_task
        self._classification_task = None
        if task is not None and not task.done():
            task.cancel()

    def _cancel_idle_task(self) -> None:
        task = self._idle_task
        self._idle_task = None
        if task is not None and not task.done():
            task.cancel()

    def _clear_current_classification_task(self, task: asyncio.Task[None]) -> None:
        if self._classification_task is task:
            self._classification_task = None
