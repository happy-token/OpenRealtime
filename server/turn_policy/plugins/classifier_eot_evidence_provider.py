"""Adapter from the legacy classifier seam to rich EoT evidence."""

from __future__ import annotations

import time

from server.turn_policy.eot_classifier import (
    EotClassifierLike,
    EotEvidence,
    EotRequest,
    classify_eot,
)


class ClassifierEotEvidenceProvider:
    """Preserve an existing classifier while the richer provider seam rolls out."""

    def __init__(self, classifier: EotClassifierLike) -> None:
        self._classifier = classifier

    async def evaluate(self, request: EotRequest) -> EotEvidence:
        started_at = time.perf_counter()
        classification = await classify_eot(self._classifier, request)
        return EotEvidence(
            decision=classification.decision,
            confidence=classification.confidence,
            wait_ms=classification.wait_ms,
            source=classification.source,
            inference_ms=(time.perf_counter() - started_at) * 1000,
        )
