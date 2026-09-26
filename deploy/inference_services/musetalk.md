# MuseTalk service

Purpose: generate a lip-synced MP4 from an MP4 motion base and WAV audio. It
reuses `scripts/generate_musetalk_talking.sh` and the shared HTTP job service.

## Hardware and prerequisites

The [official MuseTalk installation guide](https://github.com/TMElyralab/MuseTalk#installation)
recommends Python 3.10 with CUDA and documents NVIDIA V100 real-time results.
The current runner explicitly selects `--use_float16` and is intended for a
CUDA host. Do **not** claim this service works without GPU based on the HTTP
server starting. For local UI/API tests, `/health` and synthetic job-state
tests suffice; actual inference needs a compatible model runtime. Also review
the licenses of MuseTalk's third-party model dependencies.

The runtime directory must contain `repository/` with upstream MuseTalk 1.5,
`repository/models/musetalkV15/unet.pth`, the other model dependencies listed
in the upstream README, and `.venv/bin/python`. FFmpeg, ffprobe and `flock`
must be available. The runtime volume must be writable because the runner
creates a lock file there.

## Native GPU-host deployment

On the GPU host, from the repository root after preparing the runtime:

```sh
python3 -m venv .venv-musetalk-service
.venv-musetalk-service/bin/pip install -r deploy/inference_services/requirements.txt
MODEL_SERVICE_KIND=musetalk MODEL_RUNTIME_ROOT="$PWD/models/musetalk" \
  MODEL_SERVICE_JOB_ROOT="$PWD/data/model-jobs/musetalk" \
  .venv-musetalk-service/bin/uvicorn deploy.inference_services.app:create_app \
  --factory --host 127.0.0.1 --port 18191
```

Use systemd for restart and a persistent job root. Reach the host from the
web server through a protected tunnel via `beike` or an authenticated proxy.

## Docker Compose / docker run on Linux NVIDIA

Set `MUSETALK_RUNTIME_ROOT` in `.env` to a Linux/CUDA-compatible runtime
prepared in a compatible container environment, then:

```sh
docker compose --profile musetalk up --build -d
curl -i http://127.0.0.1:18191/health
```

The Compose profile requests one NVIDIA GPU using the Compose device
reservation. For `docker run`, build `Dockerfile`, mount the runtime at
`/models/musetalk`, persist `/data/jobs`, set `MODEL_SERVICE_KIND=musetalk`
and `MODEL_RUNTIME_ROOT=/models/musetalk`, pass `--gpus all`, and publish
`127.0.0.1:18191:8000`. The mounted runtime must be writable by UID 10001.
The wrapper image does not bundle CUDA or weights: validate a complete short
render before treating this as a production deployment.
