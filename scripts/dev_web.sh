#!/usr/bin/env bash

set -euo pipefail

# This marker is intentionally process-local. The preview authorization policy
# only enables its development bypass when this launcher also binds Next.js to
# the loopback interface, so a normal `next dev` process remains admin-only.
export AVATAR_EVALUATION_LOOPBACK_BOUND=true

if [ "${OPENREALTIME_WAIT_FOR_AVATAR_SERVICES:-false}" = "true" ]; then
  bash scripts/avatar_services.sh wait
fi

exec pnpm exec next dev --hostname 127.0.0.1 --port "${OPENREALTIME_WEB_PORT:-3010}"
