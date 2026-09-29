#!/usr/bin/env bash
set -euo pipefail

exec /usr/bin/ssh -N \
  -o BatchMode=yes \
  -o ConnectTimeout=15 \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=accept-new \
  -L 127.0.0.1:8190:127.0.0.1:8190 \
  -L 127.0.0.1:18191:127.0.0.1:18191 \
  "${LIPFORCING_GPU_SSH_TARGET:-dev}"
