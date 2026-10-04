"""Provider-neutral semantic-completeness Seam.

See CONTEXT.md — EotClassifier, docs/SEMANTIC-EOT.md, and ADR-0057. The
classifier owns meaning only. ``SemanticEndpointGate`` combines its result
with an independent VAD/ASR-idle stop latch and live-activity invalidation
before the Conversation Kernel commits USER_EOT_CONFIRMED to Turn Policy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from server.core.interaction_context import InteractionContext
from server.turn_policy.semantic_input import SemanticInputState


class EotDecision(Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class EotClassification:
    """Provider-neutral semantic endpoint result.

    ``wait_ms`` is an optional stability hint for INCOMPLETE or UNCERTAIN
    results, not a request to call the classifier repeatedly.  The runtime
    applies its own bounds before waiting. Keeping it on the Seam avoids
    leaking any model/provider response shape into the Kernel.
    """

    decision: EotDecision
    confidence: float | None = None
    wait_ms: float = 0.0
    source: str = "classifier"
    evidence: tuple[EotEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.decision, EotDecision):
            raise TypeError("EOT decision is invalid")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not math.isfinite(self.wait_ms) or self.wait_ms < 0:
            raise ValueError("wait_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class EotHistoryMessage:
    """One immutable, already-committed dialogue message for EoT context."""

    role: Literal["user", "assistant"]
    content: str
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.role not in {"user", "assistant"}:
            raise ValueError("EOT history role must be user or assistant")
        if not self.content.strip():
            raise ValueError("EOT history content must be non-empty")


@dataclass(frozen=True, slots=True)
class EotContext:
    """Frozen history prefix shared by every ASR revision in one user turn."""

    history: tuple[EotHistoryMessage, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.history, tuple) or not all(
            isinstance(item, EotHistoryMessage) for item in self.history
        ):
            raise ValueError("EOT history must be an immutable tuple of messages")


@dataclass(frozen=True, slots=True)
class EotRequest:
    """One immutable semantic endpoint candidate presented to a provider."""

    text: str
    generation: int
    context: EotContext = EotContext()
    language: str | None = None
    input_state: SemanticInputState = field(default_factory=SemanticInputState)
    interaction: InteractionContext | None = None
    contract_version: int = 1

    def __post_init__(self) -> None:
        if self.contract_version != 1:
            raise ValueError("unsupported EOT request contract version")
        if not isinstance(self.context, EotContext) or not isinstance(
            self.input_state, SemanticInputState
        ):
            raise TypeError("invalid EOT request context or input state")
        if self.interaction is not None and self.interaction.generation != self.generation:
            raise ValueError("EOT request generation does not match interaction")
        if not self.text.strip():
            raise ValueError("EOT request text must be non-empty")
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 0
        ):
            raise ValueError("EOT request generation must be non-negative")
        if self.language == "":
            raise ValueError("EOT request language must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class EotEvidence:
    """Provider observation retained until the hybrid resolver arbitrates it."""

    decision: EotDecision
    source: str
    confidence: float | None = None
    wait_ms: float = 0.0
    inference_ms: float = 0.0
    probability: float | None = None
    threshold: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("confidence", self.confidence),
            ("probability", self.probability),
            ("threshold", self.threshold),
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if not self.source:
            raise ValueError("EOT evidence source must be non-empty")
        if not all(
            math.isfinite(value) and value >= 0 for value in (self.wait_ms, self.inference_ms)
        ):
            raise ValueError("EOT evidence durations must be non-negative")


class EotEvidenceProvider(Protocol):
    """Replaceable evidence seam used inside a cascaded Turn Manager."""

    async def evaluate(self, request: EotRequest) -> EotEvidence: ...


def normalize_eot_classification(
    result: EotClassification | EotDecision,
) -> EotClassification:
    """Accept legacy enum-only plugins while the richer Seam rolls out."""

    if isinstance(result, EotClassification):
        return result
    if isinstance(result, EotDecision):
        return EotClassification(decision=result, source="legacy_classifier")
    raise TypeError(f"unsupported EOT classification: {type(result).__name__}")


class EotClassifier(Protocol):
    async def classify(self, *, text: str, generation: int) -> EotClassification | EotDecision: ...


@runtime_checkable
class ContextualEotClassifier(Protocol):
    """Optional extension for classifiers that can use committed history.

    Keeping this separate preserves compatibility with small local/binary
    classifiers whose input is only the current accumulated transcript.
    """

    async def classify_with_context(
        self,
        *,
        text: str,
        generation: int,
        context: EotContext,
    ) -> EotClassification | EotDecision: ...


@runtime_checkable
class RequestEotClassifier(Protocol):
    """Preferred plugin contract; text-only implementations may ignore context."""

    async def classify_request(self, request: EotRequest) -> EotClassification | EotDecision: ...


EotClassifierLike = EotClassifier | RequestEotClassifier


async def classify_eot(classifier: EotClassifierLike, request: EotRequest) -> EotClassification:
    if isinstance(classifier, RequestEotClassifier):
        result = await classifier.classify_request(request)
    elif isinstance(classifier, ContextualEotClassifier):
        result = await classifier.classify_with_context(
            text=request.text,
            generation=request.generation,
            context=request.context,
        )
    else:
        result = await classifier.classify(text=request.text, generation=request.generation)
    return normalize_eot_classification(result)


class FastEotScorer(Protocol):
    """The always-on, no-network side of an EnsembleEotClassifier (see
    turn_policy/plugins/ensemble_eot_classifier.py) — analogous to
    voiceloop's FireRedChat scorer, but scored heuristically rather than by
    a dedicated model."""

    async def score(self, *, text: str) -> EotDecision: ...


_SENTENCE_FINAL_PUNCTUATION = (".", "!", "?", "。", "！", "？")
_TRAILING_CONNECTIVES = (
    "and",
    "but",
    "or",
    "so",
    "because",
    "and then",
    "而且",
    "但是",
    "所以",
    "因为",
    "然后",
    "还有",
)


class PunctuationEotScorer:
    """Cheap, always-on, no-network stand-in for voiceloop's FireRedChat —
    the fast side of an EnsembleEotClassifier. Sentence-final punctuation
    reads as COMPLETE; a trailing conjunction/connective reads as
    INCOMPLETE; anything else is UNCERTAIN."""

    async def score(self, *, text: str) -> EotDecision:
        stripped = text.strip()
        if not stripped:
            return EotDecision.UNCERTAIN
        if stripped.endswith(_SENTENCE_FINAL_PUNCTUATION):
            return EotDecision.COMPLETE
        lowered = stripped.lower()
        if any(lowered.endswith(connective) for connective in _TRAILING_CONNECTIVES):
            return EotDecision.INCOMPLETE
        return EotDecision.UNCERTAIN
