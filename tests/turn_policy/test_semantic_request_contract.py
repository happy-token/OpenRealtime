from __future__ import annotations

import asyncio
import json

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    InMemoryConversationJournal,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.realtime.capabilities.asr import AsrEndpointHint
from server.realtime.capabilities.turn_manager import (
    LegacyTurnManagerCapabilityAdapter,
    ObserveAsrEvent,
    ObserveConversationItem,
)
from server.turn_policy.eot_classifier import (
    EotClassification,
    EotContext,
    EotDecision,
    EotEvidence,
    EotHistoryMessage,
    EotRequest,
    classify_eot,
)
from server.turn_policy.plugins.classifier_eot_evidence_provider import (
    ClassifierEotEvidenceProvider,
)
from server.turn_policy.plugins.fast_complete_fallback_eot_classifier import (
    FastCompleteFallbackEotClassifier,
)
from server.turn_policy.plugins.hybrid_eot_classifier import HybridEotClassifier
from server.turn_policy.plugins.llm_eot_classifier import LlmEotClassifier
from server.turn_policy.plugins.llm_semantic_interruption_classifier import (
    LlmSemanticInterruptionClassifier,
)
from server.turn_policy.policy import TurnPolicy
from server.turn_policy.semantic_endpoint import EndpointCandidate, SemanticEndpointGate
from server.turn_policy.semantic_input import SemanticInputState, TextBoundary
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionCandidate,
    InterruptionClassification,
    InterruptionLabel,
    InterruptionRequest,
    SemanticInterruptionGate,
)
from server.turn_policy.states import DialogueState

HISTORY = (EotHistoryMessage("user", "我要退货"), EotHistoryMessage("assistant", "是质量问题吗？"))
STATE = SemanticInputState(
    transcript_revision=3,
    boundary=TextBoundary.SENTENCE_END,
    dialogue_state=DialogueState.LISTEN,
    speech_active=False,
    silence_duration_ms=120,
)


class RequestClassifier:
    def __init__(self):
        self.requests = []
        self.called = asyncio.Event()

    async def classify_request(self, request):
        self.requests.append(request)
        self.called.set()
        return EotClassification(EotDecision.COMPLETE, confidence=0.9)


@pytest.mark.asyncio
async def test_endpoint_delivers_history_and_input_state_to_request_only_plugin():
    plugin = RequestClassifier()
    candidate = EndpointCandidate("是的", 1, 3, history=HISTORY, input_state=STATE)
    classification, error = await SemanticEndpointGate(plugin)._classify(candidate)
    assert error is None
    assert classification.decision is EotDecision.COMPLETE
    assert plugin.requests[0].context.history == HISTORY
    assert plugin.requests[0].input_state == STATE


@pytest.mark.asyncio
async def test_runtime_keeps_both_sides_of_previous_exchange_under_history_budget():
    context = InteractionContext("test", "alice", "browser", "voice", "thread", "turn", 1)
    plugin = RequestClassifier()
    session = await LegacyTurnManagerCapabilityAdapter(
        TurnPolicy, eot_classifier=plugin, history_max_chars=10
    ).open(context=context)
    journal = InMemoryConversationJournal()
    try:
        for index, (kind, text) in enumerate(
            (
                (ConversationItemKind.USER_INPUT, "上一轮用户问题"),
                (ConversationItemKind.ASSISTANT_OUTPUT, "上一轮很长的助手回答" * 10),
            )
        ):
            result = await journal.append(
                ConversationItemDraft(
                    item_id=f"history-{index}",
                    context=context,
                    kind=kind,
                    status=ConversationItemStatus.COMPLETED,
                    producer="test",
                    content=(TextContent(text),),
                )
            )
            await session.send(ObserveConversationItem(item=result.item))
        await session.send(
            ObserveAsrEvent(event=AsrEndpointHint(context=context, revision=3, text="是的"))
        )
        await asyncio.wait_for(plugin.called.wait(), timeout=1)
        request = plugin.requests[-1]
        assert [message.role for message in request.context.history] == ["user", "assistant"]
        assert sum(len(message.content) for message in request.context.history) <= 10
        assert request.context.history[-1].truncated
        assert request.input_state.transcript_revision == 3
        assert request.input_state.boundary is TextBoundary.SENTENCE_END
        assert request.interaction == context
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_legacy_text_only_plugin_works_with_and_without_history():
    class TextOnly:
        async def classify(self, *, text, generation):
            assert text == "是的"
            return EotDecision.COMPLETE

    for history in ((), HISTORY):
        result = await classify_eot(TextOnly(), EotRequest("是的", 1, EotContext(history)))
        assert result.decision is EotDecision.COMPLETE


