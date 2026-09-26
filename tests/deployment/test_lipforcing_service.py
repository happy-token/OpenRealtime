from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import time


MODULE_PATH = Path(__file__).parents[2] / "deploy" / "lipforcing" / "app.py"
SPEC = importlib.util.spec_from_file_location("lipforcing_service", MODULE_PATH)
assert SPEC and SPEC.loader
lipforcing_service = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lipforcing_service
SPEC.loader.exec_module(lipforcing_service)


def wait_for_terminal_state(manager, job_id: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job["state"] in {"success", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish")


def test_job_manager_runs_one_reproducible_job_and_persists_status(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    runner = tmp_path / "runner.sh"
    runner.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\ncp \"$1/source.mp4\" \"$1/output.mp4\"\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    settings = lipforcing_service.Settings(
        job_root=tmp_path / "jobs",
        runtime_dir=runtime,
        model_python=python,
        runner=runner,
        api_token="",
        max_video_bytes=1024,
        max_audio_bytes=1024,
        job_timeout_seconds=10,
    )
    manager = lipforcing_service.JobManager(settings)

    created = manager.submit("client-job-1", b"video", b"audio")
    repeated = manager.submit("client-job-1", b"different", b"different")
    terminal = wait_for_terminal_state(manager, created["id"])

    assert repeated["id"] == created["id"]
    assert terminal["state"] == "success"
    assert manager.result_path(created["id"]).read_bytes() == b"video"
    persisted = json.loads((settings.job_root / created["id"] / "job.json").read_text(encoding="utf-8"))
    assert persisted["state"] == "success"


def test_job_manager_rejects_unsafe_ids_and_oversized_uploads(tmp_path: Path):
    settings = lipforcing_service.Settings(
        job_root=tmp_path / "jobs",
        runtime_dir=tmp_path,
        model_python=tmp_path / "python",
        runner=tmp_path / "runner.sh",
        api_token="",
        max_video_bytes=4,
        max_audio_bytes=4,
        job_timeout_seconds=10,
    )
    manager = lipforcing_service.JobManager(settings)

    for job_id in ("../escape", "contains spaces", "x" * 129):
        try:
            manager.submit(job_id, b"a", b"b")
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe id was accepted: {job_id}")

    try:
        manager.submit("too-large", b"12345", b"1")
    except ValueError as error:
        assert "video" in str(error).lower()
    else:
        raise AssertionError("oversized video was accepted")


def test_job_manager_marks_interrupted_work_failed_on_restart(tmp_path: Path):
    job_dir = tmp_path / "jobs" / "interrupted-job"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(json.dumps({
        "id": "interrupted-job",
        "state": "processing",
        "created_at": "2026-09-25T00:00:00+00:00",
        "updated_at": "2026-09-25T00:00:00+00:00",
    }), encoding="utf-8")
    settings = lipforcing_service.Settings(
        job_root=tmp_path / "jobs",
        runtime_dir=tmp_path,
        model_python=tmp_path / "python",
        runner=tmp_path / "runner.sh",
        api_token="",
        max_video_bytes=4,
        max_audio_bytes=4,
        job_timeout_seconds=10,
    )

    manager = lipforcing_service.JobManager(settings)

    assert manager.get("interrupted-job")["state"] == "failed"
    assert "restarted" in manager.get("interrupted-job")["error"]
