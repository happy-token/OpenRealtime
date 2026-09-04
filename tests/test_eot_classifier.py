import asyncio
import json

import pytest

from server.brain.llm_clients import ChatMessage
from server.turn_policy.eot_classifier import (
    EotClassification,
    EotContext,
    EotDecision,
    EotHistoryMessage,
    PunctuationEotScorer,
)
from server.turn_policy.plugins.ensemble_eot_classifier import EnsembleEotClassifier
from server.turn_policy.plugins.llm_eot_classifier import LlmEotClassifier
from server.turn_policy.semantic_endpoint import (
    EndpointOutcome,
    EndpointResolution,
    endpoint_stability_wait_ms,
)


class StubLlmClient:
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.last_call: dict | None = None

    async def complete(self, *, system_prompt: str, user_text: str) -> str:
        self.last_call = {"system_prompt": system_prompt, "user_text": user_text}
        return self._reply


class StreamingStubLlmClient:
    def __init__(self, deltas: tuple[str, ...]) -> None:
        self._deltas = deltas
        self.complete_called = False

    async def complete(self, *, system_prompt: str, user_text: str) -> str:
        self.complete_called = True
        return "complete"

    async def stream(self, *, system_prompt: str, user_text: str):
        for delta in self._deltas:
            yield delta


class MessageStreamingStubLlmClient:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[ChatMessage, ...], int | None]] = []

    async def complete(self, *, system_prompt: str, user_text: str) -> str:
        raise AssertionError("structured message path should be used")

    async def stream_messages(self, *, messages, max_tokens=None):
        self.calls.append((messages, max_tokens))
        yield '{"status":"complete","confidence":0.9,"wait_ms":0}'


async def test_complete_reply_maps_to_complete_decision():
    classifier = LlmEotClassifier(
        StubLlmClient('{"status":"complete","confidence":0.97,"wait_ms":0}')
    )

    result = await classifier.classify(text="I want to order a pizza", generation=1)

    assert result == EotClassification(
        decision=EotDecision.COMPLETE,
        confidence=0.97,
        wait_ms=0,
        source="llm",
    )


async def test_classifier_can_expose_the_selected_provider_transport() -> None:
    classifier = LlmEotClassifier(
        StubLlmClient('{"status":"complete","confidence":0.97,"wait_ms":0}'),
        source="deepseek_responses",
    )

    result = await classifier.classify(text="现在几点", generation=1)

    assert result.source == "deepseek_responses"


async def test_incomplete_reply_maps_to_incomplete_decision():
    classifier = LlmEotClassifier(
        StubLlmClient('{"status":"incomplete","confidence":0.9,"wait_ms":0}')
    )

    result = await classifier.classify(text="I want to", generation=1)

    assert result.decision is EotDecision.INCOMPLETE


async def test_uncertain_reply_maps_to_uncertain_decision():
    classifier = LlmEotClassifier(
        StubLlmClient('{"status":"uncertain","confidence":0.51,"wait_ms":180}')
    )

    result = await classifier.classify(text="well, so", generation=1)

    assert result.decision is EotDecision.UNCERTAIN
    assert result.wait_ms == 180


async def test_garbage_reply_is_rejected_for_gate_level_fallback():
    classifier = LlmEotClassifier(StubLlmClient("¯\\_(ツ)_/¯"))

    with pytest.raises(ValueError, match="valid JSON"):
        await classifier.classify(text="anything", generation=1)


async def test_empty_reply_is_rejected_for_gate_level_fallback():
    classifier = LlmEotClassifier(StubLlmClient(""))

    with pytest.raises(ValueError, match="valid JSON"):
        await classifier.classify(text="anything", generation=1)


async def test_reply_is_case_and_whitespace_insensitive():
    classifier = LlmEotClassifier(
        StubLlmClient('  {"status":"INCOMPLETE","confidence":0.8,"wait_ms":0}\n')
    )

    result = await classifier.classify(text="anything", generation=1)

    assert result.decision is EotDecision.INCOMPLETE


async def test_classify_forwards_text_as_user_text_to_llm_client():
    llm_client = StubLlmClient(
        '{"status":"complete","confidence":0.9,"wait_ms":0}'
    )
    classifier = LlmEotClassifier(llm_client)

    await classifier.classify(text="is this a complete thought", generation=7)

    assert llm_client.last_call is not None
    assert json.loads(llm_client.last_call["user_text"]) == {
        "transcript": "is this a complete thought"
    }


