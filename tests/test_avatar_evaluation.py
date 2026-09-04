import csv
import hashlib
import json
import math
from pathlib import Path

import pytest

from scripts import avatar_evaluation
from scripts.avatar_evaluation import (
    BENCHMARK_FIELDS,
    BenchmarkRecord,
    StaticBaseVideoSpec,
    append_benchmark_record,
    build_static_base_video_command,
    initialize_campaign,
    main,
    render_static_base_video,
)


def test_static_base_video_command_produces_normalized_silent_avatar_asset() -> None:
    spec = StaticBaseVideoSpec(
        portrait_path=Path("portrait.jpg"),
        output_path=Path("runs/static/static-base.mp4"),
        duration_seconds=5.0,
        width=720,
        height=1280,
        fps=25,
    )

    command = build_static_base_video_command(
        spec,
        ffmpeg_bin="/opt/homebrew/bin/ffmpeg",
        overwrite=True,
    )

    assert command[:2] == ["/opt/homebrew/bin/ffmpeg", "-nostdin"]
    assert command[command.index("-loop") + 1] == "1"
    assert command[command.index("-t") + 1] == "5.000"
    assert command[command.index("-r") + 1] == "25"
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert "fps=25" in command[command.index("-vf") + 1]
    assert (
        "scale=720:1280:force_original_aspect_ratio=decrease" in command[command.index("-vf") + 1]
    )
    assert "out_range=tv" in command[command.index("-vf") + 1]
    assert "format=yuv420p" in command[command.index("-vf") + 1]
    assert command[command.index("-color_range") + 1] == "tv"
    assert "-an" in command
    assert command[-1] == "runs/static/static-base.mp4"


