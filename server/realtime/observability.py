"""Project public Realtime commands and events into session diagnostics."""

from __future__ import annotations

import time
from typing import Protocol

from server.observability.telemetry import (
    SessionTelemetry,
    TelemetryKind,
    TelemetryOutcome,
)
from server.realtime.protocol.commands import RealtimeCommand, RequestResponse
from server.realtime.protocol.events import (
    AudioDelta,
    DialogueStateChanged,
    DisplayContentDelta,
    InputTranscriptCompleted,
    InputTranscriptDelta,
    RealtimeCapabilityFailed,
    RealtimeEvent,
    ResponseCancelled,
    ResponseCompleted,
    ResponseFailed,
    ResponseStarted,
    SpeechPlaybackProgress,
)


class RealtimeObserver(Protocol):
    def observe_command(self, command: RealtimeCommand) -> None: ...

    def observe_event(self, event: RealtimeEvent) -> None: ...


class RealtimeTelemetryObserver:
    """Keep telemetry mapping and timing anchors behind one small interface."""

    def __init__(self, telemetry: SessionTelemetry) -> None:
        self._telemetry = telemetry
        self._requested_ns: dict[str, int] = {}
        self._started_ns: dict[str, int] = {}
        self._first_text: set[str] = set()
        self._first_audio: set[str] = set()
        self._endpoint_committed_ns: dict[int, int] = {}
        self._playback_started: set[str] = set()

    def observe_command(self, command: RealtimeCommand) -> None:
        if not isinstance(command, RequestResponse):
            return
        now = time.monotonic_ns()
        self._requested_ns[command.response_id] = now
        self._telemetry.record(
            "realtime.response_requested",
            generation=command.context.generation,
            kind=TelemetryKind.MILESTONE,
            turn_id=command.context.turn_id,
            response_id=command.response_id,
            monotonic_ns=now,
            attributes={
                "minimum_thread_sequence": command.minimum_thread_sequence,
            },
        )

    def observe_event(self, event: RealtimeEvent) -> None:
        now = time.monotonic_ns()
        context = event.context
        if isinstance(event, DialogueStateChanged):
            self._telemetry.record(
                "dialogue.state_changed",
                generation=context.generation,
                turn_id=context.turn_id,
                monotonic_ns=now,
                occurred_at=event.occurred_at,
                attributes={
                    "from_state": event.from_state.value,
                    "to_state": event.to_state.value,
                    "transition": event.transition,
                },
            )
            return
        if isinstance(event, InputTranscriptDelta):
            self._telemetry.record(
                "asr.transcript_delta",
                generation=context.generation,
                turn_id=context.turn_id,
                monotonic_ns=now,
                occurred_at=event.occurred_at,
                attributes={
                    "audio_timestamp_us": event.audio_timestamp_us,
                    "replaces_previous": event.replaces_previous,
                    "text_length": len(event.text),
                    "transcript_revision": event.transcript_revision,
                },
            )
            return
        if isinstance(event, InputTranscriptCompleted):
            self._endpoint_committed_ns[context.generation] = now
            self._telemetry.record(
                "asr.transcript_completed",
                generation=context.generation,
                kind=TelemetryKind.MILESTONE,
                turn_id=context.turn_id,
                monotonic_ns=now,
                occurred_at=event.occurred_at,
                attributes={
                    "transcript_revision": event.transcript_revision,
                    "provider_endpoint_observed": event.provider_endpoint_observed,
                    "text_length": len(event.text),
                },
            )
            return
        if isinstance(event, ResponseStarted):
            self._started_ns[event.response_id] = now
            self._record_span_from(
                "brain.response_started",
                response_id=event.response_id,
                started_ns=self._requested_ns.get(event.response_id),
                ended_ns=now,
                event=event,
            )
            return
        if isinstance(event, DisplayContentDelta):
            if event.response_id in self._first_text:
                return
            self._first_text.add(event.response_id)
            self._record_span_from(
                "brain.time_to_first_text",
                response_id=event.response_id,
                started_ns=self._requested_ns.get(event.response_id),
                ended_ns=now,
                event=event,
            )
            return
        if isinstance(event, AudioDelta):
            if event.response_id in self._first_audio:
                return
            self._first_audio.add(event.response_id)
            self._record_span_from(
                "tts.time_to_first_audio",
                response_id=event.response_id,
                started_ns=self._started_ns.get(event.response_id),
                ended_ns=now,
                event=event,
            )
            return
        if isinstance(event, ResponseCompleted):
            self._record_terminal(event, TelemetryOutcome.OK)
            return
        if isinstance(event, ResponseCancelled):
            self._record_terminal(
                event,
                TelemetryOutcome.CANCELLED,
                error=event.reason,
            )
            return
        if isinstance(event, ResponseFailed):
            outcome = _failure_outcome(event.error)
            self._record_terminal(event, outcome, error=event.error)
            return
        if isinstance(event, RealtimeCapabilityFailed):
            self._telemetry.record(
                f"realtime.capability.{event.capability}",
                generation=context.generation,
                outcome=_failure_outcome(f"{event.capability} {event.error}"),
                turn_id=context.turn_id,
                response_id=context.response_id,
                call_id=context.call_id,
                worker_id=context.worker_id,
                error=event.error,
                monotonic_ns=now,
                occurred_at=event.occurred_at,
                attributes={"capability": event.capability},
            )
            return
        if isinstance(event, SpeechPlaybackProgress):
            if event.speech_id not in self._playback_started:
                self._playback_started.add(event.speech_id)
                endpoint_ns = self._endpoint_committed_ns.pop(
                    context.generation,
                    None,
                )
                if endpoint_ns is not None and now >= endpoint_ns:
                    self._telemetry.record(
                        "turn.endpoint_to_client_playback",
                        generation=context.generation,
                        kind=TelemetryKind.SPAN,
                        duration_ms=(now - endpoint_ns) / 1_000_000,
                        turn_id=context.turn_id,
                        response_id=context.response_id,
                        monotonic_ns=now,
                        occurred_at=event.occurred_at,
                    )
            self._telemetry.record(
                "client.playback_progress",
                generation=context.generation,
                turn_id=context.turn_id,
                response_id=context.response_id,
                monotonic_ns=now,
                occurred_at=event.occurred_at,
                attributes={
                    "speech_id": event.speech_id,
                    "delivered_text_end": event.delivered_text_end,
                    "played_audio_end_us": event.played_audio_end_us,
                    "precision": event.precision.value,
                    "completed": event.completed,
                },
            )

    def _record_span_from(
        self,
        name: str,
        *,
        response_id: str,
        started_ns: int | None,
        ended_ns: int,
        event: ResponseStarted | DisplayContentDelta | AudioDelta,
    ) -> None:
        duration_ms = None
        if started_ns is not None and ended_ns >= started_ns:
            duration_ms = (ended_ns - started_ns) / 1_000_000
        self._telemetry.record(
            name,
            generation=event.context.generation,
            kind=TelemetryKind.SPAN,
            duration_ms=duration_ms,
            turn_id=event.context.turn_id,
            response_id=response_id,
            monotonic_ns=ended_ns,
            occurred_at=event.occurred_at,
        )

    def _record_terminal(
        self,
        event: ResponseCompleted | ResponseCancelled | ResponseFailed,
        outcome: TelemetryOutcome,
        *,
        error: str | None = None,
    ) -> None:
        now = time.monotonic_ns()
        started_ns = self._requested_ns.pop(event.response_id, None)
        duration_ms = (
            (now - started_ns) / 1_000_000
            if started_ns is not None and now >= started_ns
            else None
        )
        self._started_ns.pop(event.response_id, None)
        self._first_text.discard(event.response_id)
        self._first_audio.discard(event.response_id)
        self._telemetry.turn_terminal(
            event.context.generation,
            outcome=outcome,
            duration_ms=duration_ms,
            turn_id=event.context.turn_id,
            response_id=event.response_id,
            error=error,
            attributes={"realtime_event": type(event).__name__},
        )


def _failure_outcome(error: str) -> TelemetryOutcome:
    normalized = error.lower()
    if "timeout" in normalized or "deadline" in normalized:
        return TelemetryOutcome.TIMEOUT
    return TelemetryOutcome.ERROR
