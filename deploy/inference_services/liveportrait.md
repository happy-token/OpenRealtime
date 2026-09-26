# LivePortrait service

Purpose: animate a portrait image using a driving video. The HTTP service
accepts PNG/JPEG/WebP + MP4/WebM/MOV and returns an MP4 job result. It reuses
`scripts/liveportrait_provider.py`, including its runtime/weight checks. It
also exposes driving-video inspection and pose retargeting as remote endpoints.

## Hardware and prerequisites

The [official LivePortrait instructions](https://github.com/KlingAIResearch/LivePortrait#1-clone-the-code-and-prepare-the-environment-)
support human mode on Apple Silicon and warn it may be about 20× slower than
an RTX 4090. CPU-only inference may be possible with a compatible PyTorch
installation, but is **not validated here**. For this repository, the
`models/liveportrait` runtime diagnostic is ready on macOS MPS. You need
FFmpeg, the pinned human weights, and rights to both the portrait and driving
clip. `python3 scripts/setup_liveportrait_runtime.py --help` documents the
macOS runtime installer; it is intentionally macOS/arm64-only.

## Native macOS deployment (recommended for the existing runtime)

Run from the repository root, using a separate API environment:

```sh
python3 -m venv .venv-liveportrait-service
.venv-liveportrait-service/bin/pip install -r deploy/inference_services/requirements.txt
python3 scripts/liveportrait_provider.py diagnose --runtime-root models/liveportrait
MODEL_SERVICE_KIND=liveportrait MODEL_RUNTIME_ROOT="$PWD/models/liveportrait" \
  MODEL_SERVICE_JOB_ROOT="$PWD/data/model-jobs/liveportrait" \
  .venv-liveportrait-service/bin/uvicorn deploy.inference_services.app:create_app \
  --factory --host 127.0.0.1 --port 18193
```

Use a launchd unit for automatic restart; keep job storage persistent and
back it up if results need retention. Set `MODEL_SERVICE_API_TOKEN` when a
proxy/tunnel makes this reachable outside the local host.

## Docker Compose / docker run on Linux

Prepare `runtime/liveportrait/repository` and
`runtime/liveportrait/.venv/bin/python` **on Linux** using the upstream
requirements and weights, and confirm the repository's pinned provider
diagnostic succeeds in that environment. Set `LIVEPORTRAIT_RUNTIME_ROOT` to
that directory in `.env`, then:

```sh
docker compose --profile liveportrait up --build -d
curl -i http://127.0.0.1:18193/health
```

For a single-container deployment instead, build the wrapper with
`docker build -f deploy/inference_services/Dockerfile -t openrealtime-model-service .`
from the repository root, then mount the Linux runtime to
`/models/liveportrait` and persistent jobs to `/data/jobs`, set
`MODEL_SERVICE_KIND=liveportrait` and `MODEL_RUNTIME_ROOT=/models/liveportrait`,
and publish host port 18193 to container port 8000 on loopback. The mounted
runtime must be readable and writable by container UID 10001.

Submit `source_image` as PNG/JPEG/WebP, `driving_video` as MP4/WebM/MOV,
`rights_confirmed=true`, and optionally `config_json` with the motion options.
`POST /v1/inspect-driving` accepts `driving_video` for eligibility checks.
`POST /v1/retarget` accepts `source_image`, `config_json` and
`rights_confirmed=true`, then returns a PNG preview.
Check `GET /v1/jobs/{id}` before downloading the
result. The service creates no public media URLs.
