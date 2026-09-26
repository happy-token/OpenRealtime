#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
via_host=${LIPFORCING_GPU_VIA_HOST:-beike}
gpu_host=${LIPFORCING_GPU_SSH_TARGET:-root@localhost}
gpu_ssh_port=${LIPFORCING_GPU_SSH_PORT:-10022}
local_port=${LIPFORCING_LOCAL_API_PORT:-18190}
proxy_command=${LIPFORCING_GPU_PROXY_COMMAND:-ssh -o BatchMode=yes "$via_host" -W localhost:"$gpu_ssh_port"}
ssh_options=(-o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new -o "ProxyCommand=$proxy_command")

usage() {
  cat <<'EOF'
Usage: scripts/lipforcing_service.sh COMMAND

Commands:
  deploy       install or update the GPU API and start it
  start        start the remote service
  stop         stop the remote service
  restart      restart the remote service
  status       show the systemd or s6 service status
  logs         follow service logs
  smoke        query the remote health endpoint through SSH
  token        print the API token for application configuration
  tunnel       expose the remote loopback API on local port 18190
EOF
}

remote() {
  ssh "${ssh_options[@]}" "$gpu_host" "$@"
}

command=${1:-}
case "$command" in
  deploy)
    remote_tmp=$(remote 'mktemp -d /tmp/openrealtime-lipforcing.XXXXXX')
    case "$remote_tmp" in
      /tmp/openrealtime-lipforcing.*) ;;
      *) echo "unexpected remote staging directory: $remote_tmp" >&2; exit 1 ;;
    esac
    scp "${ssh_options[@]}" \
      "$repo_root/deploy/lipforcing/app.py" \
      "$repo_root/deploy/lipforcing/requirements.txt" \
      "$repo_root/deploy/lipforcing/openrealtime-lipforcing.service" \
      "$repo_root/deploy/lipforcing/s6-run" \
      "$repo_root/deploy/lipforcing/install.sh" \
      "$repo_root/scripts/generate_lipforcing_talking.sh" \
      "$gpu_host:$remote_tmp/"
    remote "bash '$remote_tmp/install.sh'"
    remote "rm -r -- '$remote_tmp'"
    ;;
  start|stop|restart)
    remote "if systemctl show-environment >/dev/null 2>&1; then systemctl $command openrealtime-lipforcing.service; else case '$command' in start) flag=-u ;; stop) flag=-d ;; restart) flag=-t ;; esac; /package/admin/s6/command/s6-svc \"\$flag\" /run/service/openrealtime-lipforcing; fi"
    ;;
  status)
    remote "if systemctl show-environment >/dev/null 2>&1; then systemctl --no-pager --full status openrealtime-lipforcing.service; else /package/admin/s6/command/s6-svstat /run/service/openrealtime-lipforcing; fi"
    ;;
  logs)
    remote "if systemctl show-environment >/dev/null 2>&1; then journalctl -u openrealtime-lipforcing.service -f -n 100; else touch /var/log/openrealtime-lipforcing.log; tail -n 100 -f /var/log/openrealtime-lipforcing.log; fi"
    ;;
  smoke)
    remote "curl --fail --silent --show-error http://127.0.0.1:18190/health"
    echo
    ;;
  token)
    remote "sed -n 's/^LIPFORCING_API_TOKEN=//p' /etc/openrealtime-lipforcing.env"
    ;;
  tunnel)
    exec ssh "${ssh_options[@]}" -N -L "127.0.0.1:$local_port:127.0.0.1:18190" "$gpu_host"
    ;;
  *)
    usage
    [[ -z "$command" ]]
    ;;
esac
