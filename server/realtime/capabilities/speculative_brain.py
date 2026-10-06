"""Deduplicated speculative buffer around a ``StreamingBrain``.

``prepare`` starts one provider stream for a transcript revision before Turn
Policy commits it.  ``stream`` later replays buffered deltas and follows the
same live producer, so semantic endpoint latency overlaps model generation
without issuing a duplicate LLM request. A provider-final revision that only
adds terminal sentence punctuation reuses the same producer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from server.core.turn_content import TurnContent, same_asr_utterance
from server.realtime.capabilities.brain_streaming import StreamingTextBrain

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _PrefetchState:
    turn: TurnContent
    started_ns: int = field(default_factory=time.monotonic_ns)
    first_delta_ns: int | None = None
    chunks: list[str] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None
    done: bool = False
    invalidated: bool = False
    error: Exception | None = None


class SpeculativeStreamingBrain:
    """One active speculative LLM request per voice-session Brain instance."""

    def __init__(
        self,
        brain: StreamingTextBrain,
        *,
        observer: Callable[[str, TurnContent, dict[str, Any]], None] | None = None,
    ) -> None:
        self._brain = brain
        self._observer = observer
        self._state: _PrefetchState | None = None
        self._lock = asyncio.Lock()

    def _observe(self, operation: str, turn: TurnContent, **attributes: Any) -> None:
        if self._observer is not None:
            try:
                self._observer(operation, turn, attributes)
            except Exception:
                logger.warning("Response prefetch observer failed", exc_info=True)

    async def prepare(self, turn: TurnContent) -> bool:
        """Start a response once; return False when the exact turn is cached."""
        async with self._lock:
            current = self._state
            if current is not None and _same_turn(current.turn, turn) and not current.invalidated:
                return False
            state = _PrefetchState(turn=turn)
            state.task = asyncio.create_task(
                self._produce(state),
                name=f"speculative-brain-{turn.generation}",
            )
            self._state = state
        if current is not None:
            await self._discard(current)
        return True

    async def invalidate(self, generation: int, *, reason: str) -> bool:
        async with self._lock:
            state = self._state
            if state is None or state.turn.generation != generation:
                return False
            self._state = None
        await self._discard(state)
        self._observe("discarded", state.turn, reason=reason)
        return True

    async def stream(self, turn: TurnContent) -> AsyncIterator[str]:
        stale: _PrefetchState | None = None
        async with self._lock:
            state = self._state
            if state is None or not _same_turn(state.turn, turn) or state.invalidated:
                if state is not None:
                    self._state = None
                    stale = state
                state = None
        if state is None:
            self._observe("miss", turn, reason="candidate_mismatch" if stale else "not_prepared")
            if stale is not None:
                await self._discard(stale)
            async for delta in self._brain.stream(turn):
                if delta:
                    yield delta
            return

        self._observe(
            "hit",
            turn,
            buffered_characters=sum(map(len, state.chunks)),
            prefetch_lead_ms=(time.monotonic_ns() - state.started_ns) / 1_000_000,
            first_delta_ready=state.first_delta_ns is not None,
        )
        completed = False
        yielded_text = False
        try:
            async for delta in self._follow(state):
                yielded_text = True
                yield delta
            completed = True
        finally:
            async with self._lock:
                if self._state is state:
                    self._state = None
            if not completed:
                await self._discard(state)
        if not yielded_text and not state.invalidated:
            async for delta in self._brain.stream(turn):
                if delta:
                    yield delta

    async def _produce(self, state: _PrefetchState) -> None:
        try:
            async for delta in self._brain.stream(state.turn):
                if not delta:
                    continue
                async with state.condition:
                    if state.invalidated:
                        break
                    if state.first_delta_ns is None:
                        state.first_delta_ns = time.monotonic_ns()
                    state.chunks.append(delta)
                    state.condition.notify_all()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - replayed at the consumer boundary
            state.error = error
        finally:
            async with state.condition:
                state.done = True
                state.condition.notify_all()

    async def _follow(self, state: _PrefetchState) -> AsyncIterator[str]:
        index = 0
        while True:
            async with state.condition:
                while index >= len(state.chunks) and not state.done and not state.invalidated:
                    await state.condition.wait()
                if state.invalidated:
                    return
                available = tuple(state.chunks[index:])
                index = len(state.chunks)
                done = state.done
                error = state.error
            for chunk in available:
                if state.invalidated:
                    return
                yield chunk
            if done:
                if error is not None:
                    raise error
                return

    async def _discard(self, state: _PrefetchState) -> None:
        state.invalidated = True
        async with state.condition:
            state.condition.notify_all()
        task = state.task
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            done, pending = await asyncio.wait({task}, timeout=0.1)
            if done and not task.cancelled():
                task.exception()
            if pending:
                logger.warning("Speculative producer did not stop within cleanup budget")
                task.add_done_callback(
                    lambda finished: None if finished.cancelled() else finished.exception()
                )


def _same_turn(left: TurnContent, right: TurnContent) -> bool:
    return (
        left.generation == right.generation
        and same_asr_utterance(left.text, right.text)
        and left.conversation_context == right.conversation_context
        and left.input_relation_unresolved == right.input_relation_unresolved
        and left.vision_text == right.vision_text
        and left.audio == right.audio
        and left.voiceprint == right.voiceprint
    )
