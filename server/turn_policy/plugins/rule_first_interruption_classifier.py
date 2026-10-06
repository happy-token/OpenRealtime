"""Local exact rules and rule-first model composition, independent of runtime I/O."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from server.turn_policy.interruption_rules import (
    InterruptionRuleContext,
    InterruptionRuleProvider,
    RuleFirstInterruptionDecision,
)
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionClassification,
    InterruptionLabel,
    InterruptionRequest,
)

_IMMEDIATE_STOP_PHRASES = frozenset(
    {
        "别说了",
        "不要说了",
        "先别说了",
        "闭嘴",
        "够了",
        "不用说了",
        "别讲了",
        "不要讲了",
        "wait",
        "holdon",
        "hangon",
    }
)
_BOUNDARY_STOP_PHRASES = frozenset({"停", "停止", "别说", "stop"})
_BACKCHANNEL_PHRASES = frozenset(
    {
        "嗯",
        "嗯嗯",
        "哼哼",
        "啊",
        "哦",
        "噢",
        "好",
        "好的",
        "行",
        "可以",
        "对",
        "是的",
        "没错",
        "继续",
        "你继续",
        "你继续讲",
        "我在听",
        "哈哈",
        "哈哈哈",
        "mhm",
        "mmhmm",
        "okay",
        "yes",
    }
)
_TRAILING_PUNCTUATION = "。！？，；：.!?,;:"


def _normalize_rule_text(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold().rstrip(_TRAILING_PUNCTUATION)


@dataclass(frozen=True, slots=True)
class ExactInterruptionRules:
    immediate_stops: frozenset[str] = _IMMEDIATE_STOP_PHRASES
    boundary_stops: frozenset[str] = _BOUNDARY_STOP_PHRASES
    backchannels: frozenset[str] = _BACKCHANNEL_PHRASES

    def match_exact(
        self, text: str, *, boundary: InterruptionBoundary, stable: bool = False
    ) -> InterruptionClassification | None:
        normalized = _normalize_rule_text(text)
        if normalized in self.immediate_stops:
            return InterruptionClassification(InterruptionLabel.STOP, 1)
        if normalized in self.boundary_stops and (
            stable or boundary is InterruptionBoundary.SENTENCE_END
        ):
            return InterruptionClassification(InterruptionLabel.STOP, 1)
        if normalized in self.backchannels:
            return InterruptionClassification(InterruptionLabel.BACKCHANNEL, 1)
        return None

    def match(self, context: InterruptionRuleContext) -> InterruptionClassification | None:
        result = self.match_exact(context.text, boundary=context.boundary)
        if (
            context.previous_chunks
            and result is not None
            and (
                result.label is InterruptionLabel.STOP
                or (
                    result.label is InterruptionLabel.BACKCHANNEL
                    and not context.previous_feedback_only
                )
            )
        ):
            result = None
        question = any(mark in context.assistant_text for mark in ("?", "？"))
        if (
            result is not None
            and result.label is InterruptionLabel.BACKCHANNEL
            and (question or context.boundary is InterruptionBoundary.PARTIAL)
        ):
            return None
        return result


class RuleFirstInterruptionClassifier:
    def __init__(
        self,
        *,
        model_call: Callable[[InterruptionRequest], Awaitable[InterruptionClassification]],
        rules: InterruptionRuleProvider | None = None,
    ) -> None:
        self.rules = rules if rules is not None else ExactInterruptionRules()
        self._model_call = model_call

    def match_rule(self, context: InterruptionRuleContext) -> InterruptionClassification | None:
        return self.rules.match(context)

    async def resolve(
        self, request: InterruptionRequest, rule: InterruptionClassification | None
    ) -> RuleFirstInterruptionDecision:
        if rule is not None:
            return RuleFirstInterruptionDecision(rule, "rule")
        result = await self._model_call(request)
        if not isinstance(result, InterruptionClassification):
            raise TypeError("unsupported interruption classification")
        return RuleFirstInterruptionDecision(result, "model")

    async def decide(
        self, request: InterruptionRequest, context: InterruptionRuleContext
    ) -> RuleFirstInterruptionDecision:
        if context.text != request.transcript or context.boundary is not request.boundary:
            raise ValueError("rule context must match the interruption request")
        return await self.resolve(request, self.match_rule(context))

    async def classify_request(self, request: InterruptionRequest) -> InterruptionClassification:
        context = InterruptionRuleContext(
            text=request.transcript,
            boundary=request.boundary,
            assistant_text=request.assistant_text,
            previous_chunks=request.input_state.previous_chunks,
        )
        return (await self.decide(request, context)).classification
