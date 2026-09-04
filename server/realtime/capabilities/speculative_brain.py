"""Deduplicated speculative buffer around a ``StreamingBrain``.

``prepare`` starts one provider stream for a transcript revision before Turn
Policy commits it.  ``stream`` later replays buffered deltas and follows the
same live producer, so semantic endpoint latency overlaps model generation
without issuing a duplicate LLM request. A provider-final revision that only
adds terminal sentence punctuation reuses the same producer.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from server.core.turn_content import TurnContent, same_asr_utterance
from server.realtime.capabilities.brain_streaming import StreamingTextBrain


@dataclass(slots=True)
class _PrefetchState:
    turn: TurnContent
    chunks: list[str] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None
    done: bool = False
    invalidated: bool = False
    error: Exception | None = None


class SpeculativeStreamingBrain:
    """One active speculative LLM request per voice-session Brain instance."""

    def __init__(self, brain: StreamingTextBrain) -> None:
        self._brain = brain
        self._state: _PrefetchState | None = None
        self._lock = asyncio.Lock()

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
        del reason
        async with self._lock:
            state = self._state
            if state is None or state.turn.generation != generation:
                return False
            self._state = None
        await self._discard(state)
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
            if stale is not None:
                await self._discard(stale)
            async for delta in self._brain.stream(turn):
                if delta:
                    yield delta
            return

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
        if not yielded_text:
            async for delta in self._brain.stream(turn):
                if delta:
                    yield delta

    async def _produce(self, state: _PrefetchState) -> None:
        try:
            async for delta in self._brain.stream(state.turn):
                if not delta:
                    continue
                async with state.condition:
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
                while index >= len(state.chunks) and not state.done:
                    await state.condition.wait()
                available = tuple(state.chunks[index:])
                index = len(state.chunks)
                done = state.done
                error = state.error
            for chunk in available:
                yield chunk
            if done:
                if error is not None:
                    raise error
                return

    async def _discard(self, state: _PrefetchState) -> None:
        state.invalidated = True
        task = state.task
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)


def _same_turn(left: TurnContent, right: TurnContent) -> bool:
    return (
        left.generation == right.generation
        and same_asr_utterance(left.text, right.text)
        and left.conversation_context == right.conversation_context
    )
