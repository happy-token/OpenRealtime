from __future__ import annotations

import pytest

from server.voice_session import VoiceSessionIdentity
from server.voice_session.registry import ActiveVoiceSessionRegistry, ResumeRejected


def identity(*, user_id: str = "user-1") -> VoiceSessionIdentity:
    return VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id=user_id,
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
    )


def test_resume_token_is_detached_only_single_use_and_rotated() -> None:
    registry = ActiveVoiceSessionRegistry(grace_period_s=60)
    runtime = object()
    first_token = registry.register(
        identity=identity(),
        protocol_version=2,
        runtime=runtime,
    )
    registry.detach("voice-1")

    resumed, second_token = registry.resume(
        identity=identity(),
        voice_session_id="voice-1",
        protocol_version=2,
        resume_token=first_token,
    )

    assert resumed is runtime
    assert second_token != first_token
    registry.detach("voice-1")
    with pytest.raises(ResumeRejected):
        registry.resume(
            identity=identity(),
            voice_session_id="voice-1",
            protocol_version=2,
            resume_token=first_token,
        )
    resumed_again, _ = registry.resume(
        identity=identity(),
        voice_session_id="voice-1",
        protocol_version=2,
        resume_token=second_token,
    )
    assert resumed_again is runtime
