import pytest

from server.turn_policy.eot_classifier import (
    EotContext,
    EotDecision,
    EotEvidence,
    EotHistoryMessage,
    EotRequest,
)
from server.turn_policy.plugins.fast_complete_fallback_eot_classifier import (
    FastCompleteFallbackEotClassifier,
)


class RecordingProvider:
    def __init__(self, evidence: EotEvidence) -> None:
        self._evidence = evidence
        self.requests: list[EotRequest] = []

    async def evaluate(self, request: EotRequest) -> EotEvidence:
        self.requests.append(request)
        return self._evidence


class FailingProvider:
    async def evaluate(self, request: EotRequest) -> EotEvidence:
        raise RuntimeError("local model unavailable")


async def test_high_confidence_closed_question_uses_fast_complete_without_llm() -> None:
    fast = RecordingProvider(
        EotEvidence(
            decision=EotDecision.COMPLETE,
            source="fireredchat",
            confidence=0.97,
            probability=0.97,
            inference_ms=42,
        )
    )
    fallback = RecordingProvider(
        EotEvidence(decision=EotDecision.INCOMPLETE, source="deepseek_responses")
    )
    classifier = FastCompleteFallbackEotClassifier(
        fast_provider=fast,
        fallback_provider=fallback,
        fast_complete_threshold=0.9,
    )

    result = await classifier.classify(text="明天上海会下雨吗", generation=3)

    assert result.decision is EotDecision.COMPLETE
    assert result.source == "fast_complete:fireredchat"
    assert result.evidence == (
        EotEvidence(
            decision=EotDecision.COMPLETE,
            source="fireredchat",
            confidence=0.97,
            probability=0.97,
            inference_ms=42,
        ),
    )
    assert len(fast.requests) == 1
    assert fallback.requests == []


@pytest.mark.parametrize("text", ["你好", "你好呀。", "您好！", "哈喽"])
async def test_high_confidence_greeting_uses_fast_complete_without_llm(
    text: str,
) -> None:
    fast = RecordingProvider(
        EotEvidence(
            decision=EotDecision.COMPLETE,
            source="fireredchat",
            confidence=0.97,
            probability=0.97,
        )
    )
    fallback = RecordingProvider(
        EotEvidence(decision=EotDecision.INCOMPLETE, source="deepseek_responses")
    )
    classifier = FastCompleteFallbackEotClassifier(
        fast_provider=fast,
        fallback_provider=fallback,
        fast_complete_threshold=0.9,
    )

    result = await classifier.classify(text=text, generation=3)

    assert result.decision is EotDecision.COMPLETE
    assert result.source == "fast_complete:fireredchat"
    assert len(fast.requests) == 1
    assert fallback.requests == []


async def test_open_ended_high_probability_result_uses_contextual_llm_fallback() -> None:
    fast = RecordingProvider(
        EotEvidence(
            decision=EotDecision.COMPLETE,
            source="fireredchat",
            confidence=0.9999,
            probability=0.9999,
        )
    )
    fallback = RecordingProvider(
        EotEvidence(
            decision=EotDecision.INCOMPLETE,
            source="deepseek_responses",
            confidence=0.96,
            wait_ms=800,
        )
    )
    classifier = FastCompleteFallbackEotClassifier(
        fast_provider=fast,
        fallback_provider=fallback,
        fast_complete_threshold=0.5,
    )
    context = EotContext(
        history=(EotHistoryMessage(role="assistant", content="你更看重哪一项？"),)
    )

    result = await classifier.classify_with_context(
        text="价格和续航相比我更看重",
        generation=4,
        context=context,
    )

    assert result.decision is EotDecision.INCOMPLETE
    assert result.wait_ms == 800
    assert result.source == "fallback:deepseek_responses;fast=fireredchat"
    assert len(fallback.requests) == 1
    assert fallback.requests[0].context == context
    assert [evidence.source for evidence in result.evidence] == [
        "fireredchat",
        "deepseek_responses",
    ]


async def test_local_model_failure_degrades_to_llm_instead_of_losing_the_turn() -> None:
    fallback = RecordingProvider(
        EotEvidence(
            decision=EotDecision.COMPLETE,
            source="deepseek_responses",
            confidence=0.93,
        )
    )
    classifier = FastCompleteFallbackEotClassifier(
        fast_provider=FailingProvider(),
        fallback_provider=fallback,
    )

    result = await classifier.classify(text="帮我查一下天气", generation=5)

    assert result.decision is EotDecision.COMPLETE
    assert result.source == "fallback:deepseek_responses;fast_degraded=RuntimeError"
    assert result.evidence == (
        EotEvidence(
            decision=EotDecision.COMPLETE,
            source="deepseek_responses",
            confidence=0.93,
        ),
    )


@pytest.mark.parametrize(
    "text",
    [
        "北京现在是几点还是",
        "那就改到周三的",
        "你把那手机给",
        "这三个里面除了中间那个",
        "我明天早上先去公司拿电脑，中午再坐高铁去",
    ],
)
async def test_clear_open_slot_vetoes_false_complete_from_llm_fallback(
    text: str,
) -> None:
    fast = RecordingProvider(
        EotEvidence(
            decision=EotDecision.COMPLETE,
            source="fireredchat",
            confidence=0.94,
            probability=0.94,
        )
    )
    fallback = RecordingProvider(
        EotEvidence(
            decision=EotDecision.COMPLETE,
            source="deepseek_responses",
            confidence=0.91,
        )
    )
    classifier = FastCompleteFallbackEotClassifier(
        fast_provider=fast,
        fallback_provider=fallback,
    )

    result = await classifier.classify(text=text, generation=6)

    assert result.decision is EotDecision.INCOMPLETE
    assert result.source == (
        "fallback_veto:open_slot;llm=deepseek_responses;fast=fireredchat"
    )
    assert result.confidence == 0.91
    assert [evidence.source for evidence in result.evidence] == [
        "fireredchat",
        "deepseek_responses",
    ]


async def test_closed_conditional_is_not_blocked_by_open_slot_safety_veto() -> None:
    fast = RecordingProvider(
        EotEvidence(
            decision=EotDecision.INCOMPLETE,
            source="fireredchat",
            confidence=0.8,
            probability=0.2,
        )
    )
    fallback = RecordingProvider(
        EotEvidence(
            decision=EotDecision.COMPLETE,
            source="deepseek_responses",
            confidence=0.95,
        )
    )
    classifier = FastCompleteFallbackEotClassifier(
        fast_provider=fast,
        fallback_provider=fallback,
    )

    result = await classifier.classify(text="要是没票那就改坐高铁", generation=7)

    assert result.decision is EotDecision.COMPLETE
    assert result.source == "fallback:deepseek_responses;fast=fireredchat"


async def test_open_slot_veto_still_applies_when_local_model_is_unavailable() -> None:
    fallback = RecordingProvider(
        EotEvidence(
            decision=EotDecision.COMPLETE,
            source="deepseek_responses",
            confidence=0.9,
        )
    )
    classifier = FastCompleteFallbackEotClassifier(
        fast_provider=FailingProvider(),
        fallback_provider=fallback,
    )

    result = await classifier.classify(text="那就改到周三的", generation=8)

    assert result.decision is EotDecision.INCOMPLETE
    assert result.source == (
        "fallback_veto:open_slot;llm=deepseek_responses;fast_degraded=RuntimeError"
    )
