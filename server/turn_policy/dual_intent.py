"""DualIntentClassifier: the plugin interface disambiguating τ9 vs τ10.

See CONTEXT.md — DualIntentClassifier, and ADR-0007/ADR-0015. Once Turn
Policy is in DUAL and the AddresseeClassifier has confirmed the overlapping
audio is addressed to the assistant (ruling out τ11, third-party), this
classifier decides whether the overlap is a floor-claim (τ9, the assistant
yields) or a backchannel (τ10, the assistant continues). A realtime engine
can feed its ASR audio during SPEAK/DUAL and pass the peeked transcript as
`text`, so a deployment can register a content-aware classifier
(turn_policy/plugins/llm_dual_intent_classifier.py's LlmDualIntentClassifier)
instead of the shipped duration-only default.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class DualIntent(Enum):
    FLOOR_CLAIM = "floor_claim"
    BACKCHANNEL = "backchannel"


class DualIntentClassifier(Protocol):
    async def classify(self, *, generation: int, overlap_ms: float, text: str) -> DualIntent: ...


@dataclass(frozen=True)
class DefaultDualIntentClassifierConfig:
    floor_claim_threshold_ms: float = 800.0


class DefaultDualIntentClassifier:
    """Minimal shipped heuristic: brief overlap reads as backchannel, sustained
    overlap reads as a floor-claim. See CONTEXT.md — Turn Policy's own note
    that signal sources here are deliberately not production-grade."""

    def __init__(self, config: DefaultDualIntentClassifierConfig | None = None) -> None:
        self._config = config or DefaultDualIntentClassifierConfig()

    async def classify(self, *, generation: int, overlap_ms: float, text: str) -> DualIntent:
        del text  # unused by this conformer; part of the Protocol shape
        if overlap_ms >= self._config.floor_claim_threshold_ms:
            return DualIntent.FLOOR_CLAIM
        return DualIntent.BACKCHANNEL
