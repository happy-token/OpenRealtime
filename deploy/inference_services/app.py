"""Small HTTP job service shared by MuseTalk, Wav2Lip and LivePortrait.

The model runtimes and their weights live outside this package.  A deployment
selects exactly one model with MODEL_SERVICE_KIND.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from threading import Lock
import uuid


KINDS = {"musetalk", "wav2lip", "liveportrait"}
JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_REFERENCE_BYTES = 20 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Settings:
    kind: str
    runtime_root: Path
    job_root: Path
    token: str
    timeout_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        kind = os.environ.get("MODEL_SERVICE_KIND", "").strip().lower()
        if kind not in KINDS:
            raise ValueError(f"MODEL_SERVICE_KIND must be one of {', '.join(sorted(KINDS))}")
        return cls(
            kind=kind,
            runtime_root=Path(os.environ.get("MODEL_RUNTIME_ROOT", f"models/{kind}")).resolve(),
            job_root=Path(os.environ.get("MODEL_SERVICE_JOB_ROOT", f"data/model-jobs/{kind}")).resolve(),
            token=os.environ.get("MODEL_SERVICE_API_TOKEN", "").strip(),
            timeout_seconds=int(os.environ.get("MODEL_SERVICE_TIMEOUT_SECONDS", "1800")),
        )


class JobManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.job_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=settings.kind)
        self._fail_interrupted_jobs()

    def readiness(self) -> tuple[bool, list[str]]:
        runtime = self.settings.runtime_root
        required = [runtime / "repository", runtime / ".venv/bin/python"]
        if self.settings.kind == "musetalk":
            required.extend([
                runtime / "repository/scripts/inference.py",
                runtime / "repository/models/musetalkV15/unet.pth",
            ])
        else:
            required.append(runtime / "repository/inference.py")
        missing = [str(path) for path in required if not path.exists()]
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            missing.append("ffmpeg/ffprobe")
        if self.settings.kind == "musetalk" and shutil.which("flock") is None:
            missing.append("flock")
        if not missing and self.settings.kind == "musetalk":
            try:
                probe = subprocess.run(
                    [str(runtime / ".venv/bin/python"), "-c",
                     "import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)"],
                    capture_output=True, timeout=60, check=False,
                )
                if probe.returncode != 0:
                    missing.append("CUDA GPU not available in MuseTalk runtime")
            except (OSError, subprocess.TimeoutExpired):
                missing.append("MuseTalk CUDA probe failed")
        if not missing and self.settings.kind in {"wav2lip", "liveportrait"}:
            provider = Path(__file__).resolve().parents[2] / "scripts" / f"{self.settings.kind}_provider.py"
            try:
                result = subprocess.run(
                    [sys.executable, str(provider), "diagnose", "--runtime-root", str(runtime)],
                    capture_output=True, text=True, timeout=180, check=False,
                )
                diagnostic = json.loads(result.stdout)
                if result.returncode != 0 or not diagnostic.get("ready"):
                    missing.extend(str(issue) for issue in diagnostic.get("issues", []))
                    if not missing:
                        missing.append("model diagnostic failed")
            except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
                missing.append("model diagnostic failed")
        return not missing, missing

    def submit(self, job_id: str | None, source: bytes, reference: bytes, *, rights_confirmed: bool,
               usage_scope: str = "internal_evaluation", source_extension: str = ".png",
               reference_extension: str = ".mp4", config_json: str | None = None) -> dict:
        if not rights_confirmed:
            raise ValueError("source, motion-video and voice rights must be confirmed")
        if self.settings.kind == "wav2lip" and usage_scope not in {"internal_evaluation", "research", "personal"}:
            raise ValueError("standard Wav2Lip is restricted to non-commercial usage")
        if not source or len(source) > MAX_SOURCE_BYTES or not reference or len(reference) > MAX_REFERENCE_BYTES:
            raise ValueError("invalid source or reference size")
        if self.settings.kind == "liveportrait":
            if source_extension not in {".png", ".jpg", ".jpeg", ".webp"} or reference_extension not in {".mp4", ".webm", ".mov"}:
                raise ValueError("unsupported LivePortrait media extension")
            if config_json is not None:
                if len(config_json.encode()) > 64 * 1024 or not isinstance(json.loads(config_json), dict):
                    raise ValueError("invalid LivePortrait config")
        ready, missing = self.readiness()
        if not ready:
            raise RuntimeError("model runtime is not ready: " + "; ".join(missing))
        identifier = job_id or f"{self.settings.kind}-{uuid.uuid4()}"
        if not JOB_ID.fullmatch(identifier):
            raise ValueError("invalid job id")
        directory = self.settings.job_root / identifier
        with self._lock:
            existing = self._load(identifier)
            if existing is not None:
                return existing
            if self._pending_count() >= 4:
                raise RuntimeError("model job queue is full")
            directory.mkdir(mode=0o700)
            source_name = f"source{source_extension}" if self.settings.kind == "liveportrait" else "source.mp4"
            reference_name = f"driving{reference_extension}" if self.settings.kind == "liveportrait" else "reference.wav"
            self._write_private(directory / source_name, source)
            self._write_private(directory / reference_name, reference)
            if self.settings.kind == "liveportrait" and config_json is not None:
                self._write_private(directory / "config.json", config_json.encode())
            job = {"id": identifier, "state": "queued", "model": self.settings.kind,
                   "created_at": now(), "updated_at": now(), "usage_scope": usage_scope}
            self._persist(job)
            self._executor.submit(self._run, identifier)
            return job.copy()

    def get(self, identifier: str) -> dict:
        if not JOB_ID.fullmatch(identifier):
            raise KeyError(identifier)
        job = self._load(identifier)
        if job is None:
            raise KeyError(identifier)
        return job

    def result_path(self, identifier: str) -> Path:
        job = self.get(identifier)
        result = self.settings.job_root / identifier / "output.mp4"
        if job["state"] != "success" or not result.is_file():
            raise FileNotFoundError(identifier)
        return result

    def _run(self, identifier: str) -> None:
        job = self.get(identifier)
        job.update(state="processing", updated_at=now())
        self._persist(job)
        directory = self.settings.job_root / identifier
        try:
            command = self._command(directory, job["usage_scope"])
            with (directory / "inference.log").open("wb") as output:
                subprocess.run(command, check=True, stdout=output, stderr=subprocess.STDOUT,
                               timeout=self.settings.timeout_seconds)
            if self.settings.kind == "liveportrait":
                result_dir = directory / "rendered"
                results = list(result_dir.glob("*.mp4"))
                if len(results) != 1:
                    raise RuntimeError("LivePortrait did not produce one MP4")
                shutil.copyfile(results[0], directory / "output.mp4")
            result = directory / "output.mp4"
            if not result.is_file() or result.stat().st_size == 0:
                raise RuntimeError("model did not produce output.mp4")
            job["state"] = "success"
        except Exception as error:
            job.update(state="failed", error="model inference failed; inspect inference.log on the service host")
            self._write_private(directory / "service-error.log",
                                f"{type(error).__name__}: {error}\n".encode())
        job["updated_at"] = now()
        self._persist(job)

    def _command(self, directory: Path, usage_scope: str) -> list[str]:
        runtime = self.settings.runtime_root
        if self.settings.kind == "musetalk":
            return ["bash", str(Path(__file__).resolve().parents[2] / "scripts/generate_musetalk_talking.sh"),
                    str(directory), str(runtime / "repository"), str(runtime / ".venv/bin/python")]
        provider = Path(__file__).resolve().parents[2] / "scripts" / f"{self.settings.kind}_provider.py"
        if self.settings.kind == "wav2lip":
            return [sys.executable, str(provider), "render", str(directory / "source.mp4"),
                    str(directory / "reference.wav"), str(directory / "output.mp4"),
                    "--runtime-root", str(runtime), "--rights-confirmed", "--usage-scope", usage_scope]
        source = next(directory.glob("source.*"))
        driving = next(directory.glob("driving.*"))
        config = directory / "config.json"
        return [sys.executable, str(provider), "render", str(source), str(driving), str(directory / "rendered"),
                "--runtime-root", str(runtime), "--rights-confirmed", *(["--config-json", str(config)] if config.is_file() else [])]

    def _load(self, identifier: str) -> dict | None:
        path = self.settings.job_root / identifier / "job.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(value, dict) or value.get("id") != identifier:
            raise RuntimeError("invalid persisted job")
        return value

    def _persist(self, job: dict) -> None:
        directory = self.settings.job_root / job["id"]
        temporary = directory / f"job.{uuid.uuid4()}.tmp"
        self._write_private(temporary, json.dumps(job, ensure_ascii=False).encode())
        os.replace(temporary, directory / "job.json")

    def _pending_count(self) -> int:
        count = 0
        for path in self.settings.job_root.glob("*/job.json"):
            try:
                if json.loads(path.read_text(encoding="utf-8")).get("state") in {"queued", "processing"}:
                    count += 1
            except (OSError, ValueError, AttributeError):
                continue
        return count

    def _fail_interrupted_jobs(self) -> None:
        for path in self.settings.job_root.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job.get("state") in {"queued", "processing"}:
                    job.update(state="failed", error="service restarted during inference", updated_at=now())
                    self._persist(job)
            except (OSError, ValueError, KeyError, TypeError):
                continue

    @staticmethod
    def _write_private(path: Path, content: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)


def create_app(settings: Settings | None = None):
    from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
    from fastapi.responses import FileResponse, JSONResponse, Response

    settings = settings or Settings.from_env()
    manager = JobManager(settings)
    application = FastAPI(title=f"OpenRealtime {settings.kind} service", version="1.0.0")

    def authorize(value: str | None) -> None:
        if settings.token and (value is None or not secrets.compare_digest(value, f"Bearer {settings.token}")):
            raise HTTPException(status_code=401, detail="invalid bearer token")

    @application.get("/health")
    def health():
        ready, missing = manager.readiness()
        return JSONResponse({"status": "ok" if ready else "not_ready", "model": settings.kind,
                             "missing": missing}, status_code=200 if ready else 503)

    @application.post("/v1/jobs", status_code=202)
    async def submit_job(source_video: UploadFile | None = File(default=None),
                         reference_audio: UploadFile | None = File(default=None),
                         source_image: UploadFile | None = File(default=None),
                         driving_video: UploadFile | None = File(default=None),
                         config_json: str | None = Form(default=None),
                         rights_confirmed: bool = Form(...), usage_scope: str = Form("internal_evaluation"),
                         x_job_id: str | None = Header(default=None),
                         authorization: str | None = Header(default=None)):
        authorize(authorization)
        source, reference = ((source_image, driving_video) if settings.kind == "liveportrait"
                             else (source_video, reference_audio))
        if source is None or reference is None:
            raise HTTPException(status_code=400, detail="required model input files are missing")
        try:
            source_extension = Path(source.filename or "").suffix.lower()
            reference_extension = Path(reference.filename or "").suffix.lower()
            return manager.submit(x_job_id, await source.read(MAX_SOURCE_BYTES + 1),
                                  await reference.read(MAX_REFERENCE_BYTES + 1),
                                  rights_confirmed=rights_confirmed, usage_scope=usage_scope,
                                  source_extension=source_extension, reference_extension=reference_extension,
                                  config_json=config_json)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @application.post("/v1/inspect-driving")
    async def inspect_driving(driving_video: UploadFile = File(...), authorization: str | None = Header(default=None)):
        authorize(authorization)
        if settings.kind != "liveportrait":
            raise HTTPException(status_code=404, detail="not supported by this model")
        import tempfile
        extension = Path(driving_video.filename or "").suffix.lower()
        if extension not in {".mp4", ".webm", ".mov"}:
            raise HTTPException(status_code=400, detail="unsupported driving video")
        video = await driving_video.read(MAX_SOURCE_BYTES + 1)
        if not video or len(video) > MAX_SOURCE_BYTES:
            raise HTTPException(status_code=400, detail="invalid driving video size")
        ready, missing = manager.readiness()
        if not ready:
            raise HTTPException(status_code=503, detail="model runtime not ready: " + "; ".join(missing))
        with tempfile.TemporaryDirectory(prefix="inspect-", dir=settings.job_root) as temporary:
            video_path = Path(temporary) / f"driving{extension}"
            manager._write_private(video_path, video)
            provider = Path(__file__).resolve().parents[2] / "scripts/liveportrait_provider.py"
            try:
                result = subprocess.run([sys.executable, str(provider), "inspect-driving", str(video_path),
                                         "--runtime-root", str(settings.runtime_root)],
                                        capture_output=True, text=True, timeout=190, check=True)
                return json.loads(result.stdout)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as error:
                raise HTTPException(status_code=422, detail="driving video validation failed") from error

    @application.post("/v1/retarget")
    async def retarget(source_image: UploadFile = File(...), config_json: str = Form(...),
                       rights_confirmed: bool = Form(...), authorization: str | None = Header(default=None)):
        authorize(authorization)
        if settings.kind != "liveportrait":
            raise HTTPException(status_code=404, detail="not supported by this model")
        extension = Path(source_image.filename or "").suffix.lower()
        if not rights_confirmed or extension not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=400, detail="invalid source or rights confirmation")
        source = await source_image.read(10 * 1024 * 1024 + 1)
        try:
            valid_config = isinstance(json.loads(config_json), dict) and len(config_json.encode()) <= 64 * 1024
        except ValueError:
            valid_config = False
        if not source or len(source) > 10 * 1024 * 1024 or not valid_config:
            raise HTTPException(status_code=400, detail="invalid source or retarget config")
        ready, missing = manager.readiness()
        if not ready:
            raise HTTPException(status_code=503, detail="model runtime not ready: " + "; ".join(missing))
        import tempfile
        with tempfile.TemporaryDirectory(prefix="retarget-", dir=settings.job_root) as temporary:
            directory = Path(temporary)
            source_path = directory / f"source{extension}"
            output_path = directory / "preview.png"
            config_path = directory / "config.json"
            manager._write_private(source_path, source)
            manager._write_private(config_path, config_json.encode())
            script = Path(__file__).resolve().parents[2] / "scripts/liveportrait_retarget_image.py"
            try:
                subprocess.run([str(settings.runtime_root / ".venv/bin/python"), str(script),
                                str(source_path), str(output_path), str(config_path),
                                "--repository", str(settings.runtime_root / "repository")],
                               capture_output=True, timeout=settings.timeout_seconds, check=True)
                return Response(output_path.read_bytes(), media_type="image/png")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
                raise HTTPException(status_code=500, detail="retarget inference failed") from error

    @application.get("/v1/jobs/{job_id}")
    def job_status(job_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return manager.get(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="job not found") from error

    @application.get("/v1/jobs/{job_id}/result")
    def job_result(job_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return FileResponse(manager.result_path(job_id), media_type="video/mp4", filename=f"{job_id}.mp4")
        except (KeyError, FileNotFoundError) as error:
            raise HTTPException(status_code=404, detail="job result not ready") from error

    return application
