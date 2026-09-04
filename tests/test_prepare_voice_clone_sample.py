from pathlib import Path

import pytest

from scripts.prepare_voice_clone_sample import (
    MAX_CLIP_SECONDS,
    build_clip_plan,
    build_ffmpeg_command,
)


def test_build_clip_plan_clamps_to_source_and_never_exceeds_sixty_seconds() -> None:
    plan = build_clip_plan(
        Path("authorized.mp3"),
        Path("sample.wav"),
        source_duration_s=72.0,
        start_s=20.0,
        duration_s=MAX_CLIP_SECONDS,
        rights_confirmed=True,
    )

    assert plan.start_s == 20.0
    assert plan.duration_s == 52.0


def test_build_clip_plan_requires_explicit_rights_confirmation() -> None:
    with pytest.raises(ValueError, match="rights"):
        build_clip_plan(
            Path("authorized.mp3"),
            Path("sample.wav"),
            source_duration_s=20.0,
            start_s=0.0,
            duration_s=20.0,
            rights_confirmed=False,
        )


def test_build_clip_plan_rejects_unsupported_or_too_short_output() -> None:
    with pytest.raises(ValueError, match="WAV"):
        build_clip_plan(
            Path("authorized.mp3"),
            Path("sample.mp3"),
            source_duration_s=20.0,
            start_s=0.0,
            duration_s=20.0,
            rights_confirmed=True,
        )

    with pytest.raises(ValueError, match="at least 5"):
        build_clip_plan(
            Path("authorized.mp3"),
            Path("sample.wav"),
            source_duration_s=4.0,
            start_s=0.0,
            duration_s=4.0,
            rights_confirmed=True,
        )


def test_ffmpeg_command_outputs_clone_ready_pcm_without_audio_enhancement() -> None:
    plan = build_clip_plan(
        Path("authorized.mp3"),
        Path("sample.wav"),
        source_duration_s=30.0,
        start_s=4.0,
        duration_s=20.0,
        rights_confirmed=True,
    )

    command = build_ffmpeg_command(plan, ffmpeg_bin="/usr/bin/ffmpeg", overwrite=True)

    assert command[:2] == ["/usr/bin/ffmpeg", "-nostdin"]
    assert command[command.index("-ss") + 1] == "4.000"
    assert command[command.index("-t") + 1] == "20.000"
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-ar") + 1] == "24000"
    assert command[command.index("-c:a") + 1] == "pcm_s16le"
    assert "-af" not in command
    assert command[-1] == "sample.wav"
