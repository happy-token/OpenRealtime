from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path

import pytest

from server.avatar_assets import FfprobeMediaProbe


@pytest.mark.asyncio
async def test_ffprobe_rejects_arbitrary_bytes() -> None:
    with pytest.raises(ValueError, match="decodable video"):
        await FfprobeMediaProbe().probe(b"not-a-video", "video/mp4")


@pytest.mark.asyncio
async def test_ffprobe_derives_authoritative_webm_facts(tmp_path: Path) -> None:
    path = tmp_path / "candidate.webm"
    await asyncio.to_thread(
        subprocess.run,
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=#8b3f46:s=640x960:r=24:d=1",
            "-c:v",
            "libvpx-vp9",
            str(path),
        ],
        check=True,
    )
    data = path.read_bytes()

    facts = await FfprobeMediaProbe().probe(data, "video/webm")

    assert facts.size_bytes == len(data)
    assert facts.sha256 == hashlib.sha256(data).hexdigest()
    assert (facts.width, facts.height) == (640, 960)
    assert (facts.frame_rate_numerator, facts.frame_rate_denominator) == (24, 1)
    assert facts.video_codec == "vp9"
    assert facts.has_audio is False

    with pytest.raises(ValueError, match="container"):
        await FfprobeMediaProbe().probe(data, "video/mp4")
