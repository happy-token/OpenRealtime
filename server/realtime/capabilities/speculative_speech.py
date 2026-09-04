"""Commit-gated speculative Brain and duplex TTS pipeline.

The Turn Manager may begin this pipeline for an endpoint candidate. Provider
text and audio are buffered, never emitted to the client, until the committed
response consumes the matching turn. ASR revisions invalidate the whole
pipeline so stale speech cannot escape.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from server.core.turn_content import TurnContent, same_asr_utterance
from server.realtime.capabilities.brain_streaming import StreamingTextBrain
from server.speech.tts import DuplexStreamingTtsEngine, SynthesizedAudioChunk

_TEXT_END = object()


@dataclass(slots=True)
class _SpeculativeSpeechState:
    turn: TurnContent
    text_chunks: list[str] = field(default_factory=list)
    audio_chunks: list[SynthesizedAudioChunk] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None
    done: bool = False
    invalidated: bool = False
    error: Exception | None = None


class SpeculativeSpeechPipeline:
    """Share one speculative provider run across Brain and duplex TTS."""

    def __init__(
        self,
        *,
        brain: StreamingTextBrain,
        tts: DuplexStreamingTtsEngine,
    ) -> None:
        self._brain = brain
        self._tts = tts
        self._state: _SpeculativeSpeechState | None = None
        self._lock = asyncio.Lock()

    async def prepare(self, turn: TurnContent) -> bool:
        async with self._lock:
            current = self._state
            if current is not None and _same_turn(current.turn, turn) and not current.invalidated:
                return False
            state = _SpeculativeSpeechState(turn=turn)
            state.task = asyncio.create_task(
                self._produce(state),
                name=f"speculative-speech-{turn.generation}",
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
        state = await self._matching_state(turn)
        if state is None:
            async for delta in self._brain.stream(turn):
                if delta:
                    yield delta
            return
        completed = False
        try:
            index = 0
            while True:
                async with state.condition:
                    while index >= len(state.text_chunks) and not state.done:
                        await state.condition.wait()
                    available = tuple(state.text_chunks[index:])
                    index = len(state.text_chunks)
                    done = state.done
                    error = state.error
                for delta in available:
                    yield delta
                if done:
                    if error is not None:
                        raise error
                    completed = True
                    return
        finally:
            if not completed:
                await self._remove_and_discard(state)

    async def synthesize_duplex(
        self,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        async with self._lock:
            state = self._state
        if state is None or state.invalidated:
            async for chunk in self._tts.synthesize_duplex(text_stream):
                yield chunk
            return

        committed_text: list[str] = []

        async def drain_committed_text() -> None:
            async for delta in text_stream:
                if delta:
                    committed_text.append(delta)

        drain_task = asyncio.create_task(
            drain_committed_text(),
            name=f"speculative-speech-text-{state.turn.generation}",
        )
        completed = False
        try:
            index = 0
            while True:
                async with state.condition:
                    while index >= len(state.audio_chunks) and not state.done:
                        await state.condition.wait()
                    available = tuple(state.audio_chunks[index:])
                    index = len(state.audio_chunks)
                    done = state.done
                    error = state.error
                for chunk in available:
                    yield chunk
                if done:
                    if error is not None:
                        raise error
                    await drain_task
                    expected_text = "".join(state.text_chunks)
                    if "".join(committed_text) != expected_text:
                        raise RuntimeError("committed TTS text diverged from speculative text")
                    completed = True
                    return
        finally:
            if not drain_task.done():
                drain_task.cancel()
            await asyncio.gather(drain_task, return_exceptions=True)
            if completed:
                async with self._lock:
                    if self._state is state:
                        self._state = None
            else:
                await self._remove_and_discard(state)

    async def warmup(self) -> None:
        warmup = getattr(self._tts, "warmup", None)
        if warmup is not None:
            await warmup()

    async def close(self) -> None:
        async with self._lock:
            state, self._state = self._state, None
        if state is not None:
            await self._discard(state)
        close = getattr(self._tts, "close", None)
        if close is not None:
            await close()

    async def _matching_state(
        self,
        turn: TurnContent,
    ) -> _SpeculativeSpeechState | None:
        stale: _SpeculativeSpeechState | None = None
        async with self._lock:
            state = self._state
            if state is None or state.invalidated or not _same_turn(state.turn, turn):
                if state is not None:
                    self._state = None
                    stale = state
                state = None
        if stale is not None:
            await self._discard(stale)
        return state

    async def _produce(self, state: _SpeculativeSpeechState) -> None:
        text_queue: asyncio.Queue[str | object] = asyncio.Queue(maxsize=64)

        async def speculative_text() -> AsyncIterator[str]:
            while True:
                item = await text_queue.get()
                if item is _TEXT_END:
                    return
                assert isinstance(item, str)
                yield item

        async def produce_audio() -> None:
            async for chunk in self._tts.synthesize_duplex(speculative_text()):
                async with state.condition:
                    state.audio_chunks.append(chunk)
                    state.condition.notify_all()

        audio_task = asyncio.create_task(
            produce_audio(),
            name=f"speculative-speech-audio-{state.turn.generation}",
        )
        try:
            produced_text = False
            for _ in range(2):
                async for delta in self._brain.stream(state.turn):
                    if not delta:
                        continue
                    produced_text = True
                    async with state.condition:
                        state.text_chunks.append(delta)
                        state.condition.notify_all()
                    await text_queue.put(delta)
                if produced_text:
                    break
            await text_queue.put(_TEXT_END)
            await audio_task
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - replayed at consumer boundary
            state.error = error
        finally:
            if not audio_task.done():
                audio_task.cancel()
            await asyncio.gather(audio_task, return_exceptions=True)
            async with state.condition:
                state.done = True
                state.condition.notify_all()

    async def _remove_and_discard(self, state: _SpeculativeSpeechState) -> None:
        async with self._lock:
            if self._state is state:
                self._state = None
        await self._discard(state)

    async def _discard(self, state: _SpeculativeSpeechState) -> None:
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
