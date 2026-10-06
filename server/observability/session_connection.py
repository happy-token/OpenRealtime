"""Session phase evidence for unexpected disconnects and completed recovery."""
import time
from server.observability.telemetry import SessionTelemetry, TelemetryOutcome
from server.voice_session.models import VoiceSessionPhaseChanged, VoiceSessionPhase


class SessionConnectionObserver:
    def __init__(self, telemetry: SessionTelemetry):
        self.telemetry = telemetry
        self.pending: tuple[str, int] | None = None
        telemetry.record("transport.collection_ready")

    def __call__(self, event: object) -> None:
        if not isinstance(event, VoiceSessionPhaseChanged):
            return
        if event.from_phase is VoiceSessionPhase.ACTIVE and event.to_phase is VoiceSessionPhase.RECONNECTING:
            if self.pending is None:
                self.pending = (event.event_id, time.monotonic_ns())
                self.telemetry.record("transport.disconnected", attributes={"incident_id": event.event_id})
        elif self.pending is not None and event.to_phase is VoiceSessionPhase.ACTIVE:
            incident, started = self.pending
            self.pending = None
            self.telemetry.record("transport.recovered", duration_ms=(time.monotonic_ns()-started)/1_000_000,
                attributes={"incident_id": incident})
        elif self.pending is not None and event.to_phase.value in {"closed", "failed"}:
            self.close()

    def close(self) -> None:
        """Finalize recovery even when the event pump stops before CLOSED delivery."""
        if self.pending is None:
            return
        incident, _ = self.pending
        self.pending = None
        self.telemetry.record("transport.recovery_failed", outcome=TelemetryOutcome.ERROR,
            attributes={"incident_id": incident})
