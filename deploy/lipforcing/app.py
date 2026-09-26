from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from threading import Lock
from typing import Any
import uuid


JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TERMINAL_STATES = {"success", "failed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Settings:
    job_root: Path
    runtime_dir: Path
    model_python: Path
    runner: Path
    api_token: str
    max_video_bytes: int
    max_audio_bytes: int
    job_timeout_seconds: int
    max_pending_jobs: int = 4
    required_paths: tuple[Path, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        runtime = Path(os.environ.get("LIPFORCING_REMOTE_ROOT", "/root/lipsync-eval/lipforcing-eval"))
        required = os.environ.get("LIPFORCING_REQUIRED_PATHS", "").strip()
        required_paths = tuple(Path(item) for item in required.split(":") if item) or (
            runtime / os.environ.get("LIPFORCING_CKPT_PATH", "weights/lipforcing_14b.pth"),
            runtime / os.environ.get("LIPFORCING_VAE_PATH", "weights/Wan2.1-T2V-14B/Wan2.1_VAE.pth"),
            runtime / os.environ.get("LIPFORCING_WAV2VEC_PATH", "weights/wav2vec2-base-960h"),
            runtime / os.environ.get("LIPFORCING_MASK_PATH", "weights/mask.png"),
            runtime / os.environ.get("LIPFORCING_TEXT_EMBEDS_PATH", "weights/person-talking-text-emb.pt"),
        )
        return cls(
            job_root=Path(os.environ.get("LIPFORCING_SERVICE_JOB_ROOT", "/var/lib/openrealtime-lipforcing/jobs")),
            runtime_dir=runtime,
            model_python=Path(os.environ.get("LIPFORCING_REMOTE_PYTHON", "/root/lipsync-eval/venv-lipforcing/bin/python")),
            runner=Path(os.environ.get("LIPFORCING_RUNNER", "/opt/openrealtime-lipforcing-service/generate_lipforcing_talking.sh")),
            api_token=os.environ.get("LIPFORCING_API_TOKEN", "").strip(),
            max_video_bytes=int(os.environ.get("LIPFORCING_MAX_VIDEO_BYTES", str(100 * 1024 * 1024))),
            max_audio_bytes=int(os.environ.get("LIPFORCING_MAX_AUDIO_BYTES", str(20 * 1024 * 1024))),
            job_timeout_seconds=int(os.environ.get("LIPFORCING_JOB_TIMEOUT_SECONDS", "3600")),
            max_pending_jobs=int(os.environ.get("LIPFORCING_MAX_PENDING_JOBS", "4")),
            required_paths=required_paths,
        )


class JobManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.job_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lipforcing")
        self._lock = Lock()
        self._mark_interrupted_jobs_failed()

    def submit(self, client_job_id: str | None, source_video: bytes, reference_audio: bytes) -> dict[str, Any]:
        job_id = client_job_id or f"lipforcing-{uuid.uuid4()}"
        if not JOB_ID.fullmatch(job_id):
            raise ValueError("job id must use 1-128 ASCII letters, digits, dots, underscores or dashes")
        if not source_video or len(source_video) > self.settings.max_video_bytes:
            raise ValueError("source video size is invalid")
        if not reference_audio or len(reference_audio) > self.settings.max_audio_bytes:
            raise ValueError("reference audio size is invalid")
        job_dir = self.settings.job_root / job_id
        with self._lock:
            existing = self._load(job_id)
            if existing:
                return existing
            if self._pending_job_count() >= self.settings.max_pending_jobs:
                raise ValueError("GPU job queue is full")
            job_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
            self._write_private(job_dir / "source.mp4", source_video)
            self._write_private(job_dir / "reference.wav", reference_audio)
            now = utc_now()
            job: dict[str, Any] = {
                "id": job_id,
                "state": "queued",
                "created_at": now,
                "updated_at": now,
            }
            self._persist(job)
            self._executor.submit(self._run, job_id)
            return dict(job)

    def get(self, job_id: str) -> dict[str, Any]:
        self._validate_id(job_id)
        job = self._load(job_id)
        if not job:
            raise KeyError(job_id)
        return job

    def result_path(self, job_id: str) -> Path:
        job = self.get(job_id)
        result = self.settings.job_root / job_id / "output.mp4"
        if job["state"] != "success" or not result.is_file():
            raise FileNotFoundError(job_id)
        return result

    def readiness(self) -> tuple[bool, list[str]]:
        paths = (self.settings.runtime_dir, self.settings.model_python, self.settings.runner, *self.settings.required_paths)
        missing = [str(item) for item in paths if not item.exists()]
        return not missing, missing

    def _run(self, job_id: str) -> None:
        job_dir = self.settings.job_root / job_id
        job = self.get(job_id)
        job["state"] = "processing"
        job["updated_at"] = utc_now()
        self._persist(job)
        try:
            with (job_dir / "inference.log").open("wb") as log:
                subprocess.run(
                    ["bash", str(self.settings.runner), str(job_dir), str(self.settings.runtime_dir), str(self.settings.model_python)],
                    check=True,
                    cwd=self.settings.runtime_dir,
                    env=os.environ.copy(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=self.settings.job_timeout_seconds,
                )
            output = job_dir / "output.mp4"
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError("runner did not produce output.mp4")
            job["state"] = "success"
        except Exception as error:
            job["state"] = "failed"
            job["error"] = "Lip Forcing inference failed; inspect inference.log on the GPU host"
            with (job_dir / "service-error.log").open("w", encoding="utf-8") as handle:
                handle.write(f"{type(error).__name__}: {error}\n")
        job["updated_at"] = utc_now()
        self._persist(job)

    def _load(self, job_id: str) -> dict[str, Any] | None:
        target = self.settings.job_root / job_id / "job.json"
        try:
            value = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(value, dict) or value.get("id") != job_id:
            raise RuntimeError(f"invalid persisted job: {job_id}")
        return value

    def _pending_job_count(self) -> int:
        count = 0
        for target in self.settings.job_root.glob("*/job.json"):
            try:
                value = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(value, dict) and value.get("state") in {"queued", "processing"}:
                    count += 1
            except (OSError, json.JSONDecodeError):
                continue
        return count

    def _mark_interrupted_jobs_failed(self) -> None:
        for target in self.settings.job_root.glob("*/job.json"):
            try:
                value = json.loads(target.read_text(encoding="utf-8"))
                if not isinstance(value, dict) or value.get("state") not in {"queued", "processing"}:
                    continue
                value["state"] = "failed"
                value["error"] = "GPU service restarted while this job was running"
                value["updated_at"] = utc_now()
                self._persist(value)
            except (OSError, json.JSONDecodeError, KeyError):
                continue

    def _persist(self, job: dict[str, Any]) -> None:
        job_dir = self.settings.job_root / str(job["id"])
        job_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = job_dir / f"job.{uuid.uuid4()}.tmp"
        self._write_private(temporary, json.dumps(job, ensure_ascii=False, indent=2).encode("utf-8"))
        os.replace(temporary, job_dir / "job.json")

    @staticmethod
    def _write_private(path: Path, content: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)

    @staticmethod
    def _validate_id(job_id: str) -> None:
        if not JOB_ID.fullmatch(job_id):
            raise ValueError("invalid job id")


def create_app():
    from fastapi import FastAPI, File, Header, HTTPException, UploadFile
    from fastapi.responses import FileResponse, JSONResponse

    settings = Settings.from_env()
    manager = JobManager(settings)
    application = FastAPI(title="OpenRealtime Lip Forcing GPU Service", version="1.0.0")

    def authorize(authorization: str | None) -> None:
        expected = f"Bearer {settings.api_token}"
        if settings.api_token and (authorization is None or not secrets.compare_digest(authorization, expected)):
            raise HTTPException(status_code=401, detail="invalid bearer token")

    @application.get("/health")
    def health():
        ready, missing = manager.readiness()
        payload = {"status": "ok" if ready else "not_ready", "model": "lipforcing-14b", "missing": missing}
        return JSONResponse(payload, status_code=200 if ready else 503)

    @application.post("/v1/jobs", status_code=202)
    async def submit_job(
        source_video: UploadFile = File(...),
        reference_audio: UploadFile = File(...),
        x_job_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        authorize(authorization)
        try:
            video = await source_video.read(settings.max_video_bytes + 1)
            audio = await reference_audio.read(settings.max_audio_bytes + 1)
            return manager.submit(x_job_id, video, audio)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/v1/jobs/{job_id}")
    def job_status(job_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return manager.get(job_id)
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=404, detail="job not found") from error

    @application.get("/v1/jobs/{job_id}/result")
    def job_result(job_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return FileResponse(manager.result_path(job_id), media_type="video/mp4", filename=f"{job_id}.mp4")
        except (KeyError, ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=404, detail="job result not ready") from error

    return application
