"""Replaceable semantic action policy; lifecycle and I/O stay in the coordinator."""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from server.turn_policy.eot_classifier import EotClassification, EotDecision
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionLabel,
    InterruptionVerdict,
)


class FloorOwner(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class InterruptionDisposition:
    stop_response: bool
    admit_input: bool


class TurnCoordinationPolicy(Protocol):
    def endpoint_wait_ms(self, result: EotClassification) -> float: ...

    def interruption(self, verdict: InterruptionVerdict) -> InterruptionDisposition: ...


@dataclass(frozen=True, slots=True)
class DefaultTurnCoordinationPolicy:
    incomplete_wait_ms: float = 5000
    uncertain_wait_ms: float = 300
    backchannel_confidence: float = 0.95

    def __post_init__(self) -> None:
        if any(
            not math.isfinite(value) or value < 0
            for value in (
                self.incomplete_wait_ms,
                self.uncertain_wait_ms,
            )
        ):
            raise ValueError("coordination waits must be finite and non-negative")
        if (
            not math.isfinite(self.backchannel_confidence)
            or not 0 <= self.backchannel_confidence <= 1
        ):
            raise ValueError("backchannel confidence must be between zero and one")

    def endpoint_wait_ms(self, result: EotClassification) -> float:
        if result.decision is EotDecision.COMPLETE:
            return 0
        ceiling = (
            self.incomplete_wait_ms
            if result.decision is EotDecision.INCOMPLETE
            else self.uncertain_wait_ms
        )
        return min(result.wait_ms, ceiling) if result.wait_ms > 0 else ceiling

    def interruption(self, verdict: InterruptionVerdict) -> InterruptionDisposition:
        # Provider errors preserve input but do not masquerade as confident stops.
        if verdict.source == "fallback":
            return InterruptionDisposition(False, True)
        if verdict.label is InterruptionLabel.STOP:
            return InterruptionDisposition(True, False)
        if verdict.label in {InterruptionLabel.CORRECTION, InterruptionLabel.INTERRUPT}:
            return InterruptionDisposition(True, True)
        if verdict.source == "rule" and verdict.label is InterruptionLabel.BACKCHANNEL:
            return InterruptionDisposition(False, False)
        if (
            verdict.label is InterruptionLabel.BACKCHANNEL
            and verdict.confidence >= self.backchannel_confidence
            and verdict.candidate.boundary is InterruptionBoundary.SENTENCE_END
        ):
            return InterruptionDisposition(False, False)
        # Uncertain input remains available for a user request.
        return InterruptionDisposition(False, True)
