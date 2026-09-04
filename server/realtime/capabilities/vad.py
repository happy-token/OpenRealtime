"""Typed VAD capability and adapter for the existing VAD seam."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol, cast

from server.core.interaction_context import InteractionContext
from server.realtime.protocol.audio import AudioEncoding, AudioFrame
from server.signals.energy_vad import Vad
from server.turn_policy.signals import Signal

_CLOSED = object()


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalyzeVadAudio:
    frame: AudioFrame
    context: InteractionContext | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VadSpeechStarted:
    context: InteractionContext
    audio_timestamp_us: int
    confidence: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VadSpeechStopped:
    context: InteractionContext
    audio_timestamp_us: int
    silence_duration_us: int
    confidence: float | None = None


VadCommand = AnalyzeVadAudio
VadEvent = VadSpeechStarted | VadSpeechStopped


class VadCapabilitySession(Protocol):
    async def send(self, command: VadCommand) -> None: ...

    def events(self) -> AsyncIterator[VadEvent]: ...

    async def close(self) -> None: ...


class VadCapabilityProvider(Protocol):
    async def open(self, *, context: InteractionContext) -> VadCapabilitySession: ...


class LegacyVadCapabilityAdapter:
    """Creates one stateful typed capability session per legacy VAD instance."""

    def __init__(self, vad_factory: Callable[[], Vad]) -> None:
        self._vad_factory = vad_factory

    async def open(self, *, context: InteractionContext) -> LegacyVadCapabilitySession:
        return LegacyVadCapabilitySession(context=context, vad=self._vad_factory())


class LegacyVadCapabilitySession:
    def __init__(self, *, context: InteractionContext, vad: Vad) -> None:
        self._context = context
        self._vad = vad
        self._events: asyncio.Queue[VadEvent | object] = asyncio.Queue(maxsize=64)
        self._closed = False

    async def send(self, command: VadCommand) -> None:
        if self._closed:
            raise RuntimeError("VAD capability session is closed")
        frame = command.frame
        event_context = command.context or self._context
        if frame.encoding is not AudioEncoding.PCM_S16LE or frame.channels != 1:
            raise ValueError("legacy VAD adapter requires mono PCM_S16LE audio")
        observation = self._vad.observe_chunk(
            frame.data,
            sample_rate_hz=frame.sample_rate_hz,
        )
        if observation is None or observation.signal is None:
            return
        if observation.signal is Signal.USER_SPEECH_ONSET:
            await self._events.put(
                VadSpeechStarted(
                    context=event_context,
                    audio_timestamp_us=frame.timestamp_us,
                )
            )
            return
        if observation.signal is Signal.USER_EOT_CONFIRMED:
            await self._events.put(
                VadSpeechStopped(
                    context=event_context,
                    audio_timestamp_us=frame.end_timestamp_us,
                    silence_duration_us=round(observation.silence_ms * 1_000),
                )
            )

    async def events(self) -> AsyncIterator[VadEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            yield cast(VadEvent, event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._events.put(_CLOSED)
