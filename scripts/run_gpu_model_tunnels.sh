#!/usr/bin/env bash
set -euo pipefail

exec /usr/bin/ssh -N \
  -o BatchMode=yes \
  -o ConnectTimeout=15 \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=accept-new \
  -o 'ProxyCommand=/usr/bin/ssh -o BatchMode=yes beike -W localhost:10022' \
  -L 127.0.0.1:18190:127.0.0.1:18190 \
  -L 127.0.0.1:18191:127.0.0.1:18191 \
  root@localhost
