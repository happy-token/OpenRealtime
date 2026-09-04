"""Server-side media inspection for candidate provenance."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from server.avatar_assets.models import MediaFacts


class MediaProbe(Protocol):
    async def probe(self, data: bytes, media_type: str) -> MediaFacts: ...


class FfprobeMediaProbe:
    def __init__(self, *, ffprobe: str | None = None, timeout_seconds: float = 30.0) -> None:
        self._ffprobe = ffprobe or shutil.which("ffprobe") or ""
        if not self._ffprobe:
            raise RuntimeError("FFprobe executable is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds

    async def probe(self, data: bytes, media_type: str) -> MediaFacts:
        suffix = {
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/webm": ".webm",
        }.get(media_type)
        if suffix is None:
            raise ValueError("candidate artifact must use a supported video media type")
        with tempfile.TemporaryDirectory(prefix="openrealtime-probe-") as directory:
            workspace = Path(directory)
            os.chmod(workspace, 0o700)
            source = workspace / f"candidate{suffix}"
            source.write_bytes(data)
            os.chmod(source, 0o600)
            return await asyncio.to_thread(self._probe_path, source, data, media_type)

    def _probe_path(self, path: Path, data: bytes, media_type: str) -> MediaFacts:
        try:
            completed = subprocess.run(
                [
                    self._ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,codec_name,width,height,r_frame_rate",
                    "-show_entries",
                    "format=duration,size,format_name",
                    "-of",
                    "json",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise ValueError("candidate artifact is not a decodable video") from error
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValueError("FFprobe returned invalid media metadata") from error
        observed_formats = set(payload.get("format", {}).get("format_name", "").split(","))
        allowed_formats = {
            "video/mp4": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
            "video/quicktime": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
            "video/webm": {"matroska", "webm"},
        }[media_type]
        if not observed_formats.intersection(allowed_formats):
            raise ValueError("candidate container does not match its declared media type")
        streams = payload.get("streams", [])
        video = next(
            (stream for stream in streams if stream.get("codec_type") == "video"),
            None,
        )
        if video is None:
            raise ValueError("candidate artifact has no video stream")
        numerator_text, denominator_text = video["r_frame_rate"].split("/", 1)
        audio = next(
            (stream for stream in streams if stream.get("codec_type") == "audio"),
            None,
        )
        try:
            return MediaFacts(
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                duration_ms=round(float(payload["format"]["duration"]) * 1000),
                width=int(video["width"]),
                height=int(video["height"]),
                frame_rate_numerator=int(numerator_text),
                frame_rate_denominator=int(denominator_text),
                video_codec=video["codec_name"],
                has_audio=audio is not None,
                audio_codec=audio.get("codec_name") if audio is not None else None,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("candidate video metadata is incomplete or invalid") from error
