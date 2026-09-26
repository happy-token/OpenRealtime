#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export MODEL_SERVICE_KIND=wav2lip
export MODEL_RUNTIME_ROOT="$repo_root/models/wav2lip"
export MODEL_SERVICE_JOB_ROOT="$repo_root/.openrealtime/model-jobs/wav2lip"
export MODEL_SERVICE_API_TOKEN=$(<"$repo_root/.openrealtime/model-service-secrets/wav2lip-token")
cd "$repo_root"
exec "$repo_root/.venv-wav2lip-service/bin/uvicorn" deploy.inference_services.app:create_app \
  --factory --host 127.0.0.1 --port 18192 --workers 1 --no-proxy-headers
