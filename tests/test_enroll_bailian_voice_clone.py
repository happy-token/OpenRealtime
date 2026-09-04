import pytest

from scripts.enroll_bailian_voice_clone import (
    build_enrollment_payload,
    public_object_url,
    resolve_enrollment_endpoint,
)


def test_enrollment_payload_targets_current_cosyvoice_model() -> None:
    payload = build_enrollment_payload(
        target_model="cosyvoice-v3-flash",
        prefix="openrt",
        audio_url="https://assets.example.com/openrealtime/voice-clones/sample.wav",
    )

    assert payload["model"] == "voice-enrollment"
    assert payload["input"]["action"] == "create_voice"
    assert payload["input"]["target_model"] == "cosyvoice-v3-flash"
    assert payload["input"]["enable_preprocess"] is False


def test_voice_prefix_and_public_url_are_strictly_validated() -> None:
    with pytest.raises(ValueError, match="prefix"):
        build_enrollment_payload(
            target_model="cosyvoice-v3-flash",
            prefix="不安全",
            audio_url="https://assets.example.com/sample.wav",
        )
    with pytest.raises(ValueError, match="HTTPS"):
        public_object_url("http://localhost:3010", "sample.wav")


def test_workspace_endpoint_and_object_url_are_composed_without_secrets() -> None:
    assert resolve_enrollment_endpoint({"BAILIAN_API_HOST": "llm-demo.cn-beijing.maas.aliyuncs.com"}) == (
        "https://llm-demo.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/customization"
    )
    assert public_object_url("https://assets.example.com", "open realtime/a.wav") == (
        "https://assets.example.com/open%20realtime/a.wav"
    )
