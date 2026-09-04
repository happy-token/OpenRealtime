from server.turn_policy.eot_classifier import (
    EotClassification,
    EotContext,
    EotDecision,
    EotHistoryMessage,
    EotRequest,
)
from server.turn_policy.plugins.classifier_eot_evidence_provider import (
    ClassifierEotEvidenceProvider,
)


class ContextRecordingClassifier:
    def __init__(self) -> None:
        self.context: EotContext | None = None

    async def classify(self, *, text: str, generation: int) -> EotClassification:
        raise AssertionError("context-aware path must be used")

    async def classify_with_context(
        self,
        *,
        text: str,
        generation: int,
        context: EotContext,
    ) -> EotClassification:
        self.context = context
        return EotClassification(
            decision=EotDecision.COMPLETE,
            confidence=0.93,
            source="deepseek_responses",
        )


async def test_classifier_adapter_preserves_history_and_rich_result() -> None:
    classifier = ContextRecordingClassifier()
    provider = ClassifierEotEvidenceProvider(classifier)
    context = EotContext(
        history=(EotHistoryMessage(role="assistant", content="你想去哪里？"),)
    )

    evidence = await provider.evaluate(
        EotRequest(text="北京", generation=4, context=context)
    )

    assert classifier.context == context
    assert evidence.decision is EotDecision.COMPLETE
    assert evidence.confidence == 0.93
    assert evidence.source == "deepseek_responses"
    assert evidence.inference_ms >= 0
