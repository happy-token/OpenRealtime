"""Session phase evidence for unexpected disconnects and completed recovery."""

import time

from server.observability.telemetry import (
    SessionTelemetry,
    TelemetryKind,
    TelemetryOutcome,
    TelemetrySeverity,
)
from server.realtime.transport.output_stop import OutputStopObservation
from server.voice_session.models import VoiceSessionPhase, VoiceSessionPhaseChanged


class SessionConnectionObserver:
    def __init__(self, telemetry: SessionTelemetry):
        self.telemetry = telemetry
        self.pending: tuple[str, int] | None = None
        telemetry.record("transport.collection_ready")

    def __call__(self, event: object) -> None:
        if isinstance(event, OutputStopObservation):
            _record_output_stop(self.telemetry, event)
            return
        if not isinstance(event, VoiceSessionPhaseChanged):
            return
        if (
            event.from_phase is VoiceSessionPhase.ACTIVE
            and event.to_phase is VoiceSessionPhase.RECONNECTING
        ):
            if self.pending is None:
                self.pending = (event.event_id, time.monotonic_ns())
                self.telemetry.record(
                    "transport.disconnected", attributes={"incident_id": event.event_id}
                )
        elif self.pending is not None and event.to_phase is VoiceSessionPhase.ACTIVE:
            incident, started = self.pending
            self.pending = None
            self.telemetry.record(
                "transport.recovered",
                duration_ms=(time.monotonic_ns() - started) / 1_000_000,
                attributes={"incident_id": incident},
            )
        elif self.pending is not None and event.to_phase.value in {"closed", "failed"}:
            self.close()

    def close(self) -> None:
        """Finalize recovery even when the event pump stops before CLOSED delivery."""
        if self.pending is None:
            return
        incident, _ = self.pending
        self.pending = None
        self.telemetry.record(
            "transport.recovery_failed",
            outcome=TelemetryOutcome.ERROR,
            attributes={"incident_id": incident},
        )


def _record_output_stop(telemetry: SessionTelemetry, event: OutputStopObservation) -> None:
    """Project observations through the existing nonblocking diagnostics writer."""
    target = event.target_context
    handoff = {
        "requested": "pending",
        "receipt": "pending",
        "handoff_ready": "granted",
        "handoff_failed": "denied",
    }[event.phase]
    details = {
        "stop_command_id": event.request.stop_command_id,
        "output_epoch": event.request.output_epoch,
        "speech_id": event.request.speech_id,
        "stop_reason": event.request.reason,
        "state": event.state,
        "reason_code": event.reason,
        "receipt_outcome": event.receipt_outcome,
        "played_position_samples": event.played_position_samples,
        "handoff": handoff,
        "requested_at": event.requested_at.isoformat(),
        "received_at": event.received_at.isoformat() if event.received_at else None,
        "requested_monotonic_ns": event.requested_ns,
        "received_monotonic_ns": event.received_ns,
        "observed_wait_ms": (event.monotonic_ns - event.requested_ns) / 1_000_000,
        "evidence": "local_output_queue_receipt",
        "authority": "transport_observation",
    }

    def record(
        name: str,
        *,
        outcome: TelemetryOutcome = TelemetryOutcome.OK,
        kind: TelemetryKind = TelemetryKind.EVENT,
        duration_ms: float | None = None,
    ) -> None:
        telemetry.record(
            name,
            generation=event.request.generation,
            turn_id=target.turn_id if target else None,
            response_id=target.response_id if target else None,
            call_id=event.request.stop_command_id,
            occurred_at=event.occurred_at,
            monotonic_ns=event.monotonic_ns,
            timeout_ms=event.timeout_ms,
            attributes=details,
            outcome=outcome,
            kind=kind,
            duration_ms=duration_ms,
            severity=TelemetrySeverity.INFO
            if outcome in {TelemetryOutcome.OK, TelemetryOutcome.CANCELLED}
            else TelemetrySeverity.ERROR,
            error=event.reason
            if outcome in {TelemetryOutcome.ERROR, TelemetryOutcome.TIMEOUT}
            else None,
        )

    outcome = TelemetryOutcome.OK
    if event.phase == "handoff_failed":
        if event.reason == "session_closed":
            outcome = TelemetryOutcome.CANCELLED
        elif event.reason in {"receipt_deadline", "playback_projection_deadline"}:
            outcome = TelemetryOutcome.TIMEOUT
        else:
            outcome = TelemetryOutcome.ERROR
    record(f"playback.stop_{event.phase}", outcome=outcome)

    # Only successful, independently named spans enter latency aggregates.
    # Failed/cancelled elapsed times remain metadata, not successful samples.
    if event.phase == "receipt" and event.receipt_outcome == "queue_stopped":
        record(
            "playback.stop_request_to_receipt",
            kind=TelemetryKind.SPAN,
            duration_ms=(event.monotonic_ns - event.requested_ns) / 1_000_000,
        )
    elif event.phase == "handoff_ready":
        assert event.received_ns is not None
        record(
            "playback.stop_receipt_to_handoff",
            kind=TelemetryKind.SPAN,
            duration_ms=(event.monotonic_ns - event.received_ns) / 1_000_000,
        )
        record(
            "playback.stop_request_to_handoff",
            kind=TelemetryKind.SPAN,
            duration_ms=(event.monotonic_ns - event.requested_ns) / 1_000_000,
        )
