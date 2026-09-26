# Lip Forcing service

Purpose: lip-sync an MP4 motion base to WAV audio using the large Lip Forcing
model. Unlike the other three services, its existing production HTTP code is
kept in `deploy/lipforcing/app.py`. This package adds a Compose entry point
without changing the running GPU service.

## Hardware and prerequisites

The current runtime is a GPU-host installation; it is **not** a CPU/Mac test
candidate. `deploy/lipforcing/install.sh` and
`deploy/lipforcing/openrealtime-lipforcing.service` provide the proven native
systemd deployment. The application reaches it through the `beike` SSH tunnel
documented by `scripts/lipforcing_service.sh`. The runtime must contain the
model Python environment and all weights checked by `/health`.

## Native deployment (current recommended path)

On the GPU host, use the existing install/systemd flow in `deploy/lipforcing`.
From the web host, `scripts/lipforcing_service.sh smoke` tests the deployed
service through `beike`. Configure the **web server** with
`LIPFORCING_API_URL=http://127.0.0.1:18190` only while that tunnel is active;
set `LIPFORCING_API_TOKEN` server-side when the service token is enabled.

## Docker Compose / docker run on Linux NVIDIA

Set `LIPFORCING_RUNTIME_ROOT` in `.env` to a Linux runtime directory containing
`lipforcing-eval/` and `venv-lipforcing/`, then:

```sh
docker compose --profile lipforcing up --build -d
curl -i http://127.0.0.1:18190/health
```

Compose mounts persistent jobs at `/data/jobs` and asks for one NVIDIA GPU.
For `docker run`, build `Dockerfile.lipforcing`, mount that runtime directory
at `/runtime`, persist `/data/jobs`, set
`LIPFORCING_REMOTE_ROOT=/runtime/lipforcing-eval`,
`LIPFORCING_REMOTE_PYTHON=/runtime/venv-lipforcing/bin/python`, and
`LIPFORCING_RUNNER=/app/generate_lipforcing_talking.sh`, pass `--gpus all`,
and publish `127.0.0.1:18190:8000`. The runtime must be compatible with the
container OS/CUDA libraries and writable by UID 10001. This image has **not**
replaced the tested systemd deployment; validate inference before cutover.
