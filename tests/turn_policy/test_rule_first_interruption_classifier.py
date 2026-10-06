from __future__ import annotations

from dataclasses import replace

import pytest

from server.turn_policy.interruption_rules import InterruptionRuleContext
from server.turn_policy.plugins.rule_first_interruption_classifier import (
    ExactInterruptionRules,
    RuleFirstInterruptionClassifier,
)
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionClassification,
    InterruptionLabel,
    InterruptionRequest,
)


def request(text):
    return InterruptionRequest(
        transcript=text,
        assistant_text="正在介绍三个方案",
        generation=1,
        boundary=InterruptionBoundary.SENTENCE_END,
    )


@pytest.mark.parametrize(
    "text,label",
    [
        ("别说了", InterruptionLabel.STOP),
        ("嗯", InterruptionLabel.BACKCHANNEL),
        ("哼哼。", InterruptionLabel.BACKCHANNEL),
        ("我在听", InterruptionLabel.BACKCHANNEL),
        ("你继续讲", InterruptionLabel.BACKCHANNEL),
    ],
)
async def test_rule_hit_never_calls_model(text, label):
    async def no_model(request):
        raise AssertionError("JEV must not be called on a rule hit")

    plugin = RuleFirstInterruptionClassifier(model_call=no_model)
    result = await plugin.decide(
        request(text),
        InterruptionRuleContext(text=text, boundary=InterruptionBoundary.SENTENCE_END),
    )
    assert result.classification.label is label
    assert result.source == "rule"


async def test_miss_calls_model_once_and_preserves_request_context():
    calls = []

    async def model(req):
        calls.append(req)
        return InterruptionClassification(InterruptionLabel.CORRECTION, 0.9)

    plugin = RuleFirstInterruptionClassifier(model_call=model)
    req = request("地点不对，请改成上海")
    decision = await plugin.decide(
        req, InterruptionRuleContext(text=req.transcript, boundary=req.boundary)
    )
    assert calls == [req]
    assert decision.source == "model"


@pytest.mark.parametrize(
    "context",
    [
        InterruptionRuleContext(
            text="停止", boundary=InterruptionBoundary.SENTENCE_END, previous_chunks=("我不是让你",)
        ),
        InterruptionRuleContext(
            text="好的", boundary=InterruptionBoundary.SENTENCE_END, assistant_text="你要换城市吗？"
        ),
        InterruptionRuleContext(text="嗯", boundary=InterruptionBoundary.PARTIAL),
    ],
)
async def test_ambiguous_rules_fall_back_to_model(context):
    calls = []

    async def model(req):
        calls.append(req)
        return InterruptionClassification(InterruptionLabel.UNCERTAIN, 0.4)

    plugin = RuleFirstInterruptionClassifier(model_call=model)
    result = await plugin.decide(replace(request(context.text), boundary=context.boundary), context)
    assert result.source == "model"
    assert len(calls) == 1


def test_exact_rules_can_be_replaced_without_changing_coordinator():
    default = ExactInterruptionRules()
    context = InterruptionRuleContext(text="收到", boundary=InterruptionBoundary.SENTENCE_END)
    assert default.match(context) is None
    custom = ExactInterruptionRules(backchannels=frozenset({"收到"}))
    assert custom.match(context).label is InterruptionLabel.BACKCHANNEL
    assert custom.match(replace(context, text="我不是让你停")) is None


async def test_mismatched_rule_context_cannot_override_request():
    async def no_model(request):
        raise AssertionError("invalid context must not reach model")

    plugin = RuleFirstInterruptionClassifier(model_call=no_model)
    with pytest.raises(ValueError, match="must match"):
        await plugin.decide(
            request("不要停止"),
            InterruptionRuleContext(text="停止", boundary=InterruptionBoundary.SENTENCE_END),
        )
