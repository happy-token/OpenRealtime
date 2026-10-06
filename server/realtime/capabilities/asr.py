"""Typed ASR capability and adapter for the existing streaming ASR seam."""

from __future__ import annotations

import time
from server.observability.telemetry import SessionTelemetry, TelemetryOutcome

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, cast

from server.core.interaction_context import InteractionContext
from server.realtime.protocol.audio import AudioEncoding, AudioFrame
from server.speech.asr import AsrEngine, AsrSession

_CLOSED = object()


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendAsrAudio:
    frame: AudioFrame
    context: InteractionContext | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CommitAsrInput:
    reason: str
    context: InteractionContext | None = None

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("ASR commit reason must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscardAsrInput:
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("ASR discard reason must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class AsrTranscriptDelta:
    context: InteractionContext
    revision: int
    delta: str
    accumulated_text: str
    audio_timestamp_us: int = 0
    replaces_previous: bool = False

    def __post_init__(self) -> None:
        if self.revision < 1 or not self.delta or not self.accumulated_text:
            raise ValueError("ASR transcript delta must be non-empty and revisioned")
        if self.audio_timestamp_us < 0:
            raise ValueError("ASR transcript audio timestamp must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class AsrEndpointHint:
    context: InteractionContext
    revision: int
    text: str

    def __post_init__(self) -> None:
        if self.revision < 1 or not self.text:
            raise ValueError("ASR endpoint hint must be non-empty and revisioned")


@dataclass(frozen=True, slots=True, kw_only=True)
class AsrTranscriptFinal:
    context: InteractionContext
    revision: int
    text: str
    reason: str

    def __post_init__(self) -> None:
        if self.revision < 1 or not self.text or not self.reason:
            raise ValueError("final ASR transcript must be non-empty and revisioned")


@dataclass(frozen=True, slots=True, kw_only=True)
class AsrCommitRejected:
    """A requested commit had no transcript yet and can be retried later."""

    context: InteractionContext
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("ASR commit rejection reason must be non-empty")


AsrCommand = AppendAsrAudio | CommitAsrInput | DiscardAsrInput
AsrEvent = AsrTranscriptDelta | AsrEndpointHint | AsrTranscriptFinal | AsrCommitRejected


class AsrCapabilitySession(Protocol):
    async def send(self, command: AsrCommand) -> None: ...

    def events(self) -> AsyncIterator[AsrEvent]: ...

    async def close(self) -> None: ...


class AsrCapabilityProvider(Protocol):
    async def open(self, *, context: InteractionContext) -> AsrCapabilitySession: ...


class LegacyAsrCapabilityAdapter:
    def __init__(self, engine: AsrEngine, *, telemetry: SessionTelemetry | None = None) -> None:
        self._engine = engine
        self._telemetry = telemetry

    async def open(self, *, context: InteractionContext) -> LegacyAsrCapabilitySession:
        if self._telemetry is None:
            session = await self._engine.start_session()
        else:
            async with self._telemetry.provider_call(provider="asr", operation="connection_setup", generation=context.generation):
                session = await self._engine.start_session()
        return LegacyAsrCapabilitySession(
            context=context,
            engine=self._engine,
            session=session,
            telemetry=self._telemetry,
        )


class LegacyAsrCapabilitySession:
    def __init__(
        self,
        *,
        context: InteractionContext,
        engine: AsrEngine,
        session: AsrSession,
        telemetry: SessionTelemetry | None = None,
    ) -> None:
        self._context = context
        self._engine = engine
        self._session = session
        self._telemetry = telemetry
        if telemetry is not None:
            telemetry.record("asr.collection_ready")
        self._events: asyncio.Queue[AsrEvent | object] = asyncio.Queue(maxsize=64)
        self._last_text = ""
        self._last_revision = 0
        self._last_endpoint_revision = 0
        self._last_context = context
        self._closed = False

    async def send(self, command: AsrCommand) -> None:
        if self._closed:
            raise RuntimeError("ASR capability session is closed")
        if isinstance(command, AppendAsrAudio):
            self._last_context = command.context or self._context
            await self._append_audio(command.frame, context=self._last_context)
            return
        if isinstance(command, CommitAsrInput):
            text = await self._session.consume_transcript()
            if not text:
                await self._events.put(
                    AsrCommitRejected(
                        context=command.context or self._last_context,
                        reason="empty_transcript",
                    )
                )
                self._last_text = ""
                return
            await self._events.put(
                AsrTranscriptFinal(
                    context=command.context or self._last_context,
                    revision=max(1, self._last_revision),
                    text=text,
                    reason=command.reason,
                )
            )
            self._last_text = ""
            return
        if isinstance(command, DiscardAsrInput):
            await self._session.consume_transcript()
            self._last_text = ""
            return
        raise TypeError(f"unsupported ASR capability command: {type(command).__name__}")

    async def _append_audio(
        self,
        frame: AudioFrame,
        *,
        context: InteractionContext,
    ) -> None:
        if frame.encoding is not AudioEncoding.PCM_S16LE or frame.channels != 1:
            raise ValueError("legacy ASR adapter requires mono PCM_S16LE audio")
        if not self._session.is_alive:
            await self._restart_session()
        await self._session.push_audio(frame.data, sample_rate_hz=frame.sample_rate_hz)
        if not self._session.is_alive:
            # The provider can expire between the liveness check and the send.
            # Re-send this one frame so the first audio after a long-idle browser
            # session is not silently discarded.
            if self._telemetry is not None:
                self._telemetry.record("asr.connection_lost", generation=context.generation)
            await self._restart_session()
            await self._session.push_audio(
                frame.data,
                sample_rate_hz=frame.sample_rate_hz,
            )
        snapshot = await self._session.snapshot()
        if snapshot.revision > self._last_revision and snapshot.text:
            replaces_previous = not snapshot.text.startswith(self._last_text)
            delta = (
                snapshot.text[len(self._last_text) :] if not replaces_previous else snapshot.text
            )
            if delta:
                await self._events.put(
                    AsrTranscriptDelta(
                        context=context,
                        revision=snapshot.revision,
                        delta=delta,
                        accumulated_text=snapshot.text,
                        audio_timestamp_us=frame.timestamp_us + frame.duration_us,
                        replaces_previous=replaces_previous,
                    )
                )
            self._last_text = snapshot.text
            self._last_revision = snapshot.revision
        if (
            snapshot.is_sentence_end
            and snapshot.sentence_end_revision > self._last_endpoint_revision
        ):
            await self._events.put(
                AsrEndpointHint(
                    context=context,
                    revision=snapshot.sentence_end_revision,
                    text=snapshot.text,
                )
            )
            self._last_endpoint_revision = snapshot.sentence_end_revision

    async def _restart_session(self) -> None:
        started = time.monotonic_ns()
        if self._telemetry is not None:
            self._telemetry.record("asr.session_restarted")
        previous = self._session
        with contextlib.suppress(Exception):
            await previous.close()
        try:
            self._session = await self._engine.start_session()
        except Exception as error:
            if self._telemetry is not None:
                self._telemetry.record("asr.restart_failed", outcome=TelemetryOutcome.ERROR, error=error)
            raise
        if self._telemetry is not None:
            self._telemetry.record("asr.restart_completed", duration_ms=(time.monotonic_ns()-started)/1_000_000)
        self._last_text = ""
        self._last_revision = 0
        self._last_endpoint_revision = 0

    async def events(self) -> AsyncIterator[AsrEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            yield cast(AsrEvent, event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._session.close()
        await self._events.put(_CLOSED)
