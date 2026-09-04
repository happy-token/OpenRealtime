"""Conservative local-complete fast path with contextual fallback evidence."""

from __future__ import annotations

import re

from server.turn_policy.eot_classifier import (
    EotClassification,
    EotContext,
    EotDecision,
    EotEvidence,
    EotEvidenceProvider,
    EotRequest,
)

_TRAILING_PUNCTUATION = re.compile(r"[，。？！,.?!\s]+$")
_CLOSED_PATTERNS = (
    re.compile(r"^(你好|你好呀|您好|您好呀|嗨|哈喽|早上好|下午好|晚上好)$"),
    re.compile(r"(吗|么|呢)$"),
    re.compile(
        r"(谁|哪儿|哪里|几点|多少|多久|多远|怎么样|怎么走|怎么做|为什么|"
        r"什么时候|什么时间|哪一天|哪天)$"
    ),
    re.compile(r"(吧|就行|即可|谢谢)$"),
    re.compile(r"^(好|好的|可以|可以啊|行|对|嗯对|不用|不需要|就这样|就这样吧)$"),
)
_CLEAR_OPEN_SLOT_PATTERNS = (
    re.compile(
        r"(还是|然后|但是|不过|而且|所以|因为|以及|或者|和|或|如果|要是|"
        r"只要|除非|不然|否则)$"
    ),
    re.compile(r"(改到|调成|应该是|目的地是|发给|给|从|到|向)$"),
    re.compile(r"(周[一二三四五六日天]|上午|下午|晚上)的$"),
    re.compile(r"除了.+(这个|那个|一种|一个)$"),
    re.compile(r"坐.+去$"),
)


class FastCompleteFallbackEotClassifier:
    """Accept only conservative local COMPLETE evidence; fallback otherwise."""

    def __init__(
        self,
        *,
        fast_provider: EotEvidenceProvider,
        fallback_provider: EotEvidenceProvider,
        fast_complete_threshold: float = 0.5,
    ) -> None:
        if not 0.0 < fast_complete_threshold <= 1.0:
            raise ValueError("fast complete threshold must be between 0 and 1")
        self._fast_provider = fast_provider
        self._fallback_provider = fallback_provider
        self._fast_complete_threshold = fast_complete_threshold

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
        request = EotRequest(
            text=text,
            generation=generation,
            context=context,
            language="zh-CN",
        )
        try:
            fast = await self._fast_provider.evaluate(request)
        except Exception as error:  # noqa: BLE001 - provider degradation boundary
            fallback = await self._fallback_provider.evaluate(request)
            return self._resolve_fallback(
                text=request.text,
                fallback=fallback,
                evidence=(fallback,),
                source_suffix=f";fast_degraded={type(error).__name__}",
            )
        if self._can_fast_complete(request.text, fast):
            return EotClassification(
                decision=EotDecision.COMPLETE,
                confidence=fast.confidence,
                wait_ms=fast.wait_ms,
                source=f"fast_complete:{fast.source}",
                evidence=(fast,),
            )
        fallback = await self._fallback_provider.evaluate(request)
        return self._resolve_fallback(
            text=request.text,
            fallback=fallback,
            evidence=(fast, fallback),
            source_suffix=f";fast={fast.source}",
        )

    def _resolve_fallback(
        self,
        *,
        text: str,
        fallback: EotEvidence,
        evidence: tuple[EotEvidence, ...],
        source_suffix: str,
    ) -> EotClassification:
        if fallback.decision is EotDecision.COMPLETE and self._has_clear_open_slot(text):
            return EotClassification(
                decision=EotDecision.INCOMPLETE,
                confidence=fallback.confidence,
                wait_ms=0,
                source=(
                    f"fallback_veto:open_slot;llm={fallback.source}{source_suffix}"
                ),
                evidence=evidence,
            )
        return EotClassification(
            decision=fallback.decision,
            confidence=fallback.confidence,
            wait_ms=fallback.wait_ms,
            source=f"fallback:{fallback.source}{source_suffix}",
            evidence=evidence,
        )

    def _can_fast_complete(self, text: str, evidence: EotEvidence) -> bool:
        score = (
            evidence.probability
            if evidence.probability is not None
            else evidence.confidence
        )
        if (
            evidence.decision is not EotDecision.COMPLETE
            or score is None
            or score < self._fast_complete_threshold
        ):
            return False
        normalized = _TRAILING_PUNCTUATION.sub("", text)
        return any(pattern.search(normalized) for pattern in _CLOSED_PATTERNS)

    @staticmethod
    def _has_clear_open_slot(text: str) -> bool:
        normalized = _TRAILING_PUNCTUATION.sub("", text)
        return any(pattern.search(normalized) for pattern in _CLEAR_OPEN_SLOT_PATTERNS)
