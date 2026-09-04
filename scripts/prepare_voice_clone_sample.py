"""Prepare an authorized recording for Bailian voice-clone enrollment.

The output is a mono, 24 kHz, 16-bit PCM WAV capped at 60 seconds. The script
does not denoise, normalize, or otherwise alter vocal identity; recording
quality should be fixed at the source whenever possible.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

MAX_CLIP_SECONDS = 60.0
MIN_CLIP_SECONDS = 5.0
MAX_FILE_BYTES = 10 * 1024 * 1024
SUPPORTED_INPUT_SUFFIXES = {".wav", ".mp3", ".m4a", ".webm", ".ogg"}


@dataclass(frozen=True, slots=True)
class ClipPlan:
    input_path: Path
    output_path: Path
    start_s: float
    duration_s: float


def build_clip_plan(
    input_path: Path,
    output_path: Path,
    *,
    source_duration_s: float,
    start_s: float,
    duration_s: float,
    rights_confirmed: bool,
) -> ClipPlan:
    if not rights_confirmed:
        raise ValueError("voice rights must be explicitly confirmed")
    if input_path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        raise ValueError("input must be WAV, MP3, M4A, WebM, or OGG")
    if output_path.suffix.lower() != ".wav":
        raise ValueError("output must be a WAV file")
    if source_duration_s <= 0:
        raise ValueError("source audio duration must be positive")
    if start_s < 0 or start_s >= source_duration_s:
        raise ValueError("start must fall inside the source audio")
    if duration_s <= 0 or duration_s > MAX_CLIP_SECONDS:
        raise ValueError("duration must be greater than 0 and at most 60 seconds")
    actual_duration_s = min(duration_s, source_duration_s - start_s)
    if actual_duration_s < MIN_CLIP_SECONDS:
        raise ValueError("prepared audio must contain at least 5 seconds")
    return ClipPlan(
        input_path=input_path,
        output_path=output_path,
        start_s=start_s,
        duration_s=actual_duration_s,
    )


def build_ffmpeg_command(
    plan: ClipPlan,
    *,
    ffmpeg_bin: str,
    overwrite: bool,
) -> list[str]:
    return [
        ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
        "-ss",
        f"{plan.start_s:.3f}",
        "-i",
        str(plan.input_path),
        "-t",
        f"{plan.duration_s:.3f}",
        "-vn",
        "-map_metadata",
        "-1",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
        str(plan.output_path),
    ]


def _probe(path: Path, *, ffprobe_bin: str) -> dict[str, float | int]:
    completed = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = json.loads(completed.stdout)["format"]
    return {"duration": float(metadata["duration"]), "size": int(metadata["size"])}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="authorized source recording")
    parser.add_argument("output", type=Path, help="output .wav path")
    parser.add_argument("--start", type=float, default=0.0, help="start offset in seconds")
    parser.add_argument(
        "--duration",
        type=float,
        default=20.0,
        help="requested clip length, 0 < seconds <= 60 (default: 20)",
    )
    parser.add_argument("--force", action="store_true", help="overwrite an existing output")
    parser.add_argument(
        "--rights-confirmed",
        action="store_true",
        help="confirm consent or sufficient rights to clone this speaker's voice",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error(f"input file does not exist: {args.input}")
    if args.output.exists() and not args.force:
        parser.error(f"output already exists (use --force): {args.output}")
    ffmpeg_bin = shutil.which("ffmpeg")
    ffprobe_bin = shutil.which("ffprobe")
    if not ffmpeg_bin or not ffprobe_bin:
        parser.error("ffmpeg and ffprobe are required")

    source = _probe(args.input, ffprobe_bin=ffprobe_bin)
    try:
        plan = build_clip_plan(
            args.input,
            args.output,
            source_duration_s=float(source["duration"]),
            start_s=args.start,
            duration_s=args.duration,
            rights_confirmed=args.rights_confirmed,
        )
    except ValueError as error:
        parser.error(str(error))

    plan.output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        build_ffmpeg_command(plan, ffmpeg_bin=ffmpeg_bin, overwrite=args.force),
        check=True,
    )
    prepared = _probe(plan.output_path, ffprobe_bin=ffprobe_bin)
    if float(prepared["duration"]) > MAX_CLIP_SECONDS + 0.05:
        raise RuntimeError("prepared audio exceeds the 60-second provider limit")
    if int(prepared["size"]) > MAX_FILE_BYTES:
        raise RuntimeError("prepared audio exceeds the 10 MB provider limit")
    print(
        json.dumps(
            {
                "output": str(plan.output_path),
                "duration_seconds": round(float(prepared["duration"]), 3),
                "size_bytes": int(prepared["size"]),
                "sample_rate_hz": 24000,
                "channels": 1,
                "encoding": "pcm_s16le",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
