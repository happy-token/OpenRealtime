"""Real, content-aware `DualIntentClassifier` conformer.

See server/turn_policy/dual_intent.py for the `DualIntentClassifier`
Protocol and the shipped duration-only default this falls back to.
"""

from __future__ import annotations

from server.brain.llm_clients import LlmClient
from server.turn_policy.dual_intent import (
    DefaultDualIntentClassifier,
    DualIntent,
    DualIntentClassifier,
)

DEFAULT_SYSTEM_PROMPT = (
    "You judge why a speaker's voice overlapped an assistant that was "
    "already talking. Reply with exactly two space-separated tokens: a "
    "label (stop, correction, interrupt, backchannel, ignore, or "
    'uncertain) and a confidence between 0 and 1, e.g. "stop 0.92".'
)

DEFAULT_STOP_PHRASES: tuple[str, ...] = (
    "stop",
    "wait",
    "hold on",
    "hang on",
    "停",
    "等等",
    "打断一下",
    "不是不是",
)


def _parse_confidence(token: str) -> float | None:
    try:
        return float(token)
    except ValueError:
        return None


class LlmDualIntentClassifier:
    """Content-aware conformer built entirely on the existing LlmClient seam —
    no new vendor or dependency. Six-label taxonomy (inspired by voiceloop's
    semantic_interruption.py) gives the LLM richer discriminative categories
    than a bare binary choice, even though the output stays the existing
    binary DualIntent: stop/correction/interrupt collapse to FLOOR_CLAIM,
    backchannel to BACKCHANNEL. Empty text, ignore/uncertain, and anything
    unparseable all fall back to the duration heuristic rather than guessing
    a fixed direction — see ADR-0015 and LlmEotClassifier's own fail-open
    discipline.

    Two additions ahead of the LLM round-trip and its parsing, new design
    work loosely inspired by voiceloop's filler-gate RuleMatcher rather than
    a port of anything voiceloop's own interruption path runs (see
    ADR-0020): a rules-first stop-phrase check that short-circuits to
    FLOOR_CLAIM before ever calling the LLM, and a confidence threshold that
    demotes a low-confidence stop/correction/interrupt reply to the fallback
    instead of manufacturing a floor-claim from an unsure judge. Backchannel
    is not confidence-gated — a false backchannel just means the assistant
    keeps talking, so there's no false-interruption risk to guard against.
    """

    def __init__(
        self,
        llm_client: LlmClient,
        *,
        fallback: DualIntentClassifier | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        stop_phrases: tuple[str, ...] = DEFAULT_STOP_PHRASES,
        confidence_threshold: float = 0.8,
    ) -> None:
        self._llm_client = llm_client
        self._fallback = fallback or DefaultDualIntentClassifier()
        self._system_prompt = system_prompt
        self._stop_phrases = stop_phrases
        self._confidence_threshold = confidence_threshold

    async def classify(self, *, generation: int, overlap_ms: float, text: str) -> DualIntent:
        if not text:
            return await self._fallback.classify(
                generation=generation, overlap_ms=overlap_ms, text=text
            )

        normalized_text = text.strip().lower()
        if any(phrase in normalized_text for phrase in self._stop_phrases):
            return DualIntent.FLOOR_CLAIM

        reply = await self._llm_client.complete(system_prompt=self._system_prompt, user_text=text)
        tokens = reply.strip().split()
        label = tokens[0].lower() if tokens else ""

        if label in {"stop", "correction", "interrupt"}:
            confidence = _parse_confidence(tokens[1]) if len(tokens) > 1 else None
            if confidence is not None and confidence >= self._confidence_threshold:
                return DualIntent.FLOOR_CLAIM
            return await self._fallback.classify(
                generation=generation, overlap_ms=overlap_ms, text=text
            )
        if label == "backchannel":
            return DualIntent.BACKCHANNEL
        return await self._fallback.classify(generation=generation, overlap_ms=overlap_ms, text=text)
