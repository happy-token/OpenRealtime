"""Commit-gated, bounded Brain and duplex TTS pre-generation.

Only uncommitted candidates may fall back to a fresh provider run. Once claimed,
consumers drain the same producer with backpressure. Brain and TTS share one
lease, so a changed candidate cannot accidentally supply an old response's PCM.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from server.core.async_stream import OwnedStreamCleanupError, owned_async_iterator
from server.core.turn_content import TurnContent, same_asr_utterance
from server.realtime.capabilities.brain_streaming import StreamingTextBrain
from server.realtime.capabilities.speculative_budget import (
    SpeculativeBudgetExceeded,
    SpeculativeBuffer,
    SpeculativeCleanupOwner,
    SpeculativeOutputBudget,
    SpeculativeState,
    candidate_queue_operation,
    detached_error,
    join_owned_tasks,
    text_cost,
)
from server.speech.tts import DuplexStreamingTtsEngine, SynthesizedAudioChunk

_TEXT_END = object()
logger = logging.getLogger(__name__)


class _TextFingerprint:
    def __init__(self) -> None:
        self._hash = hashlib.sha256()
        self.size = 0

    def update(self, text: str) -> None:
        data = text.encode("utf-8")
        self._hash.update(data)
        self.size += len(data)

    def matches(self, other: _TextFingerprint) -> bool:
        return self.size == other.size and self._hash.digest() == other._hash.digest()


@dataclass(slots=True, kw_only=True)
class _SpeculativeSpeechState(SpeculativeState):
    turn: TurnContent
    text_chunks: SpeculativeBuffer[str] = field(init=False)
    audio_chunks: SpeculativeBuffer[SynthesizedAudioChunk] = field(init=False)
    expected_text: _TextFingerprint = field(default_factory=_TextFingerprint)
    text_active: bool = False
    text_finished: bool = False
    text_done: bool = False
    audio_active: bool = False
    prefetched: bool = True


class SpeculativeSpeechPipeline:
    """One cache lease and one owned Brain/TTS producer pair per instance."""

    def __init__(self, *, brain: StreamingTextBrain, tts: DuplexStreamingTtsEngine,
                 budget: SpeculativeOutputBudget | None = None,
                 observer: Callable[[str, TurnContent, dict[str, Any]], None] | None = None) -> None:
        self._brain = brain
        self._tts = tts
        self._budget = budget or SpeculativeOutputBudget()
        self._observer = observer
        self._state: _SpeculativeSpeechState | None = None
        self._lease: _SpeculativeSpeechState | None = None
        self._direct_text_active = False
        self._direct_audio_active = False
        self._lock = asyncio.Lock()
        self._cleanup = SpeculativeCleanupOwner()
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._idle = asyncio.Event()
        self._idle.set()

    def _observe(self, operation: str, turn: TurnContent, **attributes: Any) -> None:
        if self._observer is not None:
            try:
                self._observer(operation, turn, attributes)
            except Exception:
                logger.warning("Response prefetch observer failed", exc_info=True)

    async def prepare(self, turn: TurnContent) -> bool:
        async with self._lock:
            if self._closed:
                raise RuntimeError("speculative speech pipeline is closed")
            await self._cleanup.admit()
            if self._lease is not None or self._direct_text_active or self._direct_audio_active:
                return False
            current = self._state
            if current is not None and _same_turn(current.turn, turn) and not current.invalidated:
                return False
            if current is not None:
                self._state = None
                await self._discard(current, require_confirmation=False)
                await self._cleanup.admit()
            if self._closed:
                raise RuntimeError("speculative speech pipeline is closed")
            state = _SpeculativeSpeechState(turn=turn)
            state.text_chunks = SpeculativeBuffer(
                state=state, byte_limit=self._budget.text_bytes,
                chunk_limit=self._budget.text_chunks,
                measure=lambda text: text_cost(text, self._budget.text_bytes))
            state.audio_chunks = SpeculativeBuffer(
                state=state, byte_limit=self._budget.audio_bytes,
                chunk_limit=self._budget.audio_chunks,
                seconds_limit=self._budget.audio_seconds, measure=self._audio_cost)
            state.task = asyncio.create_task(self._produce(state),
                                             name=f"speculative-speech-{turn.generation}")
            self._state = state
            state.expiry_handle = asyncio.get_running_loop().call_later(
                self._budget.candidate_seconds, self._expire, state)
        return True

    def _expire(self, state: _SpeculativeSpeechState) -> None:
        if state.claimed or state.invalidated:
            return
        if state.error is None:
            state.error = SpeculativeBudgetExceeded("candidate_residency")
        state.text_chunks.clear()
        state.audio_chunks.clear()
        state.retired.set()
        state.expiry_handle = None
        self._observe("budget_exceeded", state.turn, reason="candidate_residency")

    def _audio_cost(self, chunk: SynthesizedAudioChunk) -> tuple[int, float]:
        if chunk.sample_rate_hz <= 0:
            raise ValueError("speculative audio requires a positive sample rate")
        metadata = sum(text_cost(text, self._budget.text_bytes)[0]
                       for text in (chunk.spoken_text, chunk.sentence_text) if text)
        return len(chunk.pcm16) + metadata, len(chunk.pcm16) / (2 * chunk.sample_rate_hz)

    async def invalidate(self, generation: int, *, reason: str) -> bool:
        async with self._lock:
            state = self._state or self._lease
            if state is None or state.turn.generation != generation:
                return False
            self._state = None
        await self._discard(state, require_confirmation=state.claimed)
        self._observe("discarded", state.turn, reason=reason)
        return True

    async def stream(self, turn: TurnContent) -> AsyncIterator[str]:
        async with self._lock:
            if self._closed:
                raise RuntimeError("speculative speech pipeline is closed")
            if self._lease is not None or self._direct_text_active:
                raise RuntimeError("speculative text consumer is already bound")
            await self._cleanup.admit()
            state = self._state
            reason = "not_prepared"
            if state is not None:
                if not _same_turn(state.turn, turn) or state.invalidated:
                    reason = "candidate_mismatch"
                elif state.claim(self._budget):
                    reason = "hit"
                else:
                    reason = "budget_bypass"
                if reason != "hit":
                    self._state = None
                    await self._discard(state)
                    state = None
            if self._closed:
                raise RuntimeError("speculative speech pipeline is closed")
            active = state or _SpeculativeSpeechState(turn=turn, prefetched=False)
            active.text_active = True
            self._lease = active
            self._idle.clear()
            if state is None:
                self._direct_text_active = True
        completed = False
        yielded_text = False
        try:
            self._observe("hit" if state is not None else "miss", turn, reason=reason)
            if state is None:
                async with owned_async_iterator(self._brain.stream(turn)) as iterator:
                    async for delta in iterator:
                        if delta:
                            yielded_text = True
                            yield delta
                completed = not active.invalidated
                return
            async for delta in self._follow(state, state.text_chunks):
                yielded_text = True
                yield delta
            completed = not state.invalidated
        except Exception as error:
            current = asyncio.current_task()
            if isinstance(error, OwnedStreamCleanupError) or (current is not None and current.cancelling()):
                self._cleanup.record_failure(error)
            raise
        finally:
            self._direct_text_active = False
            active.text_active = False
            active.text_finished = completed
            if not completed or (not yielded_text and not active.audio_active):
                if state is not None:
                    await self._remove_and_discard(state)
                elif self._lease is active and not active.audio_active:
                    self._lease = None
                    self._idle.set()

    async def synthesize_duplex(self, text_stream: AsyncIterator[str]) -> AsyncIterator[SynthesizedAudioChunk]:
        # Priming the actual committed stream establishes its lease before audio
        # selection, including when stream() has not yet been iterated by Core.
        async with owned_async_iterator(text_stream) as texts:
            first = await anext(texts, None)
            async with self._lock:
                if self._closed:
                    raise RuntimeError("speculative speech pipeline is closed")
                if self._direct_audio_active or (self._lease is not None and self._lease.audio_active):
                    raise RuntimeError("speculative audio consumer is already bound")
                await self._cleanup.admit()
                if self._closed:
                    raise RuntimeError("speculative speech pipeline is closed")
                state = self._lease
                if state is not None and state.invalidated:
                    return
                if state is None or not state.prefetched:
                    self._direct_audio_active = True
                    self._idle.clear()
                if state is not None:
                    state.audio_active = True

            async def prefixed_text() -> AsyncIterator[str]:
                if first is not None:
                    yield first
                async for text in texts:
                    yield text

            if state is None or not state.prefetched:
                try:
                    async with owned_async_iterator(self._tts.synthesize_duplex(prefixed_text())) as audio:
                        async for chunk in audio:
                            yield chunk
                except Exception as error:
                    current = asyncio.current_task()
                    if isinstance(error, OwnedStreamCleanupError) or (current is not None and current.cancelling()):
                        self._cleanup.record_failure(error)
                    raise
                finally:
                    self._direct_audio_active = False
                    if state is not None:
                        state.audio_active = False
                        if self._lease is state:
                            self._lease = None
                    if self._lease is None and not self._direct_text_active:
                        self._idle.set()
                return

            committed = _TextFingerprint()

            async def drain() -> None:
                async for text in prefixed_text():
                    committed.update(text)

            drain_task = asyncio.create_task(drain(), name=f"speculative-speech-text-{state.turn.generation}")
            completed = False
            try:
                async for chunk in self._follow(state, state.audio_chunks):
                    yield chunk
                if state.invalidated:
                    return
                await drain_task
                if not committed.matches(state.expected_text):
                    raise RuntimeError("committed TTS text diverged from speculative text")
                completed = True
            finally:
                if not drain_task.done() and not drain_task.cancelling():
                    drain_task.cancel()
                results = await asyncio.shield(asyncio.gather(drain_task, return_exceptions=True))
                for result in results:
                    if isinstance(result, OwnedStreamCleanupError):
                        state.cleanup_error = detached_error(result)
                state.audio_active = False
                if not completed:
                    await self._remove_and_discard(state)
                else:
                    async with self._lock:
                        if self._state is state:
                            self._state = None
                        if self._lease is state:
                            self._lease = None
                            self._idle.set()

    async def _follow[T](self, state: _SpeculativeSpeechState, buffer: SpeculativeBuffer[T]) -> AsyncIterator[T]:
        while True:
            async with state.condition:
                while not buffer and not (state.text_done if buffer is state.text_chunks else state.done) and not state.invalidated:
                    await state.condition.wait()
                if state.invalidated:
                    return
                if buffer:
                    chunk = buffer.pop()
                else:
                    if state.error is not None:
                        raise state.error
                    return
            yield chunk

    async def _produce(self, state: _SpeculativeSpeechState) -> None:
        # At most one admitted text delta plus one in-flight provider delta.
        text_queue: asyncio.Queue[str | object] = asyncio.Queue(maxsize=1)

        async def speculative_text() -> AsyncIterator[str]:
            while True:
                item = await candidate_queue_operation(text_queue.get, state)
                if item is None or item is _TEXT_END:
                    return
                assert isinstance(item, str)
                yield item

        def record_child_error(error: Exception) -> None:
            current = asyncio.current_task()
            if isinstance(error, OwnedStreamCleanupError) or (current is not None and current.cancelling()):
                state.cleanup_error = error
            if state.error is None:
                state.error = detached_error(error)

        closing_children: set[asyncio.Task[None]] = set()

        def mark_closing() -> None:
            task = asyncio.current_task()
            assert task is not None
            closing_children.add(task)

        async def produce_audio() -> None:
            try:
                async with owned_async_iterator(self._tts.synthesize_duplex(speculative_text())) as audio:
                    try:
                        async for chunk in audio:
                            if not await state.audio_chunks.append(chunk):
                                return
                    finally:
                        mark_closing()
            except Exception as error:
                record_child_error(error)
                raise

        async def produce_text() -> None:
            try:
                produced_text = False
                for _ in range(2):
                    async with owned_async_iterator(self._brain.stream(state.turn)) as texts:
                        try:
                            async for delta in texts:
                                if state.retired.is_set():
                                    return
                                if not delta:
                                    continue
                                if not await state.text_chunks.append(delta):
                                    return
                                state.expected_text.update(delta)
                                produced_text = True
                                await candidate_queue_operation(partial(text_queue.put, delta), state)
                                if state.retired.is_set():
                                    return
                        finally:
                            mark_closing()
                    task = asyncio.current_task()
                    assert task is not None
                    closing_children.discard(task)
                    if produced_text:
                        break
                await candidate_queue_operation(lambda: text_queue.put(_TEXT_END), state)
            except Exception as error:
                record_child_error(error)
                raise
            finally:
                async with state.condition:
                    state.text_done = True
                    state.condition.notify_all()

        tasks: set[asyncio.Task[None]] = set()
        try:
            if state.retired.is_set():
                return
            tasks = {asyncio.create_task(produce_audio(), name=f"speculative-speech-audio-{state.turn.generation}"),
                     asyncio.create_task(produce_text(), name=f"speculative-speech-brain-{state.turn.generation}")}
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for task in done:
                task.result()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - replayed at consumer boundary
            state.error = detached_error(error)
            if isinstance(error, OwnedStreamCleanupError):
                state.cleanup_error = detached_error(error)
        finally:
            state.cleanup_started = True
            state.retired.set()
            for task in tasks:
                if state.claimed and not task.done() and not task.cancelling() and task not in closing_children:
                    task.cancel()
            results = await join_owned_tasks(tasks)
            for result in results:
                if isinstance(result, Exception):
                    if isinstance(result, OwnedStreamCleanupError):
                        state.cleanup_error = detached_error(result)
                    if state.error is None:
                        state.error = detached_error(result)
            if state.error is not None:
                state.error = detached_error(state.error)
            if state.cleanup_error is not None:
                state.cleanup_error = detached_error(state.cleanup_error)
            async with state.condition:
                state.done = True
                state.condition.notify_all()
            if isinstance(state.error, SpeculativeBudgetExceeded) and not state.claimed:
                state.text_chunks.clear()
                state.audio_chunks.clear()
                self._observe("budget_exceeded", state.turn, reason=str(state.error))

    async def _remove_and_discard(self, state: _SpeculativeSpeechState) -> None:
        async with self._lock:
            if self._state is state:
                self._state = None
        await self._discard(state)

    async def _discard(self, state: _SpeculativeSpeechState, *, require_confirmation: bool = True) -> None:
        state.invalidated = True
        if state.prefetched:
            state.text_chunks.clear()
            state.audio_chunks.clear()
        try:
            await self._cleanup.discard(state, confirmed=require_confirmation)
        finally:
            released = state.task is None or state.task.done()
            if released and state.cleanup_error is None and not state.text_active and not state.audio_active and self._lease is state:
                self._lease = None
                self._idle.set()

    async def warmup(self) -> None:
        warmup = getattr(self._tts, "warmup", None)
        if warmup is not None:
            await warmup()

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_owned(), name="speculative-speech-close")
            self._close_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        await asyncio.shield(self._close_task)

    async def _close_owned(self) -> None:
        async with self._lock:
            state, self._state = self._state or self._lease, None
        if state is not None:
            await self._discard(state)
        await self._cleanup.close()
        await self._idle.wait()
        close = getattr(self._tts, "close", None)
        if close is not None:
            await close()


def _same_turn(left: TurnContent, right: TurnContent) -> bool:
    return (
        left.generation == right.generation
        and same_asr_utterance(left.text, right.text)
        and left.conversation_context == right.conversation_context
        and left.context_projection_digest == right.context_projection_digest
        and left.input_relation_unresolved == right.input_relation_unresolved
        and left.context_repair == right.context_repair
        and left.vision_text == right.vision_text
        and left.audio == right.audio
        and left.voiceprint == right.voiceprint
    )
