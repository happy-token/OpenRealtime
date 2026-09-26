# Wav2Lip service

Purpose: align an MP4 face video to a pre-normalized WAV file. The service
reuses `scripts/wav2lip_provider.py`, which checks a pinned upstream checkout,
weights and FFmpeg before rendering.

## License, hardware and prerequisites

The [official Wav2Lip repository](https://github.com/Rudrabha/Wav2Lip#non-commercial-open-source-version)
restricts the open-source model to research, academic and personal use; it
explicitly prohibits commercial use. Accordingly this API accepts only
`internal_evaluation`, `research` or `personal` as `usage_scope`. Do not expose
it as an unrestricted production/commercial model.

The existing macOS runtime at `models/wav2lip` passes its diagnostic on MPS.
CPU inference is useful for a small local smoke test but may be slow. It does
not need an NVIDIA GPU merely to start the service. The input audio must
already be WAV, and the operator must confirm rights to the face and audio.

## Native macOS deployment

From the repository root:

```sh
python3 -m venv .venv-wav2lip-service
.venv-wav2lip-service/bin/pip install -r deploy/inference_services/requirements.txt
python3 scripts/wav2lip_provider.py diagnose --runtime-root models/wav2lip
MODEL_SERVICE_KIND=wav2lip MODEL_RUNTIME_ROOT="$PWD/models/wav2lip" \
  MODEL_SERVICE_JOB_ROOT="$PWD/data/model-jobs/wav2lip" \
  .venv-wav2lip-service/bin/uvicorn deploy.inference_services.app:create_app \
  --factory --host 127.0.0.1 --port 18192
```

The pinned macOS runtime installer is
`python3 scripts/setup_wav2lip_runtime.py --help`. For persistence, run the
command under launchd and keep the job directory on durable storage.

## Docker Compose / docker run on Linux

Build a Linux-compatible `runtime/wav2lip/repository` and
`runtime/wav2lip/.venv/bin/python` from the official source plus this
repository's compatibility patch and pinned weights; the macOS runtime is not
portable into a Linux container. Set `WAV2LIP_RUNTIME_ROOT` in `.env`:

```sh
docker compose --profile wav2lip up --build -d
curl -i http://127.0.0.1:18192/health
```

An individual deployment uses `Dockerfile` in this directory with
`MODEL_SERVICE_KIND=wav2lip`, `MODEL_RUNTIME_ROOT=/models/wav2lip`, the Linux
runtime mounted at `/models/wav2lip`, a persistent `/data/jobs` volume, and
loopback port `18192:8000`. The mounted runtime must be readable and writable
by container UID 10001. Run `/health` and one rights-cleared short clip before
considering the instance ready for users.
