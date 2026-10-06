"""Provider-neutral contract for local interruption rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionClassification,
    VerdictSource,
)


@dataclass(frozen=True, slots=True)
class InterruptionRuleContext:
    text: str
    boundary: InterruptionBoundary
    assistant_text: str = ""
    previous_chunks: tuple[str, ...] = ()
    previous_feedback_only: bool = False
    before_playback: bool = False


class InterruptionRuleProvider(Protocol):
    def match(self, context: InterruptionRuleContext) -> InterruptionClassification | None: ...


@dataclass(frozen=True, slots=True)
class RuleFirstInterruptionDecision:
    classification: InterruptionClassification
    source: VerdictSource
