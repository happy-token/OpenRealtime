"""Provider-neutral timing boundaries for one realtime input/output turn.

All timestamps are captured by the host using the same monotonic clock. The
bridge may report its own diagnostics, but cannot replace these measurements.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from server.core.interaction_context import InteractionContext
from server.observability.telemetry import SessionTelemetry, TelemetryKind
from server.realtime.capabilities.asr import (
    AppendAsrAudio,
    AsrCapabilitySession,
    AsrEvent,
    AsrTranscriptDelta,
    AsrTranscriptFinal,
    DiscardAsrInput,
)
from server.realtime.capabilities.tts import (
    AppendTtsText,
    CancelTts,
    TtsAudioFrame,
    TtsCancelled,
    TtsCapabilitySession,
    TtsCompleted,
    TtsEvent,
    TtsFailed,
    TtsTextMode,
)


@dataclass(frozen=True, slots=True)
class ProviderLatencyMetrics:
    asr_first_text_ms: float | None
    asr_final_tail_ms: float | None
    tts_first_audio_ms: float | None
    llm_first_text_ms: float | None
    asr_speech_to_first_text_ms: float | None = None


class ProviderLatencyTrace:
    """Measure the four PRD spans without inventing values for missing events."""

    def __init__(self) -> None:
        self._asr_speech_start: int | None = None
        self._asr_first_frame: int | None = None
        self._asr_last_frame: int | None = None
        self._asr_first_text: int | None = None
        self._asr_final: int | None = None
        self._tts_first_text: int | None = None
        self._tts_first_audio: int | None = None
        self._llm_request: int | None = None
        self._llm_first_text: int | None = None

    def asr_speech_started(self, *, at_ns: int | None = None) -> None:
        # The first detected onset is stable across pauses in the same input.
        if self._asr_speech_start is None and self._asr_first_text is None:
            self._asr_speech_start = _time(at_ns)

    def asr_audio_frame(self, *, at_ns: int | None = None) -> None:
        now = _time(at_ns)
        if self._asr_final is not None:
            raise ValueError("ASR turn has already produced final text")
        if self._asr_first_frame is None:
            self._asr_first_frame = now
        if self._asr_last_frame is None or now >= self._asr_last_frame:
            self._asr_last_frame = now
        else:
            raise ValueError("ASR audio frames must be observed in delivery order")

    def asr_partial_text(self, text: str, *, at_ns: int | None = None) -> None:
        if text.strip() and self._asr_first_text is None:
            self._asr_first_text = _time(at_ns)

    def asr_final_text(self, text: str, *, at_ns: int | None = None) -> None:
        if not text.strip():
            return
        now = _time(at_ns)
        if self._asr_first_text is None:
            self._asr_first_text = now
        if self._asr_final is None:
            self._asr_final = now

    def tts_text_chunk(self, text: str, *, at_ns: int | None = None) -> None:
        if text.strip() and self._tts_first_text is None:
            self._tts_first_text = _time(at_ns)

    def tts_audio_chunk(self, audio: bytes, *, at_ns: int | None = None) -> None:
        if audio and self._tts_first_audio is None:
            self._tts_first_audio = _time(at_ns)

    def llm_request(self, *, at_ns: int | None = None) -> None:
        if self._llm_request is None:
            self._llm_request = _time(at_ns)

    def llm_text_chunk(self, text: str, *, at_ns: int | None = None) -> None:
        if text.strip() and self._llm_first_text is None:
            self._llm_first_text = _time(at_ns)

    def snapshot(self) -> ProviderLatencyMetrics:
        return ProviderLatencyMetrics(
            asr_speech_to_first_text_ms=_span(self._asr_speech_start, self._asr_first_text),
            asr_first_text_ms=_span(self._asr_first_frame, self._asr_first_text),
            asr_final_tail_ms=_span(self._asr_last_frame, self._asr_final),
            tts_first_audio_ms=_span(self._tts_first_text, self._tts_first_audio),
            llm_first_text_ms=_span(self._llm_request, self._llm_first_text),
        )


def _time(at_ns: int | None) -> int:
    value = time.monotonic_ns() if at_ns is None else at_ns
    if value < 0:
        raise ValueError("monotonic timestamp must be non-negative")
    return value


def _span(start: int | None, end: int | None) -> float | None:
    return (end - start) / 1_000_000 if start is not None and end is not None and end >= start else None


class ProviderLatencyObserver:
    """Emit host-timed capability spans without logging content or credentials."""

    def __init__(self, telemetry: SessionTelemetry, *, instances: dict[str, str] | None = None,
                 versions: dict[str, str] | None = None) -> None:
        self._telemetry = telemetry
        self._instances = instances or {}
        self._versions = versions or {}
        self._asr: dict[tuple[str, int], ProviderLatencyTrace] = {}
        self._tts: dict[tuple[str, str], ProviderLatencyTrace] = {}

    def asr_speech_started(self, context: InteractionContext) -> None:
        self._asr.setdefault(self._asr_key(context), ProviderLatencyTrace()).asr_speech_started()

    def asr_frame(self, context: InteractionContext) -> None:
        self._asr.setdefault(self._asr_key(context), ProviderLatencyTrace()).asr_audio_frame()

    def asr_partial(self, context: InteractionContext, text: str) -> None:
        trace = self._asr.get(self._asr_key(context))
        if trace is None:
            return
        before = trace.snapshot().asr_first_text_ms
        trace.asr_partial_text(text)
        if before is None:
            self._record("asr.input_to_first_text", context, trace.snapshot().asr_first_text_ms)
            self._record("asr.speech_start_to_first_text", context, trace.snapshot().asr_speech_to_first_text_ms)

    def asr_final(self, context: InteractionContext, text: str) -> None:
        trace = self._asr.pop(self._asr_key(context), None)
        if trace is None:
            return
        before = trace.snapshot().asr_first_text_ms
        trace.asr_final_text(text)
        metrics = trace.snapshot()
        if before is None:
            self._record("asr.input_to_first_text", context, metrics.asr_first_text_ms)
            self._record("asr.speech_start_to_first_text", context, metrics.asr_speech_to_first_text_ms)
        self._record("asr.last_frame_to_final_text", context, metrics.asr_final_tail_ms)

    def asr_discard(self, turns: set[tuple[str, int]]) -> None:
        for turn in turns:
            self._asr.pop(turn, None)

    def tts_text(self, context: InteractionContext, speech_id: str, text: str) -> None:
        self._tts.setdefault(self._tts_key(context, speech_id), ProviderLatencyTrace()).tts_text_chunk(text)

    def tts_audio(self, context: InteractionContext, speech_id: str, audio: bytes) -> None:
        trace = self._tts.get(self._tts_key(context, speech_id))
        if trace is None:
            return
        before = trace.snapshot().tts_first_audio_ms
        trace.tts_audio_chunk(audio)
        if before is None:
            self._record("tts.first_text_to_first_audio", context, trace.snapshot().tts_first_audio_ms)

    def tts_end(self, context: InteractionContext, speech_id: str) -> None:
        self._tts.pop(self._tts_key(context, speech_id), None)

    @staticmethod
    def _asr_key(context: InteractionContext) -> tuple[str, int]:
        return (context.voice_session_id, context.generation)

    @staticmethod
    def _tts_key(context: InteractionContext, speech_id: str) -> tuple[str, str]:
        return (context.voice_session_id, speech_id)

    def _record(
        self,
        name: str,
        context: InteractionContext,
        duration_ms: float | None,
        *,
        response_id: str | None = None,
    ) -> None:
        if duration_ms is None:
            return
        capability = name.split(".", 1)[0]
        attributes = {
            **({"instance_id": self._instances[capability]} if capability in self._instances else {}),
            **({"config_version": self._versions[capability]} if capability in self._versions else {}),
        }
        self._telemetry.record(
            name, generation=context.generation, kind=TelemetryKind.SPAN,
            duration_ms=duration_ms, turn_id=context.turn_id,
            response_id=response_id or context.response_id, attributes=attributes,
        )


class TimedAsrSession:
    def __init__(self, delegate: AsrCapabilitySession, timing: ProviderLatencyObserver) -> None:
        self._delegate = delegate
        self._timing = timing
        self._turns: set[tuple[str, int]] = set()

    async def send(self, command) -> None:
        if isinstance(command, AppendAsrAudio) and command.context is not None:
            self._turns.add((command.context.voice_session_id, command.context.generation))
            self._timing.asr_frame(command.context)
        elif isinstance(command, DiscardAsrInput):
            self._timing.asr_discard(self._turns)
            self._turns.clear()
        await self._delegate.send(command)

    async def events(self) -> AsyncIterator[AsrEvent]:
        async for event in self._delegate.events():
            if isinstance(event, AsrTranscriptDelta):
                self._timing.asr_partial(event.context, event.accumulated_text)
            elif isinstance(event, AsrTranscriptFinal):
                self._timing.asr_final(event.context, event.text)
            yield event

    async def close(self) -> None:
        try:
            await self._delegate.close()
        finally:
            self._timing.asr_discard(self._turns)
            self._turns.clear()


class TimedTtsSession:
    def __init__(self, delegate: TtsCapabilitySession, timing: ProviderLatencyObserver, context: InteractionContext) -> None:
        self._delegate = delegate
        self._timing = timing
        self._context = context
        self._speech_ids: set[str] = set()

    @property
    def text_mode(self) -> TtsTextMode:
        return self._delegate.text_mode

    async def send(self, command) -> None:
        if isinstance(command, AppendTtsText):
            self._speech_ids.add(command.speech_id)
            self._timing.tts_text(self._context, command.speech_id, command.delta)
        elif isinstance(command, CancelTts):
            self._timing.tts_end(self._context, command.speech_id)
        await self._delegate.send(command)

    async def events(self) -> AsyncIterator[TtsEvent]:
        async for event in self._delegate.events():
            if isinstance(event, TtsAudioFrame):
                self._timing.tts_audio(event.context, event.speech_id, event.frame.data)
            elif isinstance(event, (TtsCompleted, TtsCancelled, TtsFailed)):
                self._timing.tts_end(event.context, event.speech_id)
            yield event

    async def close(self) -> None:
        try:
            await self._delegate.close()
        finally:
            for speech_id in self._speech_ids:
                self._timing.tts_end(self._context, speech_id)
            self._speech_ids.clear()
