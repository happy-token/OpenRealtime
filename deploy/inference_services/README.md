# Standalone inference services

This directory is the distribution boundary for four **independent** model APIs.
It belongs under `deploy/`, not `src/`, because the web application only needs
their URLs; each model process owns its runtime, weights, queue and job storage.
No model weights, virtual environments or user media are included in this repo.

| Service | Host port | Typical hardware | Guide |
| --- | ---: | --- | --- |
| Lip Forcing | 18190 | NVIDIA GPU host | [lipforcing.md](lipforcing.md) |
| MuseTalk | 18191 | NVIDIA CUDA host | [musetalk.md](musetalk.md) |
| Wav2Lip | 18192 | CPU for testing; MPS/CUDA for speed | [wav2lip.md](wav2lip.md) |
| LivePortrait | 18193 | Apple Silicon MPS or NVIDIA GPU; CPU is slow | [liveportrait.md](liveportrait.md) |

## Deployment choices

1. **Native process**: best for the existing macOS model environments and the
   already-running Lip Forcing GPU host. Use a service manager such as systemd
   or launchd for persistence.
2. **Docker Compose**: one profile per model. Use on a Linux host with a
   **Linux-built** model runtime under `runtime/<model>/`. Compose builds only
   the small API wrapper, never downloads licensed weights.
3. **Individual `docker run`**: use the same Dockerfile and runtime mount for
   one model without Compose. See each guide.

Do **not** mount the current macOS `models/*/.venv` into Linux containers:
Python binaries and PyTorch wheels are platform-specific. Prepare the runtime
inside a compatible Linux environment first. GPU Compose additionally needs
NVIDIA Container Toolkit and a CUDA-compatible runtime. [Docker's GPU Compose
documentation](https://docs.docker.com/compose/how-tos/gpu-support/) describes
the device reservation used here.

### Compose quick start

From this directory, copy `.env.example` to `.env` and set the appropriate
runtime root and token **for the service process only**. The web application's
service URLs are configured in its **Settings → Model Services** screen, not in
the web app's `.env`. An administrator saves them through the UI; the web app
persists the connections in its private `.openrealtime/model-service-connections.json`
file. Mount `.openrealtime/` on persistent storage when containerizing the web
app. After preparing the runtime described by the model's
guide:

```sh
docker compose config --quiet
docker compose --profile liveportrait up --build -d
curl -fsS http://127.0.0.1:18193/health
docker compose logs -f liveportrait
```

Start another service by changing the profile to `wav2lip`, `musetalk` or
`lipforcing`. Compose profiles keep unrelated models off the host. The four
services use separate persistent named volumes for jobs; `docker compose down
-v` **deletes** those jobs and should not be used casually.

The Compose file binds HTTP ports to `127.0.0.1` only. For a remote web app,
use an authenticated reverse proxy or SSH tunnel (for example through `beike`)
instead of exposing the raw model port to the Internet. Each model accepts an
optional bearer token. Set a strong token for every non-isolated deployment.
The token belongs on the web **server**, not in browser JavaScript.

### HTTP contract

Each service implements `GET /health`, `POST /v1/jobs`,
`GET /v1/jobs/{id}` and `GET /v1/jobs/{id}/result`. The result is an MP4.
`X-Job-Id` makes a retry idempotent. Job state is `queued`, `processing`,
`success` or `failed`. An interrupted job is marked failed on restart; it is
not silently regenerated.

For MuseTalk and Wav2Lip, submit multipart fields `source_video` (MP4),
`reference_audio` (WAV), `rights_confirmed=true`. For LivePortrait, use
`source_image` (portrait PNG/JPEG/WebP), `driving_video` (MP4/WebM/MOV) and
optional `config_json`; `POST /v1/inspect-driving` validates an uploaded
driving clip, and `POST /v1/retarget` returns a PNG pose preview. Wav2Lip additionally accepts `usage_scope`,
limited to `internal_evaluation`, `research` or `personal` because the upstream
open-source model prohibits commercial use.

Example for Wav2Lip:

```sh
curl -H "Authorization: Bearer $WAV2LIP_SERVICE_TOKEN" \
  -F source_video=@source.mp4 -F reference_audio=@voice.wav \
  -F rights_confirmed=true -F usage_scope=internal_evaluation \
  http://127.0.0.1:18192/v1/jobs
```

The URL entered at `/settings/services` is the service base URL, such as
`http://127.0.0.1:18192` **as seen from the web server**. `127.0.0.1` inside
a web container refers to that container, not the host or another container.

## Verification scope

This package provides deployment entry points and the same API shape for all
models. On this developer machine, the existing native Wav2Lip and
LivePortrait runtimes pass their diagnostic commands with MPS. The wrapper's
API/Compose syntax can be tested without weights, but an end-to-end Docker
render requires a separately prepared Linux model runtime. Do not interpret
`docker compose config` or an image build as proof that model inference works.
