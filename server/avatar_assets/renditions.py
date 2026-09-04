"""FFprobe/FFmpeg rendition engine preserving the immutable Source Master."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from enum import StrEnum
from pathlib import Path

from server.avatar_assets.models import MediaFacts


class RenditionProfile(StrEnum):
    MOBILE_FULLSCREEN = "mobile_fullscreen"
    DESKTOP_FULLSCREEN = "desktop_fullscreen"

    @property
    def dimensions(self) -> tuple[int, int]:
        if self is RenditionProfile.MOBILE_FULLSCREEN:
            return 720, 1280
        return 1280, 720


def validate_rendition_media(profile: RenditionProfile, media: MediaFacts) -> None:
    if (media.width, media.height) != profile.dimensions:
        raise ValueError("rendition dimensions do not match its profile")
    if (media.frame_rate_numerator, media.frame_rate_denominator) != (25, 1):
        raise ValueError("rendition frame rate must be 25fps")
    if media.video_codec != "h264" or media.has_audio:
        raise ValueError("rendition must be silent H.264")


class FfmpegRenditionEngine:
    def __init__(
        self,
        *,
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._ffmpeg = ffmpeg or shutil.which("ffmpeg") or ""
        self._ffprobe = ffprobe or shutil.which("ffprobe") or ""
        if not self._ffmpeg or not self._ffprobe:
            raise RuntimeError("FFmpeg and FFprobe executables are required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds

    async def render(
        self,
        source: Path,
        output: Path,
        profile: RenditionProfile,
    ) -> MediaFacts:
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.resolve() == output.resolve() or (
            output.exists() and os.path.samefile(source, output)
        ):
            raise ValueError("rendition source and output must be different paths")
        output.parent.mkdir(parents=True, exist_ok=True)
        width, height = profile.dimensions
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp.mp4")
        video_filter = (
            "[0:v:0]split=2[background][foreground];"
            f"[background]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=20:10[blurred];"
            f"[foreground]scale={width}:{height}:force_original_aspect_ratio=decrease[subject];"
            "[blurred][subject]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=25[video]"
        )
        command = [
            self._ffmpeg,
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-filter_complex",
            video_filter,
            "-map",
            "[video]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
        try:
            await asyncio.to_thread(self._run, command)
            facts = await asyncio.to_thread(self._probe, temporary)
            if (facts.width, facts.height) != (width, height):
                raise RuntimeError("rendition dimensions do not match the requested profile")
            if (
                facts.frame_rate_numerator,
                facts.frame_rate_denominator,
            ) != (25, 1):
                raise RuntimeError("rendition frame rate is not 25fps")
            if facts.video_codec != "h264" or facts.has_audio:
                raise RuntimeError("rendition must be H.264 and silent")
            os.replace(temporary, output)
            return facts
        finally:
            temporary.unlink(missing_ok=True)

    def _run(self, command: list[str]) -> None:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=self._timeout_seconds,
        )

    def _probe(self, path: Path) -> MediaFacts:
        completed = subprocess.run(
            [
                self._ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,r_frame_rate",
                "-show_entries",
                "format=duration,size",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(completed.stdout)
        video = next(
            (stream for stream in payload["streams"] if stream["codec_type"] == "video"),
            None,
        )
        if video is None:
            raise RuntimeError("rendition has no video stream")
        numerator_text, denominator_text = video["r_frame_rate"].split("/", 1)
        data = path.read_bytes()
        return MediaFacts(
            size_bytes=int(payload["format"]["size"]),
            sha256=hashlib.sha256(data).hexdigest(),
            duration_ms=round(float(payload["format"]["duration"]) * 1000),
            width=int(video["width"]),
            height=int(video["height"]),
            frame_rate_numerator=int(numerator_text),
            frame_rate_denominator=int(denominator_text),
            video_codec=video["codec_name"],
            has_audio=any(stream["codec_type"] == "audio" for stream in payload["streams"]),
        )
