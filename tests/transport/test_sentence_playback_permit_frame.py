"""Wire validation is not actor authorization; malformed grants never reach renderers."""

import pytest
from pydantic import ValidationError

from server.transport.frames import AssistantSpeechCancelledFrame


def stop_frame():
    return {
        "generation": 1,
        "output_epoch": "epoch",
        "speech_id": "response:reply",
        "stop_command_id": "stop",
        "sentence_permit": {
            "permit_id": "permit",
            "input_id": "input",
            "input_version": 1,
            "response_id": "reply",
            "reply_version": 1,
            "sentence_id": "sentence",
            "audio_start_samples": 0,
            "audio_end_samples": 24000,
            "sample_rate_hz": 24000,
            "max_wait_ms": 1500,
        },
    }


def test_sentence_permit_round_trips_full_version_and_exact_stop_target():
    frame = AssistantSpeechCancelledFrame.model_validate(stop_frame())
    assert frame.sentence_permit.input_version == 1
    assert frame.sentence_permit.reply_version == 1
    assert AssistantSpeechCancelledFrame.model_validate_json(frame.model_dump_json()) == frame


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_version", True),
        ("reply_version", "1"),
        ("audio_end_samples", 1.5),
        ("audio_start_samples", False),
        ("audio_end_samples", 0),
        ("audio_end_samples", 2**53),
        ("sample_rate_hz", 0),
        ("sample_rate_hz", 384001),
        ("max_wait_ms", 5001),
        ("max_wait_ms", 0),
        ("sentence_id", ""),
        ("response_id", "other"),
        ("unexpected", "field"),
    ],
)
def test_invalid_sentence_permit_is_rejected_before_playback(field, value):
    raw = stop_frame()
    raw["sentence_permit"][field] = value
    with pytest.raises(ValidationError):
        AssistantSpeechCancelledFrame.model_validate(raw)


@pytest.mark.parametrize(
    "change",
    [
        {"output_epoch": None, "speech_id": None, "stop_command_id": None},
        {"reason": "failed"},
        {"reason": "cancelled"},
        {"generation": True},
        {"generation": "1"},
        {"generation": -1},
        {"generation": 2**53},
        {"output_epoch": b"epoch"},
        {"speech_id": b"response:reply"},
        {"stop_command_id": b"stop"},
    ],
)
def test_permit_requires_complete_interrupted_precise_target(change):
    with pytest.raises(ValidationError):
        AssistantSpeechCancelledFrame.model_validate({**stop_frame(), **change})