async def test_context_history_is_a_stable_message_prefix_for_provider_kv_cache():
    llm_client = MessageStreamingStubLlmClient()
    classifier = LlmEotClassifier(llm_client)
    context = EotContext(
        history=(
            EotHistoryMessage(role="user", content="我想订明天的票"),
            EotHistoryMessage(role="assistant", content="你想去哪里？"),
        )
    )

    await classifier.classify_with_context(
        text="北京",
        generation=1,
        context=context,
    )
    await classifier.classify_with_context(
        text="北京南站",
        generation=1,
        context=context,
    )

    first_messages, first_max_tokens = llm_client.calls[0]
    second_messages, second_max_tokens = llm_client.calls[1]
    assert first_messages[:-1] == second_messages[:-1]
    assert [message.role for message in first_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert json.loads(first_messages[-1].content) == {"transcript": "北京"}
    assert json.loads(second_messages[-1].content) == {"transcript": "北京南站"}
    assert first_max_tokens == second_max_tokens == 64


async def test_classifier_prompt_marks_short_self_contained_turns_complete():
    llm_client = StubLlmClient(
        '{"status":"complete","confidence":0.9,"wait_ms":0}'
    )
    classifier = LlmEotClassifier(llm_client)

    await classifier.classify(text="你好。", generation=1)

    assert llm_client.last_call is not None
    prompt = llm_client.last_call["system_prompt"]
    assert "你好" in prompt
    assert "换一个" in prompt
    assert "short" in prompt.lower()


def test_incomplete_wait_hint_is_bounded_by_hard_timeout():
    outcome = EndpointOutcome(
        resolution=EndpointResolution.HOLD_INCOMPLETE,
        classification=EotClassification(
            decision=EotDecision.INCOMPLETE,
            confidence=0.9,
            wait_ms=500,
            source="llm",
        ),
    )

    assert endpoint_stability_wait_ms(
        outcome,
        incomplete_timeout_ms=5000,
        uncertain_wait_ms=300,
    ) == 500


def test_incomplete_without_wait_hint_uses_hard_timeout():
    outcome = EndpointOutcome(
        resolution=EndpointResolution.HOLD_INCOMPLETE,
        classification=EotClassification(
            decision=EotDecision.INCOMPLETE,
            confidence=0.9,
            source="llm",
        ),
    )

    assert endpoint_stability_wait_ms(
        outcome,
        incomplete_timeout_ms=5000,
        uncertain_wait_ms=300,
    ) == 5000


def test_incomplete_wait_hint_cannot_shrink_below_stability_floor():
    outcome = EndpointOutcome(
        resolution=EndpointResolution.HOLD_INCOMPLETE,
        classification=EotClassification(
            decision=EotDecision.INCOMPLETE,
            confidence=0.9,
            wait_ms=20,
            source="llm",
        ),
    )

    assert endpoint_stability_wait_ms(
        outcome,
        incomplete_timeout_ms=5000,
        uncertain_wait_ms=300,
    ) == 300


async def test_classifier_returns_on_first_complete_streamed_label():
    llm_client = StreamingStubLlmClient(
        ('{"status":"incomplete",', '"confidence":0.93,"wait_ms":0}', "ignored")
    )
    classifier = LlmEotClassifier(llm_client)

    result = await classifier.classify(text="I want to", generation=1)

    assert result.decision is EotDecision.INCOMPLETE
    assert llm_client.complete_called is False


class RaisingEotClassifier:
    async def classify(self, *, text: str, generation: int) -> EotDecision:
        raise RuntimeError("HTTP Error 400")


class StubEotClassifier:
    def __init__(self, decision: EotDecision) -> None:
        self._decision = decision

    async def classify(self, *, text: str, generation: int) -> EotDecision:
        return self._decision


class StubFastEotScorer:
    def __init__(self, decision: EotDecision) -> None:
        self._decision = decision

    async def score(self, *, text: str) -> EotDecision:
        return self._decision


class GatedEotClassifier:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def classify(self, *, text: str, generation: int) -> EotDecision:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class SlowCancellationEotClassifier:
    async def classify(self, *, text: str, generation: int) -> EotDecision:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.1)
            raise


class DelayedEotClassifier:
    def __init__(self, decision: EotDecision) -> None:
        self._decision = decision
        self.calls = 0

    async def classify(self, *, text: str, generation: int) -> EotDecision:
        del text, generation
        self.calls += 1
        await asyncio.sleep(0.01)
        return self._decision


async def test_punctuation_scorer_sentence_final_punctuation_is_complete():
    scorer = PunctuationEotScorer()

    decision = await scorer.score(text="I'd like a pizza.")

    assert decision is EotDecision.COMPLETE


