from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from server.avatar_assets import FfmpegRenditionEngine, RenditionProfile


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_video(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=#8b3f46:s=720x1280:r=30:d=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=1.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )


@pytest.mark.asyncio
async def test_renditions_preserve_master_and_emit_two_strict_silent_profiles(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    mobile = tmp_path / "mobile.mp4"
    desktop = tmp_path / "desktop.mp4"
    _source_video(source)
    source_hash = _sha256(source)
    engine = FfmpegRenditionEngine()

    mobile_facts = await engine.render(source, mobile, RenditionProfile.MOBILE_FULLSCREEN)
    desktop_facts = await engine.render(
        source,
        desktop,
        RenditionProfile.DESKTOP_FULLSCREEN,
    )

    assert _sha256(source) == source_hash
    assert (mobile_facts.width, mobile_facts.height) == (720, 1280)
    assert (desktop_facts.width, desktop_facts.height) == (1280, 720)
    for facts in (mobile_facts, desktop_facts):
        assert (facts.frame_rate_numerator, facts.frame_rate_denominator) == (25, 1)
        assert facts.video_codec == "h264"
        assert facts.has_audio is False
        assert 1150 <= facts.duration_ms <= 1250


@pytest.mark.asyncio
async def test_rendition_engine_rejects_overwriting_the_source_master(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    _source_video(source)
    source_hash = _sha256(source)

    with pytest.raises(ValueError, match="different paths"):
        await FfmpegRenditionEngine().render(
            source,
            source,
            RenditionProfile.MOBILE_FULLSCREEN,
        )

    assert _sha256(source) == source_hash
