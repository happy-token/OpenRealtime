from __future__ import annotations

from dataclasses import dataclass

import pytest

from server.voice_session import VoiceSessionAdmissionRejected, VoiceSessionIdentity
from server.voice_session.admission import (
    LocalVoiceSessionAdmissionController,
    VoiceSessionCapacityLimits,
    VoiceSessionResourceSnapshot,
)


def identity(session_id: str, *, device_id: str = "browser") -> VoiceSessionIdentity:
    return VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id=device_id,
        voice_session_id=session_id,
        thread_id=session_id,
    )


@dataclass
class FixedProbe:
    value: VoiceSessionResourceSnapshot

    async def snapshot(self) -> VoiceSessionResourceSnapshot:
        return self.value


def limits(**overrides: object) -> VoiceSessionCapacityLimits:
    values: dict[str, object] = {
        "max_active_sessions": 2,
        "max_asr_sessions": 2,
        "max_tts_sessions": 2,
        "max_event_loop_lag_ms": 200.0,
        "max_process_memory_bytes": 1_000_000,
        "max_audio_queue_bytes": 2_000,
        "audio_queue_reservation_bytes": 1_000,
        "retry_after_ms": 750,
    }
    values.update(overrides)
    return VoiceSessionCapacityLimits(**values)


async def test_shared_admission_rejects_at_capacity_and_release_is_idempotent() -> None:
    observations = []
    controller = LocalVoiceSessionAdmissionController(
        limits=limits(),
        probe=FixedProbe(
            VoiceSessionResourceSnapshot(
                event_loop_lag_ms=1,
                process_memory_bytes=100,
                audio_queue_bytes=0,
            )
        ),
        observer=observations.append,
    )

    first = await controller.acquire(identity("voice-1"))
    second = await controller.acquire(identity("voice-2", device_id="browser-2"))
    assert controller.active_sessions == 2

    with pytest.raises(VoiceSessionAdmissionRejected) as rejected:
        await controller.acquire(identity("voice-3", device_id="browser-3"))
    assert rejected.value.retry_after_ms == 750

    await first.release()
    await first.release()
    third = await controller.acquire(identity("voice-3", device_id="browser-3"))
    assert controller.active_sessions == 2

    await second.release()
    await third.release()
    assert controller.active_sessions == 0
    assert [observation.decision for observation in observations] == [
        "accepted",
        "accepted",
        "rejected",
        "released",
        "accepted",
        "released",
        "released",
    ]
    assert observations[2].reasons == (
        "active_sessions",
        "asr_sessions",
        "tts_sessions",
        "audio_queue",
    )
    assert observations[2].projected_sessions == 3
    assert observations[2].active_sessions == 2


@pytest.mark.parametrize(
    ("snapshot", "limit_override"),
    [
        (
            VoiceSessionResourceSnapshot(
                event_loop_lag_ms=201,
                process_memory_bytes=100,
                audio_queue_bytes=0,
            ),
            {},
        ),
        (
            VoiceSessionResourceSnapshot(
                event_loop_lag_ms=1,
                process_memory_bytes=1_000_001,
                audio_queue_bytes=0,
            ),
            {},
        ),
        (
            VoiceSessionResourceSnapshot(
                event_loop_lag_ms=1,
                process_memory_bytes=100,
                audio_queue_bytes=1_001,
            ),
            {},
        ),
    ],
)
async def test_admission_rejects_observed_resource_pressure(
    snapshot: VoiceSessionResourceSnapshot,
    limit_override: dict[str, object],
) -> None:
    controller = LocalVoiceSessionAdmissionController(
        limits=limits(**limit_override),
        probe=FixedProbe(snapshot),
    )

    with pytest.raises(VoiceSessionAdmissionRejected) as rejected:
        await controller.acquire(identity("voice-pressure"))

    assert rejected.value.retry_after_ms == 750
    assert controller.active_sessions == 0


def test_capacity_limits_reject_impossible_configuration() -> None:
    with pytest.raises(ValueError, match="audio queue reservation"):
        limits(
            max_audio_queue_bytes=999,
            audio_queue_reservation_bytes=1_000,
        )