async def test_punctuation_scorer_trailing_connective_is_incomplete():
    scorer = PunctuationEotScorer()

    decision = await scorer.score(text="I'd like a pizza and")

    assert decision is EotDecision.INCOMPLETE


async def test_punctuation_scorer_no_cue_is_uncertain():
    scorer = PunctuationEotScorer()

    decision = await scorer.score(text="I'd like a pizza")

    assert decision is EotDecision.UNCERTAIN


async def test_punctuation_scorer_empty_text_is_uncertain():
    scorer = PunctuationEotScorer()

    decision = await scorer.score(text="   ")

    assert decision is EotDecision.UNCERTAIN


async def test_ensemble_classifier_uses_slow_result_when_both_agree():
    ensemble = EnsembleEotClassifier(
        StubEotClassifier(EotDecision.COMPLETE), fast=StubFastEotScorer(EotDecision.COMPLETE)
    )

    decision = await ensemble.classify(text="anything", generation=1)

    assert decision is EotDecision.COMPLETE


async def test_ensemble_classifier_downgrades_to_uncertain_on_disagreement():
    ensemble = EnsembleEotClassifier(
        StubEotClassifier(EotDecision.INCOMPLETE), fast=StubFastEotScorer(EotDecision.COMPLETE)
    )

    decision = await ensemble.classify(text="anything", generation=1)

    assert decision is EotDecision.UNCERTAIN


async def test_ensemble_classifier_downgrades_reverse_disagreement_to_uncertain():
    ensemble = EnsembleEotClassifier(
        StubEotClassifier(EotDecision.COMPLETE),
        fast=StubFastEotScorer(EotDecision.INCOMPLETE),
    )

    decision = await ensemble.classify(text="anything", generation=1)

    assert decision is EotDecision.UNCERTAIN


async def test_ensemble_classifier_falls_open_to_fast_result_when_slow_raises():
    ensemble = EnsembleEotClassifier(
        RaisingEotClassifier(), fast=StubFastEotScorer(EotDecision.INCOMPLETE)
    )

    decision = await ensemble.classify(text="anything", generation=1)

    assert decision is EotDecision.INCOMPLETE


async def test_ensemble_classifier_logs_which_side_failed_before_falling_open(caplog):
    ensemble = EnsembleEotClassifier(
        RaisingEotClassifier(), fast=StubFastEotScorer(EotDecision.INCOMPLETE)
    )

    with caplog.at_level("WARNING"):
        await ensemble.classify(text="anything", generation=1)

    record = caplog.records[-1]
    assert "RaisingEotClassifier" in record.message
    assert "generation=1" in record.message
    assert record.exc_info is not None


async def test_ensemble_fast_complete_path_does_not_wait_for_network_classifier():
    slow = GatedEotClassifier()
    ensemble = EnsembleEotClassifier(
        slow,
        fast=StubFastEotScorer(EotDecision.COMPLETE),
        slow_timeout_s=1.0,
        fast_complete_short_circuit=True,
    )

    decision = await asyncio.wait_for(
        ensemble.classify(text="已经说完。", generation=1),
        timeout=0.05,
    )

    assert decision is EotDecision.COMPLETE
    assert slow.cancelled is True


async def test_ensemble_can_require_bounded_slow_judgement_despite_punctuation():
    slow = DelayedEotClassifier(EotDecision.INCOMPLETE)
    ensemble = EnsembleEotClassifier(
        slow,
        fast=StubFastEotScorer(EotDecision.COMPLETE),
        slow_timeout_s=0.1,
    )

    decision = await ensemble.classify(text="我想。", generation=1)

    assert decision is EotDecision.UNCERTAIN
    assert slow.calls == 1


async def test_ensemble_network_classifier_has_a_hard_latency_budget():
    slow = GatedEotClassifier()
    ensemble = EnsembleEotClassifier(
        slow,
        fast=StubFastEotScorer(EotDecision.UNCERTAIN),
        slow_timeout_s=0.01,
    )

    decision = await ensemble.classify(text="也许还没说完", generation=1)

    assert decision is EotDecision.UNCERTAIN
    assert slow.cancelled is True


async def test_ensemble_timeout_does_not_wait_for_slow_client_cleanup():
    ensemble = EnsembleEotClassifier(
        SlowCancellationEotClassifier(),
        fast=StubFastEotScorer(EotDecision.UNCERTAIN),
        slow_timeout_s=0.01,
    )

    decision = await asyncio.wait_for(
        ensemble.classify(text="网络清理不能阻塞响应", generation=1),
        timeout=0.05,
    )

    assert decision is EotDecision.UNCERTAIN
