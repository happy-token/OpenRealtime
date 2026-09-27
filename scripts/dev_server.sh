#!/usr/bin/env bash
# Launches the Python WS (8765) + control-plane (8766) server for local dev.
# Invoked by `pnpm dev` via package.json's dev:server script.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

for env_file in .env .env.local; do
  if [ -f "$env_file" ]; then
    set -a
    source "$env_file"
    set +a
  fi
done

# Keep existing local VoiceLoop environments working without leaking the
# deprecated variable into the Python process (which would warn per session).
if [ -n "${WEB_SEARCH_API_KEY:-}" ] && [ -z "${BYTE_WEB_SEARCH_API_KEY:-}" ]; then
  export BYTE_WEB_SEARCH_API_KEY="${WEB_SEARCH_API_KEY}"
fi
unset WEB_SEARCH_API_KEY

export VOICEAGENT_EOT_FIRERED_MODEL_DIR="${VOICEAGENT_EOT_FIRERED_MODEL_DIR:-$PWD/models/fireredchat-turn-detector}"

exec uv run --extra firered --extra postgres --extra object-store python demos/voice_web_server.py dev
