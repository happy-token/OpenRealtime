"""Typed TTS capability with duplex and commit-only legacy adapters."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, cast

from server.core.async_stream import OwnedStreamCleanupError, owned_async_iterator
from server.core.interaction_context import InteractionContext
from server.observability.telemetry import SessionTelemetry
from server.realtime.protocol.audio import AudioEncoding, AudioFrame
from server.realtime.protocol.playback import SentenceSpan, sentence_identity
from server.speech.tts import DuplexStreamingTtsEngine, StreamingTtsEngine

_TEXT_END = object()
_CLOSED = object()
logger = logging.getLogger(__name__)


class TtsTextMode(StrEnum):
    DUPLEX = "duplex"
    COMMIT_ONLY = "commit_only"


@dataclass(frozen=True, slots=True, kw_only=True)
class StartTts:
    speech_id: str
    context: InteractionContext | None = None

    def __post_init__(self) -> None:
        if not self.speech_id:
            raise ValueError("TTS speech identity must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendTtsText:
    speech_id: str
    text_sequence: int
    delta: str

    def __post_init__(self) -> None:
        if not self.speech_id or self.text_sequence < 1 or not self.delta:
            raise ValueError("TTS text must be non-empty and positively sequenced")


@dataclass(frozen=True, slots=True, kw_only=True)
class CommitTts:
    speech_id: str

    def __post_init__(self) -> None:
        if not self.speech_id:
            raise ValueError("TTS speech identity must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelTts:
    speech_id: str
    reason: str

    def __post_init__(self) -> None:
        if not self.speech_id or not self.reason:
            raise ValueError("TTS cancellation identity and reason must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class TtsAudioFrame:
    context: InteractionContext
    speech_id: str
    frame: AudioFrame
    is_final_for_segment: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TtsTextAlignment:
    context: InteractionContext
    speech_id: str
    audio_end_us: int
    text_end: int
    audio_start_us: int | None = None
    text_end_precision: Literal["exact", "estimated"] = "exact"
    sentence: SentenceSpan | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TtsCompleted:
    context: InteractionContext
    speech_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TtsCancelled:
    context: InteractionContext
    speech_id: str
    reason: str
    cleanup_timed_out: bool = False

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("TTS cancellation reason must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class TtsFailed:
    context: InteractionContext
    speech_id: str
    error: str
    cleanup_failed: bool = False

    def __post_init__(self) -> None:
        if not self.error:
            raise ValueError("TTS failure must carry an error")


TtsCommand = StartTts | AppendTtsText | CommitTts | CancelTts
TtsEvent = TtsTextAlignment | TtsAudioFrame | TtsCompleted | TtsCancelled | TtsFailed


class TtsCapabilitySession(Protocol):
    @property
    def text_mode(self) -> TtsTextMode: ...

    async def send(self, command: TtsCommand) -> None: ...

    def events(self) -> AsyncIterator[TtsEvent]: ...

    async def close(self) -> None: ...


class TtsCapabilityProvider(Protocol):
    async def open(self, *, context: InteractionContext) -> TtsCapabilitySession: ...


class LegacyTtsCapabilityAdapter:
    def __init__(
        self,
        engine: StreamingTtsEngine | DuplexStreamingTtsEngine,
        *,
        cancel_timeout_s: float = 0.3,
        telemetry: SessionTelemetry | None = None,
    ) -> None:
        if cancel_timeout_s <= 0:
            raise ValueError("cancel_timeout_s must be positive")
        self._engine = engine
        self._telemetry = telemetry
        self._cancel_timeout_s = cancel_timeout_s

    async def open(self, *, context: InteractionContext) -> LegacyTtsCapabilitySession:
        warmup = getattr(self._engine, "warmup", None)
        warmup_task = (
            asyncio.create_task(
                _warm_tts_engine(warmup, self._telemetry, context),
                name=f"tts-warmup-{context.voice_session_id}",
            )
            if warmup is not None
            else None
        )
        return LegacyTtsCapabilitySession(
            context=context,
            engine=self._engine,
            cancel_timeout_s=self._cancel_timeout_s,
            warmup_task=warmup_task,
        )


class LegacyTtsCapabilitySession:
    def __init__(
        self,
        *,
        context: InteractionContext,
        engine: StreamingTtsEngine | DuplexStreamingTtsEngine,
        cancel_timeout_s: float,
        warmup_task: asyncio.Task[None] | None = None,
    ) -> None:
        self._context = context
        self._engine = engine
        self._cancel_timeout_s = cancel_timeout_s
        self._warmup_task = warmup_task
        self._duplex_synthesize = getattr(engine, "synthesize_duplex", None)
        self._events: asyncio.Queue[TtsEvent | object] = asyncio.Queue(maxsize=64)
        self._text_queue: asyncio.Queue[str | object] = asyncio.Queue(maxsize=16)
        self._speech_id: str | None = None
        self._speech_context = context
        self._next_text_sequence = 1
        self._text_parts: list[str] = []
        self._task: asyncio.Task[None] | None = None
        self._detached_tasks: set[asyncio.Task[None]] = set()
        self._committed = False
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._cleanup_error: Exception | None = None

    @property
    def text_mode(self) -> TtsTextMode:
        return (
            TtsTextMode.DUPLEX if self._duplex_synthesize is not None else TtsTextMode.COMMIT_ONLY
        )

    async def send(self, command: TtsCommand) -> None:
        if self._closed:
            raise RuntimeError("TTS capability session is closed")
        if isinstance(command, StartTts):
            self._start(command)
            return
        self._validate_active(command.speech_id)
        if isinstance(command, AppendTtsText):
            if self._committed:
                raise ValueError("TTS text input is already committed")
            if command.text_sequence != self._next_text_sequence:
                raise ValueError(
                    f"expected TTS text sequence {self._next_text_sequence}, "
                    f"received {command.text_sequence}"
                )
            self._next_text_sequence += 1
            self._text_parts.append(command.delta)
            if self.text_mode is TtsTextMode.DUPLEX:
                await self._text_queue.put(command.delta)
            return
        if isinstance(command, CommitTts):
            if self._committed:
                raise ValueError("TTS text input is already committed")
            if not self._text_parts:
                raise ValueError("cannot commit TTS without text")
            self._committed = True
            if self.text_mode is TtsTextMode.DUPLEX:
                await self._text_queue.put(_TEXT_END)
            else:
                self._task = asyncio.create_task(
                    self._run_commit_only(command.speech_id, "".join(self._text_parts)),
                    name=f"tts-capability-{command.speech_id}",
                )
            return
        if isinstance(command, CancelTts):
            self._committed = True
            speech_context = self._speech_context
            cleanup_timed_out = False
            if self._task is not None and not self._task.done():
                cleanup_timed_out = await self._cancel_task_bounded(
                    self._task,
                    speech_id=command.speech_id,
                )
            await self._events.put(
                TtsCancelled(
                    context=speech_context,
                    speech_id=command.speech_id,
                    reason=command.reason,
                    cleanup_timed_out=cleanup_timed_out,
                )
            )
            self._reset_after(command.speech_id)
            return
        raise TypeError(f"unsupported TTS capability command: {type(command).__name__}")

    async def _cancel_task_bounded(
        self,
        task: asyncio.Task[None],
        *,
        speech_id: str,
    ) -> bool:
        if not task.cancelling():
            task.cancel()
        done, pending = await asyncio.wait({task}, timeout=self._cancel_timeout_s)
        if done:
            await asyncio.shield(asyncio.gather(*done, return_exceptions=True))
            if self._cleanup_error is not None:
                raise OwnedStreamCleanupError(f"TTS provider cleanup failed: {self._cleanup_error}") from self._cleanup_error
            return False
        logger.warning(
            "TTS cancellation exceeded %.0fms for speech %s; detaching provider cleanup",
            self._cancel_timeout_s * 1000,
            speech_id,
        )
        self._detached_tasks.update(pending)
        for detached in pending:
            detached.add_done_callback(self._observe_detached_task)
        return True

    def _observe_detached_task(self, task: asyncio.Task[None]) -> None:
        self._detached_tasks.discard(task)
        try:
            task.exception()
        except asyncio.CancelledError:
            pass

    def _start(self, command: StartTts) -> None:
        if self._cleanup_error is not None:
            raise RuntimeError("TTS provider cleanup was not confirmed; requires a new capability session")
        if self._speech_id is not None:
            raise ValueError("TTS capability already has an active speech")
        self._speech_id = command.speech_id
        self._speech_context = command.context or self._context
        if self.text_mode is TtsTextMode.DUPLEX:
            self._task = asyncio.create_task(
                self._run_duplex(command.speech_id),
                name=f"tts-capability-{command.speech_id}",
            )

    def _validate_active(self, speech_id: str) -> None:
        if self._speech_id != speech_id:
            raise ValueError("TTS command does not match the active speech")

    async def _text_stream(self) -> AsyncIterator[str]:
        while True:
            item = await self._text_queue.get()
            if item is _TEXT_END:
                return
            assert isinstance(item, str)
            yield item

    async def _run_duplex(self, speech_id: str) -> None:
        assert self._duplex_synthesize is not None
        try:
            await self._await_warmup()
            await self._emit_audio(speech_id, self._duplex_synthesize(self._text_stream()))
            await self._events.put(
                TtsCompleted(context=self._speech_context, speech_id=speech_id)
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - provider failures become typed events
            cleanup_failed = self._record_cleanup_failure(error)
            if self._closed:
                return
            await self._events.put(
                TtsFailed(context=self._speech_context, speech_id=speech_id, error=str(error),
                          cleanup_failed=cleanup_failed)
            )
        finally:
            self._reset_after(speech_id)

    async def _run_commit_only(self, speech_id: str, text: str) -> None:
        synthesize = getattr(self._engine, "synthesize_stream", None)
        if synthesize is None:
            await self._events.put(
                TtsFailed(
                    context=self._speech_context,
                    speech_id=speech_id,
                    error="TTS engine exposes neither duplex nor streaming synthesis",
                )
            )
            self._reset_after(speech_id)
            return
        try:
            await self._await_warmup()
            await self._emit_audio(speech_id, synthesize(text))
            await self._events.put(
                TtsCompleted(context=self._speech_context, speech_id=speech_id)
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - provider failures become typed events
            cleanup_failed = self._record_cleanup_failure(error)
            if self._closed:
                return
            await self._events.put(
                TtsFailed(context=self._speech_context, speech_id=speech_id, error=str(error),
                          cleanup_failed=cleanup_failed)
            )
        finally:
            self._reset_after(speech_id)

    def _record_cleanup_failure(self, error: Exception) -> bool:
        current = asyncio.current_task()
        if isinstance(error, OwnedStreamCleanupError) or (current is not None and current.cancelling()):
            self._cleanup_error = error
            return True
        return False

    def _reset_after(self, speech_id: str) -> None:
        if self._speech_id != speech_id:
            return
        self._speech_id = None
        self._speech_context = self._context
        self._next_text_sequence = 1
        self._text_parts.clear()
        self._text_queue = asyncio.Queue(maxsize=16)
        self._committed = False
        if self._task is asyncio.current_task():
            self._task = None

    async def _emit_audio(self, speech_id: str, chunks) -> None:
        sequence = 0
        timestamp_us = 0
        aligned_text_end = 0
        seen_timings: set[tuple[str, int, int, str | None, int | None, int | None, str | None]] = set()
        sentence_anchor: tuple[tuple[str, int], int] | None = None
        async with owned_async_iterator(chunks) as iterator:
            async for chunk in iterator:
                aligned = None
                sentence = None
                precision: Literal["exact", "estimated"] = "estimated"
                has_timing = chunk.spoken_start_us is not None and chunk.spoken_end_us is not None
                duplicate = False
                if has_timing and chunk.spoken_text:
                    assert chunk.spoken_start_us is not None and chunk.spoken_end_us is not None
                    # A repeated word can carry newly complete sentence evidence.
                    timing = (chunk.spoken_text, chunk.spoken_start_us, chunk.spoken_end_us,
                              chunk.sentence_text, chunk.sentence_start_us,
                              chunk.sentence_duration_us, chunk.sentence_timebase)
                    duplicate = timing in seen_timings
                    seen_timings.add(timing)
                if chunk.spoken_text and not duplicate:
                    accepted = "".join(self._text_parts)
                    if (has_timing and chunk.sentence_text and chunk.sentence_duration_us is not None
                            and chunk.sentence_duration_us > 0):
                        # Provider word positions are on the entire session clock.
                        # The numerator must subtract this sentence's origin.
                        audio_start = chunk.sentence_start_us or 0
                        # A later complete subtitle may upgrade an estimated duration.
                        # Keep its original-text offset; the caption cursor is not evidence.
                        anchor_key = (chunk.sentence_text, audio_start)
                        if sentence_anchor is None or sentence_anchor[0] != anchor_key:
                            found = accepted.find(chunk.sentence_text, aligned_text_end)
                            sentence_anchor = (anchor_key, found) if found >= 0 else None
                        if sentence_anchor is not None:
                            _, text_start = sentence_anchor
                            assert chunk.spoken_end_us is not None
                            ratio = max(0.0, min(1.0, (chunk.spoken_end_us - audio_start) / chunk.sentence_duration_us))
                            candidate = text_start + round(ratio * len(chunk.sentence_text))
                            if chunk.sentence_timebase == "speech" and chunk.sentence_start_us is not None:
                                sentence = SentenceSpan(
                                    sentence_id=sentence_identity(self._speech_context, speech_id, chunk.sentence_text, text_start),
                                    text=chunk.sentence_text, text_start=text_start,
                                    text_end=text_start + len(chunk.sentence_text), audio_start_us=audio_start,
                                    audio_end_us=audio_start + chunk.sentence_duration_us)
                                if chunk.spoken_end_us >= sentence.audio_end_us:
                                    precision = "exact"
                            if candidate > aligned_text_end or precision == "exact" and candidate == aligned_text_end:
                                aligned = candidate
                    elif accepted[aligned_text_end:].startswith(chunk.spoken_text):
                        aligned = aligned_text_end + len(chunk.spoken_text)
                if aligned is not None:
                    aligned_text_end = aligned
                    await self._events.put(TtsTextAlignment(
                        context=self._speech_context, speech_id=speech_id,
                        audio_end_us=chunk.spoken_end_us if chunk.spoken_end_us is not None else timestamp_us,
                        audio_start_us=chunk.spoken_start_us, text_end=aligned,
                        text_end_precision=precision, sentence=sentence,
                    ))
                # Alignment duplicates can still carry new PCM; never drop audio
                # merely because a caption/timing tuple has already been seen.
                if not chunk.pcm16:
                    continue
                duration_us = max(
                    1,
                    round(len(chunk.pcm16) / 2 / chunk.sample_rate_hz * 1_000_000),
                )
                frame = AudioFrame(
                    stream_id=speech_id,
                    sequence=sequence,
                    timestamp_us=timestamp_us,
                    duration_us=duration_us,
                    encoding=AudioEncoding.PCM_S16LE,
                    sample_rate_hz=chunk.sample_rate_hz,
                    channels=1,
                    data=chunk.pcm16,
                )
                sequence += 1
                if chunk.pcm16:
                    timestamp_us += duration_us
                await self._events.put(
                    TtsAudioFrame(
                        context=self._speech_context,
                        speech_id=speech_id,
                        frame=frame,
                        is_final_for_segment=chunk.is_final,
                    )
                )

    async def events(self) -> AsyncIterator[TtsEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            yield cast(TtsEvent, event)

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_owners(), name="tts-capability-close")
            self._close_task.add_done_callback(self._observe_close)
        await asyncio.shield(self._close_task)

    @staticmethod
    def _observe_close(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _close_owners(self) -> None:
        tasks = set(self._detached_tasks)
        if self._task is not None:
            tasks.add(self._task)
        if self._warmup_task is not None:
            tasks.add(self._warmup_task)
        while not self._events.empty():
            self._events.get_nowait()
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
        self._detached_tasks.clear()
        close = getattr(self._engine, "close", None)
        if close is not None:
            await close()
        while not self._events.empty():
            self._events.get_nowait()
        self._events.put_nowait(_CLOSED)
        if self._cleanup_error is not None:
            raise OwnedStreamCleanupError(f"TTS capability close did not confirm provider cleanup: {self._cleanup_error}") from self._cleanup_error

    async def _await_warmup(self) -> None:
        if self._warmup_task is None:
            return
        await self._warmup_task


async def _warm_tts_engine(warmup, telemetry: SessionTelemetry | None = None, context: InteractionContext | None = None) -> None:
    try:
        if telemetry is None:
            await warmup()
        else:
            async with telemetry.provider_call(provider="tts", operation="connection_setup", generation=context.generation if context else None, attributes={"mode": "preconnect"}):
                await warmup()
    except asyncio.CancelledError:
        raise
    except Exception:  # first synthesis remains authoritative
        logger.warning("TTS provider warmup failed; synthesis will retry", exc_info=True)