def test_initialize_campaign_creates_shared_manifest_and_benchmark(tmp_path: Path) -> None:
    portrait = tmp_path / "portrait.jpg"
    portrait.write_bytes(b"portrait")
    workspace = tmp_path / "campaign"

    manifest_path, benchmark_path = initialize_campaign(
        workspace,
        campaign_id="avatar-eval-2026-08-22",
        portrait_path=portrait,
        usage_scope="internal_evaluation",
        rights_confirmed=True,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["campaign_id"] == "avatar-eval-2026-08-22"
    assert manifest["inputs"]["portrait"] == {
        "path": "inputs/portrait.jpg",
        "sha256": hashlib.sha256(b"portrait").hexdigest(),
        "size_bytes": len(b"portrait"),
    }
    assert (workspace / "inputs" / "portrait.jpg").read_bytes() == b"portrait"
    assert manifest["usage_scope"] == "internal_evaluation"
    assert manifest["rights"] == {
        "internal_processing_confirmed": True,
        "public_distribution_confirmed": False,
    }
    assert manifest["target"] == {
        "width": 720,
        "height": 1280,
        "fps": 25,
        "video_codec": "h264",
        "audio_sample_rate_hz": 24000,
    }
    assert (workspace / "runs").is_dir()
    assert (workspace / "artifacts").is_dir()

    with benchmark_path.open(newline="", encoding="utf-8") as benchmark_file:
        assert next(csv.reader(benchmark_file)) == BENCHMARK_FIELDS


def test_initialize_campaign_rejects_unconfirmed_portrait_rights(tmp_path: Path) -> None:
    portrait = tmp_path / "portrait.jpg"
    portrait.write_bytes(b"portrait")

    try:
        initialize_campaign(
            tmp_path / "campaign",
            campaign_id="avatar-eval",
            portrait_path=portrait,
            usage_scope="internal_evaluation",
            rights_confirmed=False,
        )
    except ValueError as error:
        assert "rights" in str(error).lower()
    else:
        raise AssertionError("unconfirmed portrait rights must be rejected")


def test_initialize_campaign_rejects_reusing_nonempty_workspace(tmp_path: Path) -> None:
    portrait = tmp_path / "portrait.jpg"
    portrait.write_bytes(b"portrait")
    workspace = tmp_path / "campaign"
    workspace.mkdir()
    (workspace / "benchmark.csv").write_text("old result", encoding="utf-8")

    with pytest.raises(FileExistsError, match="non-empty"):
        initialize_campaign(
            workspace,
            campaign_id="new-campaign",
            portrait_path=portrait,
            usage_scope="internal_evaluation",
            rights_confirmed=True,
        )


def test_render_static_base_video_creates_parent_and_runs_ffmpeg(tmp_path: Path) -> None:
    portrait = tmp_path / "portrait.jpg"
    portrait.write_bytes(b"portrait")
    output = tmp_path / "runs" / "static" / "base.mp4"
    calls: list[tuple[list[str], bool]] = []

    def fake_runner(command: list[str], *, check: bool) -> None:
        calls.append((command, check))

    command = render_static_base_video(
        StaticBaseVideoSpec(portrait_path=portrait, output_path=output),
        ffmpeg_bin="ffmpeg",
        overwrite=True,
        runner=fake_runner,
    )

    assert output.parent.is_dir()
    assert calls == [(command, True)]
    assert command[-1] == str(output)


def test_main_static_command_renders_requested_asset(tmp_path: Path) -> None:
    portrait = tmp_path / "portrait.jpg"
    portrait.write_bytes(b"portrait")
    output = tmp_path / "base.mp4"
    calls: list[list[str]] = []

    exit_code = main(
        [
            "static",
            str(portrait),
            str(output),
            "--duration",
            "8",
            "--force",
        ],
        runner=lambda command, *, check: calls.append(command),
    )

    assert exit_code == 0
    assert calls[0][calls[0].index("-t") + 1] == "8.000"
    assert "-y" in calls[0]


def test_append_benchmark_record_calculates_rtf(tmp_path: Path) -> None:
    portrait = tmp_path / "portrait.jpg"
    portrait.write_bytes(b"portrait")
    _, benchmark_path = initialize_campaign(
        tmp_path / "campaign",
        campaign_id="avatar-eval",
        portrait_path=portrait,
        usage_scope="internal_evaluation",
        rights_confirmed=True,
    )

    append_benchmark_record(
        benchmark_path,
        BenchmarkRecord(
            run_id="static-001",
            provider="ffmpeg-static",
            artifact_id="static-base",
            mode="offline",
            status="ready",
            duration_seconds=5.0,
            render_seconds=0.5,
            average_fps=25.0,
            recorded_at="2026-08-23T00:00:00+08:00",
            notes="normalized baseline",
        ),
    )

    with benchmark_path.open(newline="", encoding="utf-8") as benchmark_file:
        rows = list(csv.DictReader(benchmark_file))
    assert rows == [
        {
            "run_id": "static-001",
            "provider": "ffmpeg-static",
            "artifact_id": "static-base",
            "mode": "offline",
            "status": "ready",
            "recorded_at": "2026-08-23T00:00:00+08:00",
            "duration_seconds": "5.000",
            "render_seconds": "0.500",
            "rtf": "0.100",
            "performance_metric_kind": "compute",
            "average_fps": "25.000",
            "first_frame_ms": "",
            "av_drift_ms": "",
            "stable_minutes": "",
            "queue_growth": "",
            "interrupt_p95_ms": "",
            "second_half_fps": "",
            "thermal_state": "",
            "notes": "normalized baseline",
        }
    ]
    result = json.loads(
        (benchmark_path.parent / "results" / "static-001.json").read_text(encoding="utf-8")
    )
    assert result == {
        "run_id": "static-001",
        "provider": "ffmpeg-static",
        "artifact_id": "static-base",
        "mode": "offline",
        "status": "ready",
        "duration_seconds": 5.0,
        "render_seconds": 0.5,
        "rtf": 0.1,
        "performance_metric_kind": "compute",
        "average_fps": 25.0,
        "first_frame_ms": None,
        "av_drift_ms": None,
        "stable_minutes": None,
        "queue_growth": None,
        "interrupt_p95_ms": None,
        "second_half_fps": None,
        "thermal_state": "",
        "recorded_at": "2026-08-23T00:00:00+08:00",
        "notes": "normalized baseline",
    }


@pytest.mark.parametrize(
    "spec",
    [
        StaticBaseVideoSpec(Path("portrait.jpg"), Path("base.mp4"), duration_seconds=0),
        StaticBaseVideoSpec(Path("portrait.jpg"), Path("base.mp4"), duration_seconds=math.nan),
        StaticBaseVideoSpec(Path("portrait.jpg"), Path("base.mp4"), width=721),
        StaticBaseVideoSpec(Path("portrait.jpg"), Path("base.mp4"), height=-2),
        StaticBaseVideoSpec(Path("portrait.jpg"), Path("base.mp4"), fps=0),
    ],
)
def test_static_base_video_command_rejects_invalid_specs(spec: StaticBaseVideoSpec) -> None:
    with pytest.raises(ValueError):
        build_static_base_video_command(spec)


@pytest.mark.parametrize("render_seconds", [-1.0, math.nan, math.inf])
def test_append_benchmark_record_rejects_invalid_metrics(
    tmp_path: Path,
    render_seconds: float,
) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    benchmark_path.write_text(",".join(BENCHMARK_FIELDS) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        append_benchmark_record(
            benchmark_path,
            BenchmarkRecord(
                run_id="invalid",
                provider="ffmpeg-static",
                artifact_id="static-base",
                mode="offline",
                status="ready",
                duration_seconds=1,
                render_seconds=render_seconds,
            ),
        )


def test_append_benchmark_record_rejects_unsafe_provider(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    benchmark_path.write_text(",".join(BENCHMARK_FIELDS) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="provider"):
        append_benchmark_record(
            benchmark_path,
            BenchmarkRecord(
                run_id="unsafe",
                provider="__proto__",
                artifact_id="static-base",
                mode="offline",
                status="ready",
                duration_seconds=1,
                render_seconds=1,
            ),
        )


def test_append_benchmark_record_escapes_spreadsheet_formulas(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    benchmark_path.write_text(",".join(BENCHMARK_FIELDS) + "\n", encoding="utf-8")

    append_benchmark_record(
        benchmark_path,
        BenchmarkRecord(
            run_id="safe-run",
            provider="ffmpeg-static",
            artifact_id="static-base",
            mode="offline",
            status="ready",
            duration_seconds=1,
            render_seconds=1,
            notes="\t =unsafe",
        ),
    )

    with benchmark_path.open(newline="", encoding="utf-8") as benchmark_file:
        row = next(csv.DictReader(benchmark_file))
    assert row["run_id"] == "safe-run"
    assert row["notes"] == "'\t =unsafe"


def test_append_benchmark_record_rejects_unknown_csv_schema(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    benchmark_path.write_text("wrong,header\n", encoding="utf-8")

    with pytest.raises(ValueError, match="schema"):
        append_benchmark_record(
            benchmark_path,
            BenchmarkRecord(
                run_id="run",
                provider="ffmpeg-static",
                artifact_id="static-base",
                mode="offline",
                status="ready",
                duration_seconds=1,
                render_seconds=1,
            ),
        )


def test_append_benchmark_record_rejects_malformed_canonical_run(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    benchmark_path.write_text(",".join(BENCHMARK_FIELDS) + "\n", encoding="utf-8")
    results_path = tmp_path / "results"
    results_path.mkdir()
    (results_path / "broken.json").write_text("[1]", encoding="utf-8")

    with pytest.raises(ValueError, match="broken.json"):
        append_benchmark_record(
            benchmark_path,
            BenchmarkRecord(
                run_id="run",
                provider="ffmpeg-static",
                artifact_id="static-base",
                mode="offline",
                status="ready",
                duration_seconds=1,
                render_seconds=1,
            ),
        )


def test_append_benchmark_record_is_idempotent_and_rebuilds_csv(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    benchmark_path.write_text(",".join(BENCHMARK_FIELDS) + "\n", encoding="utf-8")
    record = BenchmarkRecord(
        run_id="static-001",
        provider="ffmpeg-static",
        artifact_id="static-base",
        mode="offline",
        status="ready",
        duration_seconds=5,
        render_seconds=0.5,
        recorded_at="2026-08-23T00:00:00+08:00",
    )

    append_benchmark_record(benchmark_path, record)
    benchmark_path.write_text(",".join(BENCHMARK_FIELDS) + "\n", encoding="utf-8")
    append_benchmark_record(benchmark_path, record)

    with benchmark_path.open(newline="", encoding="utf-8") as benchmark_file:
        assert [row["run_id"] for row in csv.DictReader(benchmark_file)] == ["static-001"]


def test_append_benchmark_record_rolls_back_new_canonical_if_csv_rebuild_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    benchmark_path.write_text(",".join(BENCHMARK_FIELDS) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        avatar_evaluation,
        "_rebuild_benchmark_csv",
        lambda *args: (_ for _ in ()).throw(RuntimeError("csv failed")),
    )

    with pytest.raises(RuntimeError, match="csv failed"):
        append_benchmark_record(
            benchmark_path,
            BenchmarkRecord(
                run_id="transaction-test",
                provider="ffmpeg-static",
                artifact_id="static-base",
                mode="offline",
                status="ready",
                duration_seconds=1,
                render_seconds=0.5,
            ),
        )

    assert not (tmp_path / "results" / "transaction-test.json").exists()


def test_append_benchmark_record_rejects_semantically_invalid_canonical_run(
    tmp_path: Path,
) -> None:
    benchmark_path = tmp_path / "benchmark.csv"
    benchmark_path.write_text(",".join(BENCHMARK_FIELDS) + "\n", encoding="utf-8")
    results_path = tmp_path / "results"
    results_path.mkdir()
    invalid = {
        "run_id": "broken",
        "provider": "ffmpeg-static",
        "artifact_id": "static-base",
        "mode": "bogus",
        "status": "ready",
        "duration_seconds": 0,
        "render_seconds": -2,
        "rtf": 999,
        "average_fps": True,
        "first_frame_ms": None,
        "av_drift_ms": None,
        "stable_minutes": None,
        "queue_growth": None,
        "interrupt_p95_ms": None,
        "second_half_fps": None,
        "thermal_state": "lava",
        "recorded_at": "not-a-date",
        "notes": "invalid",
    }
    (results_path / "broken.json").write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(ValueError, match="broken.json"):
        append_benchmark_record(
            benchmark_path,
            BenchmarkRecord(
                run_id="run",
                provider="ffmpeg-static",
                artifact_id="static-base",
                mode="offline",
                status="ready",
                duration_seconds=1,
                render_seconds=1,
            ),
        )
