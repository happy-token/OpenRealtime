#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "install.sh must run as root" >&2
  exit 1
fi

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install_dir=/opt/openrealtime-lipforcing-service
environment_file=/etc/openrealtime-lipforcing.env
service_file=/etc/systemd/system/openrealtime-lipforcing.service

install -d -m 0755 "$install_dir"
install -m 0644 "$source_dir/app.py" "$install_dir/app.py"
install -m 0644 "$source_dir/requirements.txt" "$install_dir/requirements.txt"
install -m 0755 "$source_dir/generate_lipforcing_talking.sh" "$install_dir/generate_lipforcing_talking.sh"
install -m 0644 "$source_dir/openrealtime-lipforcing.service" "$service_file"

if [[ ! -x "$install_dir/venv/bin/python" ]]; then
  python3 -m venv "$install_dir/venv"
fi
"$install_dir/venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -r "$install_dir/requirements.txt"

install -d -m 0700 /var/lib/openrealtime-lipforcing/jobs
if [[ ! -f "$environment_file" ]]; then
  api_token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  install -m 0600 /dev/null "$environment_file"
  {
    echo 'LIPFORCING_REMOTE_ROOT=/root/lipsync-eval/lipforcing-eval'
    echo 'LIPFORCING_REMOTE_PYTHON=/root/lipsync-eval/venv-lipforcing/bin/python'
    echo 'LIPFORCING_RUNNER=/opt/openrealtime-lipforcing-service/generate_lipforcing_talking.sh'
    echo 'LIPFORCING_SERVICE_JOB_ROOT=/var/lib/openrealtime-lipforcing/jobs'
    echo "LIPFORCING_API_TOKEN=$api_token"
    echo 'LIPFORCING_JOB_TIMEOUT_SECONDS=3600'
    echo 'LIPFORCING_MAX_PENDING_JOBS=4'
  } >> "$environment_file"
fi

if systemctl show-environment >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl enable --now openrealtime-lipforcing.service
  systemctl --no-pager --full status openrealtime-lipforcing.service
elif [[ -x /package/admin/s6/command/s6-svc ]]; then
  install -d -m 0755 /etc/services.d/openrealtime-lipforcing
  install -m 0755 "$source_dir/s6-run" /etc/services.d/openrealtime-lipforcing/run
  ln -sfn /etc/services.d/openrealtime-lipforcing /run/service/openrealtime-lipforcing
  /package/admin/s6/command/s6-svscanctl -a /run/service
  /package/admin/s6/command/s6-svc -u /run/service/openrealtime-lipforcing
  sleep 1
  /package/admin/s6/command/s6-svstat /run/service/openrealtime-lipforcing
else
  echo "neither systemd nor s6 supervision is available" >&2
  exit 1
fi
