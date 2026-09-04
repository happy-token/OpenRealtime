"""Real `EotClassifier` conformer: a dual-scorer ensemble.

See server/turn_policy/eot_classifier.py for the `EotClassifier` and
`FastEotScorer` Protocols and their unregistered (no-op) default behavior.

Loosely inspired by voiceloop-modular-runtime's SemanticEoTProcessor, which
runs a fast always-on scorer (FireRedChat) in parallel with an optional LLM
judge and arbitrates asymmetrically. This conformer adapts that arbitration
rule to OpenRealtime's existing LlmClient/EotClassifier seams rather than
introducing a new model dependency.
"""

from __future__ import annotations

import asyncio
import logging
import time

from server.turn_policy.eot_classifier import (
    ContextualEotClassifier,
    EotClassifier,
    EotContext,
    EotDecision,
    FastEotScorer,
    PunctuationEotScorer,
    normalize_eot_classification,
)

logger = logging.getLogger(__name__)


class EnsembleEotClassifier:
    """Composes a network EotClassifier (typically LlmEotClassifier) with a
    fast, always-on FastEotScorer. Runs both concurrently:

    - punctuation is advisory by default and cannot independently end a turn;
      the legacy short-circuit remains an explicit opt-in only;
    - slow raises or exceeds its latency budget -> fail open to the fast result (mirrors LlmEotClassifier's
      own fail-open-to-COMPLETE discipline: a vendor hiccup on the slow side
      must never block on the slower path forever).
    - slow == INCOMPLETE and fast == COMPLETE -> downgrade to UNCERTAIN
      (voiceloop's disagreement rule: don't end the turn on one confident
      signal alone when the other side disagrees).
    - otherwise -> the slow result is authoritative.
    """

    def __init__(
        self,
        slow: EotClassifier,
        *,
        fast: FastEotScorer | None = None,
        slow_timeout_s: float = 0.45,
        fast_complete_short_circuit: bool = False,
    ) -> None:
        if slow_timeout_s <= 0:
            raise ValueError("slow_timeout_s must be positive")
        self._slow = slow
        self._fast = fast or PunctuationEotScorer()
        self._slow_timeout_s = slow_timeout_s
        self._fast_complete_short_circuit = fast_complete_short_circuit

    async def classify(self, *, text: str, generation: int) -> EotDecision:
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
    ) -> EotDecision:
        slow_call = (
            self._slow.classify_with_context(
                text=text,
                generation=generation,
                context=context,
            )
            if isinstance(self._slow, ContextualEotClassifier)
            else self._slow.classify(text=text, generation=generation)
        )
        slow_task = asyncio.create_task(slow_call)
        fast_task = asyncio.create_task(self._fast.score(text=text))
        started_at = time.monotonic()
        fast_result = await fast_task

        # A sentence-final punctuation signal is sufficient for the common
        # path. Give an already-finished semantic judge a chance to arbitrate,
        # but never put a network round-trip in front of an obvious EoT.
        if fast_result is EotDecision.COMPLETE and self._fast_complete_short_circuit:
            await asyncio.sleep(0)
            if not slow_task.done():
                _cancel_in_background(slow_task)
                await asyncio.sleep(0)
                return fast_result

        elapsed_s = time.monotonic() - started_at
        remaining_s = max(0.0, self._slow_timeout_s - elapsed_s)
        done, _ = await asyncio.wait({slow_task}, timeout=remaining_s)
        if not done:
            _cancel_in_background(slow_task)
            await asyncio.sleep(0)
            logger.info(
                "slow EotClassifier %s exceeded %.1fms generation=%s; falling back to fast scorer",
                type(self._slow).__name__,
                self._slow_timeout_s * 1000,
                generation,
            )
            return fast_result

        try:
            slow_result = normalize_eot_classification(slow_task.result()).decision
        except Exception:
            logger.warning(
                "slow EotClassifier %s failed after %.1fms generation=%s; falling back to fast scorer",
                type(self._slow).__name__,
                (time.monotonic() - started_at) * 1000,
                generation,
                exc_info=True,
            )
            return fast_result

        if {slow_result, fast_result} == {
            EotDecision.COMPLETE,
            EotDecision.INCOMPLETE,
        }:
            return EotDecision.UNCERTAIN
        return slow_result


def _cancel_in_background(task: asyncio.Task[EotDecision]) -> None:
    task.cancel()
    task.add_done_callback(_consume_background_result)


def _consume_background_result(task: asyncio.Task[EotDecision]) -> None:
    try:
        task.exception()
    except asyncio.CancelledError:
        pass
