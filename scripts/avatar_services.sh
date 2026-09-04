#!/usr/bin/env bash
# Starts the local realtime avatar sidecars before a conversation requests one.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ -z "${OPENREALTIME_AVATAR_RENDERER_MODE+x}" ] \
  && [ -z "${OPENREALTIME_START_AVATAR_SERVICES+x}" ] \
  && [ -f .env ]; then
  set -a
  source .env
  set +a
fi

avatar_services_command="${1:-start}"
avatar_renderer_mode="${OPENREALTIME_AVATAR_RENDERER_MODE:-}"
avatar_services_flag="${OPENREALTIME_START_AVATAR_SERVICES:-true}"
avatar_renderer_url="${OPENREALTIME_AVATAR_RENDERER_URL:-http://127.0.0.1:8010}"
avatar_renderer_adapter="livetalking-wav2lip256"
livetalking_port="8010"
livetalking_avatar_id="shuchang256"
livetalking_inference_stride="${OPENREALTIME_WAV2LIP_INFERENCE_STRIDE:-2}"

if [ -z "$avatar_renderer_mode" ]; then
  case "$avatar_services_flag" in
    1|true|TRUE|yes|YES|on|ON) avatar_renderer_mode="managed" ;;
    0|false|FALSE|no|NO|off|OFF) avatar_renderer_mode="disabled" ;;
    *)
      echo "OPENREALTIME_START_AVATAR_SERVICES must be true or false"
      exit 2
      ;;
  esac
fi
case "$avatar_renderer_mode" in
  managed|external|disabled) ;;
  *)
    echo "OPENREALTIME_AVATAR_RENDERER_MODE must be managed, external, or disabled"
    exit 2
    ;;
esac
if [[ ! "$avatar_renderer_url" =~ ^https?://[A-Za-z0-9._:-]+/?$ ]]; then
  echo "OPENREALTIME_AVATAR_RENDERER_URL must be an http(s) origin without a path"
  exit 2
fi
case "$livetalking_inference_stride" in
  1|2) ;;
  *)
    echo "OPENREALTIME_WAV2LIP_INFERENCE_STRIDE must be 1 or 2"
    exit 2
    ;;
esac
avatar_renderer_url="${avatar_renderer_url%/}"

if [ "$avatar_renderer_mode" = "disabled" ]; then
  if [ "$avatar_services_command" = "plan" ]; then
    printf '{"enabled":false,"mode":"disabled","services":[]}\n'
  else
    echo "Self-hosted avatar rendering is disabled"
  fi
  exit 0
fi
if [ "$avatar_services_command" = "plan" ]; then
  printf '{"enabled":true,"mode":"%s","services":[{"id":"avatar-renderer","adapter":"%s","endpoint":"%s","avatar_id":"%s","inference_stride":%s}]}\n' \
    "$avatar_renderer_mode" "$avatar_renderer_adapter" "$avatar_renderer_url" "$livetalking_avatar_id" "$livetalking_inference_stride"
  exit 0
fi
if [ "$avatar_services_command" != "start" ] && [ "$avatar_services_command" != "wait" ]; then
  echo "Usage: scripts/avatar_services.sh [plan|start|wait]"
  exit 2
fi

livetalking_is_ready() {
  renderer_probe="$(curl --silent --show-error --output /dev/null --max-time 1 \
    --header 'Origin: http://127.0.0.1:3010' \
    --write-out '%{http_code} %{redirect_url}' \
    "$avatar_renderer_url/" 2>/dev/null || true)"
  [ "$renderer_probe" = "302 $avatar_renderer_url/index.html" ]
}

if [ "$avatar_services_command" = "wait" ]; then
  avatar_services_attempt=0
  while ! livetalking_is_ready; do
    avatar_services_attempt=$((avatar_services_attempt + 1))
    if [ "$avatar_services_attempt" -ge 240 ]; then
      echo "Timed out waiting for avatar renderer at $avatar_renderer_url"
      exit 1
    fi
    sleep 0.5
  done
  echo "Avatar renderer is ready at $avatar_renderer_url"
  exit 0
fi

if [ "$avatar_renderer_mode" = "external" ]; then
  echo "External avatar renderer is managed outside OpenRealtime: $avatar_renderer_url"
  exit 0
fi

if [ "$avatar_renderer_url" != "http://127.0.0.1:$livetalking_port" ]; then
  echo "Managed MVP renderer must use http://127.0.0.1:$livetalking_port"
  exit 2
fi

if livetalking_is_ready; then
  echo "Avatar renderer is already ready at $avatar_renderer_url"
  exit 0
fi

livetalking_python="$PWD/models/livetalking/.venv/bin/python"
if [ ! -x "$livetalking_python" ]; then
  echo "LiveTalking runtime is not installed: $livetalking_python"
  exit 1
fi

echo "Prewarming avatar renderer with the LiveTalking Wav2Lip compatibility adapter"
exec "$livetalking_python" "$PWD/scripts/livetalking_provider.py" serve \
  --runtime-root "$PWD/models/livetalking" \
  --avatar-id "$livetalking_avatar_id" \
  --port "$livetalking_port" \
  --inference-stride "$livetalking_inference_stride" \
  --model-size 256
