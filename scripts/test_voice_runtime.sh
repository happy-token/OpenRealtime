#!/usr/bin/env bash

set -euo pipefail

VOICE_RUNTIME_ALLOW_PREVIEW="${VOICE_RUNTIME_ALLOW_PREVIEW:-0}"

python_command=()
if [[ -n "${VOICEAGENT_PYTHON_BIN:-}" ]]; then
  if [[ ! -x "$VOICEAGENT_PYTHON_BIN" ]]; then
    echo "Python test runtime not found: $VOICEAGENT_PYTHON_BIN" >&2
    exit 1
  fi
  python_command=("$VOICEAGENT_PYTHON_BIN")
elif [[ -x ".venv/bin/python" ]]; then
  python_command=(".venv/bin/python")
elif command -v uv >/dev/null 2>&1; then
  python_command=(uv run python)
else
  echo "Python test runtime not found; install uv or create .venv." >&2
  exit 1
fi

resolve_browser() {
  local configured_path="$1"
  local macos_path="$2"
  shift 2
  if [[ -n "$configured_path" && -x "$configured_path" ]]; then
    printf '%s\n' "$configured_path"
    return 0
  fi
  if [[ -x "$macos_path" ]]; then
    printf '%s\n' "$macos_path"
    return 0
  fi
  local candidate
  for candidate in "$@"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

allocate_e2e_port() {
  "${python_command[@]}" - <<'PY'
import socket

with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    print(listener.getsockname()[1])
PY
}

run_browser_e2e() {
  local browser_name="$1"
  local executable_path="$2"
  local e2e_port
  e2e_port="$(allocate_e2e_port)"
  echo "Running Voice Runtime E2E in ${browser_name}: ${executable_path}"
  PLAYWRIGHT_BASE_URL="http://127.0.0.1:${e2e_port}" \
    PLAYWRIGHT_EXECUTABLE_PATH="$executable_path" \
    pnpm test:e2e
}

run_statistical_gate() {
  local evidence_path="${VOICE_RUNTIME_QUALITY_EVIDENCE:-}"
  if [[ -z "$evidence_path" || ! -f "$evidence_path" ]]; then
    if [[ "$VOICE_RUNTIME_ALLOW_PREVIEW" == "1" ]]; then
      echo "Preview run: no real-turn evidence; statistical gate not evaluated." >&2
      return 0
    fi
    echo "Voice Runtime release gate requires VOICE_RUNTIME_QUALITY_EVIDENCE JSONL." >&2
    return 1
  fi

  local json_output="${VOICE_RUNTIME_QUALITY_JSON_OUTPUT:-test-results/voice-runtime-quality.json}"
  local markdown_output="${VOICE_RUNTIME_QUALITY_MARKDOWN_OUTPUT:-test-results/voice-runtime-quality.md}"
  local gate_status
  set +e
  "${python_command[@]}" scripts/generate_voice_runtime_quality_report.py \
    "$evidence_path" \
    --json-output "$json_output" \
    --markdown-output "$markdown_output"
  gate_status=$?
  set -e
  if (( gate_status == 0 )); then
    return 0
  fi
  if (( gate_status == 2 )) && [[ "$VOICE_RUNTIME_ALLOW_PREVIEW" == "1" ]]; then
    echo "Preview run: statistical evidence is below the release threshold." >&2
    return 0
  fi
  return "$gate_status"
}

chrome_path="$(
  resolve_browser \
    "${PLAYWRIGHT_CHROME_EXECUTABLE_PATH:-${PLAYWRIGHT_EXECUTABLE_PATH:-}}" \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    google-chrome google-chrome-stable chromium chromium-browser || true
)"

if [[ -z "$chrome_path" ]]; then
  if [[ "$VOICE_RUNTIME_ALLOW_PREVIEW" != "1" ]]; then
    echo "Voice Runtime release gate requires Chrome." >&2
    echo "Set VOICE_RUNTIME_ALLOW_PREVIEW=1 only for a non-release Preview run." >&2
    exit 1
  fi
  echo "Preview run: required Chrome browser is missing." >&2
fi

run_statistical_gate

"${python_command[@]}" -m pytest -q
pnpm test
pnpm exec tsc --noEmit
pnpm build

if [[ -n "$chrome_path" ]]; then
  run_browser_e2e "chrome" "$chrome_path"
fi
