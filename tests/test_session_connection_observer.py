from datetime import UTC, datetime
from unittest.mock import Mock
from server.observability.session_connection import SessionConnectionObserver
from server.voice_session.models import VoiceSessionIdentity, VoiceSessionPhase, VoiceSessionPhaseChanged


def phase(source, target, sequence):
    return VoiceSessionPhaseChanged(event_id=f"e-{sequence}", identity=VoiceSessionIdentity(
        tenant_id="t", user_id="u", device_id="d", voice_session_id="s", thread_id="thread"),
        session_sequence=sequence, occurred_at=datetime.now(UTC), from_phase=source, to_phase=target)


def test_disconnect_is_deduplicated_and_recovery_correlated():
    telemetry = Mock()
    observer = SessionConnectionObserver(telemetry)
    event = phase(VoiceSessionPhase.ACTIVE, VoiceSessionPhase.RECONNECTING, 1)
    observer(event)
    observer(event)
    observer(phase(VoiceSessionPhase.RECONNECTING, VoiceSessionPhase.ACTIVE, 2))
    names = [call.args[0] for call in telemetry.record.call_args_list]
    assert names == ["transport.collection_ready", "transport.disconnected", "transport.recovered"]
    assert telemetry.record.call_args_list[-1].kwargs["attributes"]["incident_id"] == "e-1"


def test_normal_end_does_not_count_as_disconnect():
    telemetry = Mock()
    observer = SessionConnectionObserver(telemetry)
    observer(phase(VoiceSessionPhase.ACTIVE, VoiceSessionPhase.CLOSED, 1))
    assert telemetry.record.call_count == 1


def test_shutdown_finalizes_pending_recovery_once():
    telemetry = Mock()
    observer = SessionConnectionObserver(telemetry)
    observer(phase(VoiceSessionPhase.ACTIVE, VoiceSessionPhase.RECONNECTING, 1))
    observer.close()
    observer.close()
    observer(phase(VoiceSessionPhase.RECONNECTING, VoiceSessionPhase.CLOSED, 2))
    assert [call.args[0] for call in telemetry.record.call_args_list] == [
        "transport.collection_ready", "transport.disconnected", "transport.recovery_failed"]
