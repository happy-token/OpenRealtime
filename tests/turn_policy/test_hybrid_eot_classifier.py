import asyncio

import pytest

from server.turn_policy.eot_classifier import (
    EotContext,
    EotDecision,
    EotEvidence,
    EotRequest,
)
from server.turn_policy.plugins.hybrid_eot_classifier import HybridEotClassifier


class StubEvidenceProvider:
    def __init__(self, evidence: EotEvidence) -> None:
        self._evidence = evidence

    async def evaluate(self, request: EotRequest) -> EotEvidence:
        assert request.text == "帮我查一下天气"
        assert request.context == EotContext()
        return self._evidence


class FailingEvidenceProvider:
    async def evaluate(self, request: EotRequest) -> EotEvidence:
        raise RuntimeError("provider unavailable")


class CancelledEvidenceProvider:
    async def evaluate(self, request: EotRequest) -> EotEvidence:
        raise asyncio.CancelledError


async def test_hybrid_classifier_commits_when_independent_providers_agree() -> None:
    classifier = HybridEotClassifier(
        providers=(
            StubEvidenceProvider(
                EotEvidence(
                    decision=EotDecision.COMPLETE,
                    confidence=0.91,
                    source="deepseek_responses",
                    inference_ms=720,
                )
            ),
            StubEvidenceProvider(
                EotEvidence(
                    decision=EotDecision.COMPLETE,
                    confidence=0.83,
                    source="fireredchat",
                    inference_ms=28,
                    probability=0.83,
                )
            ),
        )
    )

    result = await classifier.classify_with_context(
        text="帮我查一下天气",
        generation=7,
        context=EotContext(),
    )

    assert result.decision is EotDecision.COMPLETE
    assert result.confidence == 0.83
    assert result.source == "hybrid:deepseek_responses+fireredchat"


async def test_hybrid_classifier_uses_remaining_evidence_when_one_provider_fails() -> None:
    classifier = HybridEotClassifier(
        providers=(
            FailingEvidenceProvider(),
            StubEvidenceProvider(
                EotEvidence(
                    decision=EotDecision.INCOMPLETE,
                    confidence=0.88,
                    source="fireredchat",
                    inference_ms=31,
                    probability=0.12,
                )
            ),
        )
    )

    result = await classifier.classify(text="帮我查一下天气", generation=8)

    assert result.decision is EotDecision.INCOMPLETE
    assert result.source == "hybrid:fireredchat;degraded=RuntimeError"


async def test_hybrid_classifier_never_commits_when_providers_disagree() -> None:
    classifier = HybridEotClassifier(
        providers=(
            StubEvidenceProvider(
                EotEvidence(
                    decision=EotDecision.COMPLETE,
                    confidence=0.95,
                    source="deepseek_responses",
                )
            ),
            StubEvidenceProvider(
                EotEvidence(
                    decision=EotDecision.INCOMPLETE,
                    confidence=0.76,
                    source="fireredchat",
                    probability=0.24,
                )
            ),
        )
    )

    result = await classifier.classify(text="帮我查一下天气", generation=9)

    assert result.decision is EotDecision.UNCERTAIN
    assert result.confidence == 0.76


async def test_primary_with_shadow_keeps_primary_decision_and_retains_all_evidence() -> None:
    classifier = HybridEotClassifier(
        providers=(
            StubEvidenceProvider(
                EotEvidence(
                    decision=EotDecision.COMPLETE,
                    confidence=0.94,
                    source="deepseek_responses",
                )
            ),
            StubEvidenceProvider(
                EotEvidence(
                    decision=EotDecision.INCOMPLETE,
                    confidence=0.81,
                    source="fireredchat",
                    probability=0.19,
                )
            ),
        ),
        strategy="primary_with_shadow",
    )

    result = await classifier.classify(text="帮我查一下天气", generation=10)

    assert result.decision is EotDecision.COMPLETE
    assert result.confidence == 0.94
    assert [item.source for item in result.evidence] == [
        "deepseek_responses",
        "fireredchat",
    ]


async def test_hybrid_classifier_never_converts_cancellation_into_fallback() -> None:
    classifier = HybridEotClassifier(
        providers=(
            CancelledEvidenceProvider(),
            StubEvidenceProvider(
                EotEvidence(
                    decision=EotDecision.COMPLETE,
                    source="fireredchat",
                )
            ),
        )
    )

    with pytest.raises(asyncio.CancelledError):
        await classifier.classify(text="帮我查一下天气", generation=11)
