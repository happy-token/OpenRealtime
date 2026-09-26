#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "install-musetalk-gpu.sh must run as root" >&2
  exit 1
fi

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install_dir=/opt/openrealtime-musetalk-service
runtime_dir=/opt/openrealtime-musetalk-runtime
environment_file=/etc/openrealtime-musetalk.env

if [[ ! -f /root/lipsync-eval/musetalk/models/musetalkV15/unet.pth || ! -x /root/lipsync-eval/venv-musetalk/bin/python ]]; then
  echo "MuseTalk runtime or weights are missing" >&2
  exit 1
fi

install -d -m 0755 "$install_dir/deploy/inference_services" "$install_dir/scripts" "$runtime_dir"
install -m 0644 "$source_dir/app.py" "$install_dir/deploy/inference_services/app.py"
install -m 0644 "$source_dir/__init__.py" "$install_dir/deploy/inference_services/__init__.py"
install -m 0644 "$source_dir/requirements.txt" "$install_dir/requirements.txt"
install -m 0755 "$source_dir/generate_musetalk_talking.sh" "$install_dir/scripts/generate_musetalk_talking.sh"
ln -sfn /root/lipsync-eval/musetalk "$runtime_dir/repository"
ln -sfn /root/lipsync-eval/venv-musetalk "$runtime_dir/.venv"

if [[ ! -x "$install_dir/venv/bin/python" ]]; then
  python3 -m venv "$install_dir/venv"
fi
"$install_dir/venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -r "$install_dir/requirements.txt"

install -d -m 0700 /var/lib/openrealtime-musetalk/jobs
if [[ ! -f "$environment_file" ]]; then
  api_token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  install -m 0600 /dev/null "$environment_file"
  {
    echo 'MODEL_SERVICE_KIND=musetalk'
    echo "MODEL_RUNTIME_ROOT=$runtime_dir"
    echo 'MODEL_SERVICE_JOB_ROOT=/var/lib/openrealtime-musetalk/jobs'
    echo 'MODEL_SERVICE_TIMEOUT_SECONDS=1800'
    echo "MODEL_SERVICE_API_TOKEN=$api_token"
  } >> "$environment_file"
fi

if [[ -x /package/admin/s6/command/s6-svc ]]; then
  install -d -m 0755 /etc/services.d/openrealtime-musetalk
  install -m 0755 "$source_dir/musetalk-s6-run" /etc/services.d/openrealtime-musetalk/run
  ln -sfn /etc/services.d/openrealtime-musetalk /run/service/openrealtime-musetalk
  /package/admin/s6/command/s6-svscanctl -a /run/service
  for attempt in {1..10}; do
    if /package/admin/s6/command/s6-svstat /run/service/openrealtime-musetalk >/dev/null 2>&1; then break; fi
    sleep 1
  done
  /package/admin/s6/command/s6-svc -u /run/service/openrealtime-musetalk
  sleep 1
  /package/admin/s6/command/s6-svstat /run/service/openrealtime-musetalk
else
  echo "s6 supervision is unavailable" >&2
  exit 1
fi
