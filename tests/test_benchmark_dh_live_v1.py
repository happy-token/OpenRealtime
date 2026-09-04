import json
from pathlib import Path

import pytest

from scripts.benchmark_dh_live_v1 import (
    build_dh_live_v1_normalize_command,
    run_dh_live_v1_benchmark,
)
from scripts.dh_live_v1_provider import RENDERER_FILES


def test_normalize_command_preserves_full_height_canvas() -> None:
    command = build_dh_live_v1_normalize_command(
        raw_video=Path("capture.webm"),
        audio=Path("speech.wav"),
        output=Path("result.mp4"),
        duration_seconds=3.12,
        ffmpeg_bin="/opt/ffmpeg",
    )

    assert command[0] == "/opt/ffmpeg"
    filter_graph = command[command.index("-vf") + 1]
    assert "fps=25,scale=720:1280:flags=lanczos" in filter_graph
    assert "pad=720:1280" not in filter_graph
    assert command[-1] == "result.mp4"


def test_run_rejects_rights_and_unsafe_identity_before_external_tools(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    common = {
        "bundle": tmp_path / "bundle",
        "campaign": campaign,
        "audio_path": campaign / "input.wav",
        "output_path": campaign / "runs/custom/unsafe.mp4",
    }
    with pytest.raises(ValueError, match="rights"):
        run_dh_live_v1_benchmark(
            **common,
            run_id="unsafe",
            rights_confirmed=False,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="run_id"):
        run_dh_live_v1_benchmark(
            **common,
            run_id="../unsafe",
            rights_confirmed=True,  # type: ignore[arg-type]
        )


def test_schema2_campaign_evidence_pins_renderer_and_avatar_files() -> None:
    evidence_path = (
        Path(__file__).parents[1]
        / "research-assets/avatar-evaluation/2026-08-22/runs/dh-live-v1-custom/"
        "dh-live-mini-v1-custom-003.evidence.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert evidence["schema_version"] == 2
    assert evidence["supersedes"] == "dh-live-mini-v1-custom-002"
    assert evidence["renderer_files"] == {
        relative.as_posix(): {"size_bytes": size, "sha256": digest}
        for relative, (size, digest) in RENDERER_FILES.items()
    }
    assert evidence["avatar"]["files"] == {
        "assets/01.mp4": {
            "size_bytes": 64_896,
            "sha256": "993ac482a401849d8dfcce6195b6e253d77e650683934d1282fcfde19b9e0794",
        },
        "assets/combined_data.json.gz": {
            "size_bytes": 86_706,
            "sha256": "4637baa85694b2155783452994906668e5a1c250af284dc04f56ab9f3af18bfc",
        },
    }
