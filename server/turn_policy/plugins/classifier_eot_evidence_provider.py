"""Adapter from the legacy classifier seam to rich EoT evidence."""

from __future__ import annotations

import time

from server.turn_policy.eot_classifier import (
    ContextualEotClassifier,
    EotClassifier,
    EotEvidence,
    EotRequest,
    normalize_eot_classification,
)


class ClassifierEotEvidenceProvider:
    """Preserve an existing classifier while the richer provider seam rolls out."""

    def __init__(self, classifier: EotClassifier) -> None:
        self._classifier = classifier

    async def evaluate(self, request: EotRequest) -> EotEvidence:
        started_at = time.perf_counter()
        if isinstance(self._classifier, ContextualEotClassifier):
            result = await self._classifier.classify_with_context(
                text=request.text,
                generation=request.generation,
                context=request.context,
            )
        else:
            result = await self._classifier.classify(
                text=request.text,
                generation=request.generation,
            )
        classification = normalize_eot_classification(result)
        return EotEvidence(
            decision=classification.decision,
            confidence=classification.confidence,
            wait_ms=classification.wait_ms,
            source=classification.source,
            inference_ms=(time.perf_counter() - started_at) * 1000,
        )
