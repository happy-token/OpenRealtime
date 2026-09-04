"""Verify the pinned same-input lip-sync comparison and its media evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import wave
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = PROJECT_ROOT / "research-assets/avatar-evaluation/2026-08-22"
MANIFEST_PATH = CAMPAIGN_ROOT / "runs/lip-sync-comparison/lip-sync-comparison-001.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_media(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error", "-count_frames",
        "-show_entries", (
            "stream=codec_type,codec_name,duration,nb_read_frames,width,height,"
            "r_frame_rate,sample_rate,channels"
        ),
        "-show_entries", "format=duration", "-of", "json", str(path),
    ]
    return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)


def assert_silence_tail(audio_path: Path, start_seconds: float) -> None:
    with wave.open(str(audio_path), "rb") as source:
        assert source.getsampwidth() == 2
        assert source.getnchannels() == 1
        assert source.getframerate() == 16000
        source.setpos(round(start_seconds * source.getframerate()))
        silence = source.readframes(source.getnframes() - source.tell())
    assert silence and not any(silence), "fixed WAV tail is not digital silence"


def verify() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    motion_base = manifest["motion_base"]
    fixed_audio = manifest["fixed_audio"]
    runs = {run["provider"]: run for run in manifest["runs"]}

    for item in (motion_base, fixed_audio):
        path = CAMPAIGN_ROOT / item["path"]
        assert path.stat().st_size == item["size_bytes"], path
        assert sha256(path) == item["sha256"], path
    assert_silence_tail(CAMPAIGN_ROOT / fixed_audio["path"], fixed_audio["speech_seconds"])

    assert runs["dh-live-mini-v1"]["avatar_source_video_sha256"] == motion_base["sha256"]
    dh_evidence_path = CAMPAIGN_ROOT / runs["dh-live-mini-v1"]["evidence_path"]
    dh_evidence = json.loads(dh_evidence_path.read_text())
    assert dh_evidence["avatar"]["source_video"]["sha256"] == motion_base["sha256"]
    assert dh_evidence["input"]["sha256"] == fixed_audio["sha256"]

    for run in runs.values():
        for output_kind in ("raw_output", "preview_output"):
            output = run[output_kind]
            path = CAMPAIGN_ROOT / output["path"]
            assert path.stat().st_size == output["size_bytes"], path
            assert sha256(path) == output["sha256"], path
        raw = run["raw_output"]
        raw_probe = probe_media(CAMPAIGN_ROOT / raw["path"])
        raw_video = next(stream for stream in raw_probe["streams"] if stream["codec_type"] == "video")
        assert float(raw_video["duration"]) == raw["video_duration_seconds"]
        assert int(raw_video["nb_read_frames"]) == raw["video_frame_count"]
        assert float(raw_probe["format"]["duration"]) == raw["container_duration_seconds"]

        preview = run["preview_output"]
        preview_probe = probe_media(CAMPAIGN_ROOT / preview["path"])
        video = next(stream for stream in preview_probe["streams"] if stream["codec_type"] == "video")
        audio = next(stream for stream in preview_probe["streams"] if stream["codec_type"] == "audio")
        assert video["codec_name"] == preview["video_codec"]
        assert int(video["width"]) == preview["width"]
        assert int(video["height"]) == preview["height"]
        assert video["r_frame_rate"] == "25/1"
        assert int(video["nb_read_frames"]) == 125
        assert float(video["duration"]) == preview["duration_seconds"]
        assert audio["codec_name"] == preview["audio_codec"]
        assert int(audio["sample_rate"]) == preview["audio_sample_rate_hz"]
        assert int(audio["channels"]) == preview["audio_channels"]
        assert float(audio["duration"]) == preview["audio_duration_seconds"]
        assert float(preview_probe["format"]["duration"]) == preview["duration_seconds"]

    assert dh_evidence["artifact"]["sha256"] == runs["dh-live-mini-v1"]["raw_output"]["sha256"]


if __name__ == "__main__":
    verify()
    print(f"verified: {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")
