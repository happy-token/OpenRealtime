#!/usr/bin/env bash

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ "${OPENREALTIME_WAIT_FOR_AVATAR_SERVICES:-false}" = "true" ]; then
  bash scripts/avatar_services.sh wait
fi

exec pnpm exec next start
