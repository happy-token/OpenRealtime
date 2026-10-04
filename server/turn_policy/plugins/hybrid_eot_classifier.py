"""Provider-neutral semantic EoT arbitration."""

from __future__ import annotations

import asyncio
from typing import Literal

from server.turn_policy.eot_classifier import (
    EotClassification,
    EotContext,
    EotDecision,
    EotEvidenceProvider,
    EotRequest,
)


class HybridEotClassifier:
    """Hide parallel provider execution and arbitration behind one classifier."""

    def __init__(
        self,
        *,
        providers: tuple[EotEvidenceProvider, ...],
        strategy: Literal["consensus", "primary_with_shadow"] = "consensus",
    ) -> None:
        if not providers:
            raise ValueError("hybrid EOT classifier requires at least one provider")
        if strategy not in {"consensus", "primary_with_shadow"}:
            raise ValueError("unsupported hybrid EOT strategy")
        self._providers = providers
        self._strategy = strategy

    async def classify(self, *, text: str, generation: int) -> EotClassification:
        return await self.classify_with_context(
            text=text,
            generation=generation,
            context=EotContext(),
        )

    async def classify_with_context(
        self,
        *,
        text: str,
        generation: int,
        context: EotContext,
    ) -> EotClassification:
        return await self.classify_request(
            EotRequest(text=text, generation=generation, context=context)
        )

    async def classify_request(self, request: EotRequest) -> EotClassification:
        observations = await asyncio.gather(
            *(provider.evaluate(request) for provider in self._providers),
            return_exceptions=True,
        )
        for observation in observations:
            if isinstance(observation, BaseException) and not isinstance(observation, Exception):
                raise observation
        failures = [item for item in observations if isinstance(item, Exception)]
        evidence = [item for item in observations if not isinstance(item, BaseException)]
        if not evidence:
            raise RuntimeError(
                "all EOT evidence providers failed: "
                + ", ".join(type(error).__name__ for error in failures)
            )
        primary = observations[0] if not isinstance(observations[0], BaseException) else evidence[0]
        if self._strategy == "primary_with_shadow":
            decision = primary.decision
            confidence = primary.confidence
            wait_ms = primary.wait_ms
            source = f"primary:{primary.source}"
            shadow = [item.source for item in evidence if item is not primary]
            if shadow:
                source += ";shadow=" + "+".join(shadow)
        else:
            decisions = {item.decision for item in evidence}
            decision = evidence[0].decision if len(decisions) == 1 else EotDecision.UNCERTAIN
            confidence_values = [
                item.confidence for item in evidence if item.confidence is not None
            ]
            confidence = min(confidence_values) if confidence_values else None
            wait_ms = max(item.wait_ms for item in evidence)
            source = "hybrid:" + "+".join(item.source for item in evidence)
        if failures:
            source += ";degraded=" + "+".join(type(error).__name__ for error in failures)
        return EotClassification(
            decision=decision,
            confidence=confidence,
            wait_ms=wait_ms,
            source=source,
            evidence=tuple(evidence),
        )