@pytest.mark.asyncio
async def test_hybrid_and_fast_fallback_preserve_the_entire_request():
    plugin = RequestClassifier()
    provider = ClassifierEotEvidenceProvider(plugin)
    request = EotRequest("是的", 1, EotContext(HISTORY), input_state=STATE)
    await classify_eot(HybridEotClassifier(providers=(provider,)), request)

    class Fast:
        async def evaluate(self, request):
            return EotEvidence(EotDecision.UNCERTAIN, "fast")

    await classify_eot(
        FastCompleteFallbackEotClassifier(fast_provider=Fast(), fallback_provider=provider), request
    )
    assert plugin.requests == [request, request]


@pytest.mark.asyncio
async def test_interruption_gate_delivers_history_revision_and_assistant_text():
    class RequestPlugin:
        def __init__(self):
            self.request = None

        async def classify_request(self, request):
            self.request = request
            return InterruptionClassification(InterruptionLabel.INTERRUPT, 0.95)

    plugin = RequestPlugin()
    gate = SemanticInterruptionGate(plugin)
    try:
        await gate.begin(generation=1, assistant_text="请提供订单号", history=HISTORY)
        verdict = await gate.resolve(
            InterruptionCandidate("我想换货", 1, 3, InterruptionBoundary.SENTENCE_END)
        )
        assert verdict.should_stop
        assert plugin.request.history == HISTORY
        assert plugin.request.assistant_text == "请提供订单号"
        assert plugin.request.input_state.transcript_revision == 3
        assert plugin.request.input_state.boundary is TextBoundary.SENTENCE_END
    finally:
        await gate.reset()


@pytest.mark.asyncio
async def test_llm_interruption_serializes_rich_input_without_identity_secrets():
    class Client:
        async def complete(self, *, system_prompt, user_text):
            self.payload = json.loads(user_text)
            return '{"label":"interrupt","confidence":0.9}'

    client = Client()
    await LlmSemanticInterruptionClassifier(client).classify_request(
        InterruptionRequest(
            "我想换货",
            "请提供订单号",
            1,
            InterruptionBoundary.SENTENCE_END,
            history=HISTORY,
            input_state=STATE,
        )
    )
    assert client.payload["history"][-1]["content"] == "是质量问题吗？"
    assert client.payload["input_state"]["dialogue_state"] == "listen"
    assert "interaction" not in client.payload


@pytest.mark.asyncio
async def test_llm_endpoint_receives_previous_exchange_and_current_state():
    class Client:
        async def complete(self, *, system_prompt, user_text):
            self.user_text = user_text
            return '{"status":"complete","confidence":0.9,"wait_ms":0}'

    client = Client()
    result = await classify_eot(
        LlmEotClassifier(client), EotRequest("是的", 1, EotContext(HISTORY), input_state=STATE)
    )
    assert result.decision is EotDecision.COMPLETE
    assert "是质量问题吗？" in client.user_text
    assert '"transcript_revision":3' in client.user_text


def test_history_is_immutable_and_contract_version_is_checked():
    with pytest.raises(ValueError):
        EotContext(history=list(HISTORY))
    with pytest.raises(ValueError):
        EotRequest("是的", 1, contract_version=2)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_non_finite_or_negative_observations_and_outputs_are_rejected(value):
    with pytest.raises(ValueError):
        SemanticInputState(silence_duration_ms=value)
    with pytest.raises(ValueError):
        EotClassification(EotDecision.COMPLETE, wait_ms=value)
    with pytest.raises(ValueError):
        InterruptionClassification(InterruptionLabel.STOP, value)
