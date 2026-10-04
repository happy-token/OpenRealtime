"""Stable, provider-neutral semantic endpoint coordination.

A sentence-final ASR revision starts classification immediately, but it is
only a *candidate*.  The candidate can commit after both independent latches
are satisfied:

1. semantic completeness has been classified; and
2. VAD stop (or the ASR-idle fallback) confirms that audio has gone quiet.

Fresh transcript activity invalidates both pieces of speculative work. A VAD
restart still cancels an in-flight classification, but if semantic completeness
is already known and ASR does not revise the text, the Gate retains that result
and requires a fresh ASR-idle/stop latch before committing the same revision.
This follows VoiceLoop's useful invariant without importing its model or
pipeline wrappers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from enum import Enum

from server.core.interaction_context import InteractionContext
from server.turn_policy.eot_classifier import (
    EotClassification,
    EotClassifierLike,
    EotContext,
    EotDecision,
    EotHistoryMessage,
    EotRequest,
    classify_eot,
)
from server.turn_policy.semantic_input import SemanticInputState


@dataclass(frozen=True, slots=True)
class EndpointCandidate:
    text: str
    generation: int
    transcript_revision: int
    history: tuple[EotHistoryMessage, ...] = ()
    input_state: SemanticInputState = field(default_factory=SemanticInputState)
    interaction: InteractionContext | None = None


class EndpointResolution(Enum):
    COMMIT = "commit"
    DEFER_ACTIVITY = "defer_activity"
    HOLD_INCOMPLETE = "hold_incomplete"
    HOLD_UNCERTAIN = "hold_uncertain"


@dataclass(frozen=True, slots=True)
class EndpointOutcome:
    resolution: EndpointResolution
    classification: EotClassification
    stop_source: str | None = None
    error: str | None = None


def endpoint_stability_wait_ms(
    outcome: EndpointOutcome,
    *,
    incomplete_timeout_ms: float,
    uncertain_wait_ms: float,
) -> float:
    """Resolve a model hint without letting it exceed runtime policy.

    ``incomplete_timeout_ms`` remains the conservative hard ceiling. A model
    may request a shorter continuation window for a likely false-negative
    (for example a terse but meaningful utterance); an absent hint retains the
    full ceiling for genuinely open-ended speech.
    """

    if outcome.resolution is EndpointResolution.HOLD_INCOMPLETE:
        requested_ms = outcome.classification.wait_ms
        if requested_ms <= 0:
            return incomplete_timeout_ms
        return min(
            max(requested_ms, uncertain_wait_ms),
            incomplete_timeout_ms,
        )
    if outcome.resolution is EndpointResolution.HOLD_UNCERTAIN:
        return outcome.classification.wait_ms or uncertain_wait_ms
    return 0.0


class EndpointActivity:
    """Single-candidate activity signal written by live ASR/VAD input."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._reason: str | None = None

    @property
    def invalidated(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return self._reason

    def invalidate(self, reason: str) -> bool:
        if self._event.is_set():
            if self._reason == "vad_speech" and reason != "vad_speech":
                self._reason = reason
            return False
        self._reason = reason
        self._event.set()
        return True

    def reset(self, expected_reason: str) -> bool:
        if self._reason != expected_reason:
            return False
        self._reason = None
        self._event.clear()
        return True

    async def wait(self) -> None:
        await self._event.wait()


class EndpointStop:
    """Resettable acoustic/idle commit latch for an endpoint candidate."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._source: str | None = None

    @property
    def confirmed(self) -> bool:
        return self._event.is_set()

    @property
    def source(self) -> str | None:
        return self._source

    def confirm(self, source: str) -> bool:
        if self._event.is_set():
            return False
        self._source = source
        self._event.set()
        return True

    def reset(self) -> None:
        self._source = None
        self._event.clear()

    async def wait(self) -> None:
        await self._event.wait()


class SemanticEndpointGate:
    """Resolve the semantic and acoustic latches while activity stays stable.

    The interface deliberately exposes one operation.  Classifier deadlines,
    legacy-result normalization, latch ordering and cancellation are hidden
    here so the Conversation Kernel only handles domain outcomes.
    """

    def __init__(
        self,
        classifier: EotClassifierLike | None,
        *,
        classifier_timeout_ms: float = 5000.0,
        uncertain_wait_ms: float = 300.0,
        min_uncertain_wait_ms: float = 100.0,
        max_uncertain_wait_ms: float = 400.0,
    ) -> None:
        if classifier_timeout_ms <= 0:
            raise ValueError("classifier_timeout_ms must be positive")
        if uncertain_wait_ms < 0:
            raise ValueError("uncertain_wait_ms must be non-negative")
        if min_uncertain_wait_ms < 0:
            raise ValueError("min_uncertain_wait_ms must be non-negative")
        if max_uncertain_wait_ms < min_uncertain_wait_ms:
            raise ValueError("max_uncertain_wait_ms must be at least min_uncertain_wait_ms")
        self._classifier = classifier
        self._classifier_timeout_s = classifier_timeout_ms / 1000
        self._uncertain_wait_ms = uncertain_wait_ms
        self._min_uncertain_wait_ms = min_uncertain_wait_ms
        self._max_uncertain_wait_ms = max_uncertain_wait_ms

    async def resolve(
        self,
        candidate: EndpointCandidate,
        activity: EndpointActivity,
        stop: EndpointStop,
    ) -> EndpointOutcome:
        fallback = EotClassification(
            decision=EotDecision.UNCERTAIN,
            wait_ms=self._uncertain_wait_ms,
            source="classifier_error",
        )
        if activity.invalidated:
            return EndpointOutcome(EndpointResolution.DEFER_ACTIVITY, fallback)

        classification_task = asyncio.create_task(self._classify(candidate))
        activity_task = asyncio.create_task(activity.wait())
        stop_task = asyncio.create_task(stop.wait())
        classification: EotClassification | None = None
        error: str | None = None
        stop_confirmed = stop.confirmed

        try:
            while classification is None or not stop_confirmed:
                waiters: set[asyncio.Task[object]] = {activity_task}
                if classification is None:
                    waiters.add(classification_task)
                if not stop_confirmed:
                    waiters.add(stop_task)
                done, _ = await asyncio.wait(
                    waiters,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Preserve a semantic result that became ready before the VAD
                # activity was observed. The Gate can reuse that result if the
                # ASR revision remains unchanged through the next idle.
                if classification_task in done:
                    classification, error = classification_task.result()
                if stop_task in done:
                    stop_confirmed = True
                if activity_task in done or activity.invalidated:
                    if (
                        classification is not None
                        and classification.decision is EotDecision.COMPLETE
                        and activity.reason == "vad_speech"
                        and activity.reset("vad_speech")
                    ):
                        # VAD can restart on noise or a non-lexical sound after
                        # semantic completeness has already been established.
                        # Keep that judgement, but require a fresh acoustic/ASR
                        # idle latch for the unchanged transcript revision.
                        stop_confirmed = stop.confirmed
                        activity_task = asyncio.create_task(activity.wait())
                        if not stop_confirmed and stop_task.done():
                            stop_task = asyncio.create_task(stop.wait())
                        continue
                    return EndpointOutcome(
                        EndpointResolution.DEFER_ACTIVITY,
                        classification or fallback,
                        error=error,
                    )

            if activity.invalidated:
                return EndpointOutcome(
                    EndpointResolution.DEFER_ACTIVITY,
                    classification or fallback,
                )
        finally:
            tasks = (classification_task, activity_task, stop_task)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        assert classification is not None
        if (
            classification.decision is EotDecision.UNCERTAIN
            and classification.wait_ms > 0
            and classification.source != "classifier_error"
        ):
            classification = replace(
                classification,
                wait_ms=min(
                    self._max_uncertain_wait_ms,
                    max(self._min_uncertain_wait_ms, classification.wait_ms),
                ),
            )
        resolution = {
            EotDecision.COMPLETE: EndpointResolution.COMMIT,
            EotDecision.INCOMPLETE: EndpointResolution.HOLD_INCOMPLETE,
            EotDecision.UNCERTAIN: EndpointResolution.HOLD_UNCERTAIN,
        }[classification.decision]
        return EndpointOutcome(
            resolution=resolution,
            classification=classification,
            stop_source=stop.source,
            error=error,
        )

    async def _classify(self, candidate: EndpointCandidate) -> tuple[EotClassification, str | None]:
        if self._classifier is None:
            return (
                EotClassification(
                    decision=EotDecision.COMPLETE,
                    confidence=1.0,
                    source="classifier_disabled",
                ),
                None,
            )
        try:
            async with asyncio.timeout(self._classifier_timeout_s):
                result = await classify_eot(
                    self._classifier,
                    EotRequest(
                        text=candidate.text,
                        generation=candidate.generation,
                        context=EotContext(history=candidate.history),
                        input_state=candidate.input_state,
                        interaction=candidate.interaction,
                    ),
                )
            return result, None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - bounded liveness boundary
            return (
                EotClassification(
                    decision=EotDecision.UNCERTAIN,
                    wait_ms=self._uncertain_wait_ms,
                    source="classifier_error",
                ),
                f"{type(exc).__name__}: {exc}",
            )
