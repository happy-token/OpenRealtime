# Voice Runtime Quality Evidence and Release Gate

This is the executable evidence contract for Phase 1 M5. It does not create
provider traffic: a live test operator or CI collector records one JSON object
per attempted full turn, including failed attempts, then the repository's gate
produces machine- and human-readable reports.

## Release commands

Generate a report directly:

```bash
uv run python scripts/generate_voice_runtime_quality_report.py \
  test-results/live-turns.jsonl \
  --json-output test-results/voice-runtime-quality.json \
  --markdown-output test-results/voice-runtime-quality.md
```

Collect content-free attempts from the runtime diagnostics API first. Use one
isolated campaign session per reconnect/device-failure attempt so session-level
recovery evidence cannot be attributed to the wrong turn:

```bash
uv run python scripts/collect_voice_runtime_quality_evidence.py \
  --control-plane-url http://127.0.0.1:8766 \
  --session-id '<campaign-voice-session-id>' \
  --run-id 'chrome-cn-normal-20260821-001' \
  --engine cascaded \
  --provider doubao-asr+deepseek+doubao-tts \
  --capture-profile desktop-web-phase1-v1 \
  --browser chrome \
  --browser-version '<installed-version>' \
  --network cn-normal \
  --result-type ordinary \
  --evidence live \
  --output test-results/live-turns.jsonl \
  --append
```

The collector requires a real `InputEpochStarted`, a terminal Turn and, for a
`live` label, at least one recorded provider call. It derives playback,
barge-in and reconnect-to-`ACTIVE` durations from the server-clock diagnostics
timeline. Its adjacent `.manifest.json` records the invocation dimensions and
selected Session IDs. This validation prevents accidental collection of the
browser-only fallback, but it cannot establish provider authenticity without
the retained CI/operator invocation and provider configuration.

The command exits with `0` for Passed, `1` for Failed, `2` for Preview, and
`3` for malformed evidence or report configuration.

Run the complete deterministic/browser/statistical release chain:

```bash
VOICE_RUNTIME_QUALITY_EVIDENCE=test-results/live-turns.jsonl \
  pnpm test:voice
```

Strict mode requires Chrome plus a Passed statistical report. On a developer
machine, `VOICE_RUNTIME_ALLOW_PREVIEW=1 pnpm test:voice` runs every locally
available deterministic/build/browser check while clearly reporting missing
Chrome or live-turn evidence. Preview is never a release pass.

## JSONL attempt contract

Each non-empty line is one attempted full turn. The parser is strict: missing
or unknown fields, duplicate `attempt_id` values, invalid booleans, negative or
non-finite durations, and malformed correctness violations reject the report.

```json
{"attempt_id":"run-20260821-turn-0001","engine":"cascaded","provider":"doubao-asr+deepseek+doubao-tts","capture_profile":"desktop-web-phase1-v1","browser":"chrome","browser_version":"128.0.6613.120","network":"cn-normal","result_type":"ordinary","evidence":"live","eot_to_playback_started_ms":742.3,"barge_in_to_audio_stopped_ms":null,"reconnect_to_active_ms":null,"abnormal_terminal":false,"voiced_sample_silent_loss":false,"correctness_violations":[]}
```

Fields:

- `attempt_id`: opaque unique run/turn correlation; never transcript content.
- `engine`, `provider`, `capture_profile`: the release Profile identity. The
  minimum 200 live attempts applies independently to every such combination.
- `browser`, `browser_version`, `network`, `result_type`: mandatory grouping
  dimensions. Phase 1 profile coverage requires `chrome`; other browser
  evidence may be recorded but is not a release prerequisite.
- `evidence`: `live` only when the installed browser traversed the real
  Cascaded provider chain. Fake WebSocket/model, deterministic conformers, and
  simulations must use `synthetic`; synthetic samples can only yield Preview.
- latency fields: same-clock monotonic durations for the named milestone, or
  `null` when that scenario does not contain the milestone. Do not subtract
  unsynchronised browser and server wall clocks.
- `abnormal_terminal`: includes no-response, provider failure, unhandled
  timeout, or otherwise abnormal terminal outcome; these attempts stay in the
  denominator.
- `voiced_sample_silent_loss` and `correctness_violations`: zero-tolerance
  correctness evidence. Any violation makes the report Failed regardless of
  sample count.

Recommended `result_type` values are `ordinary`, `barge_in`, `reconnect`,
`device_change`, `weak_network`, `provider_failure`, and `resource_cleanup`.
Collectors may add a more precise value, but must not merge failure scenarios
into an ordinary-success bucket.

## Gate semantics

The report keeps synthetic and live evidence in separate groups. For every
live Engine/Provider/Capture Profile it requires at least 200 attempted turns
and observations from Chrome. SLO percentiles are then calculated per browser
version, network tier, and result type:

- EOT accepted to client playback started: p50 `< 800 ms`, p95 `< 1500 ms`;
- Barge-in confirmed to old audio stopped: p95 `< 200 ms` when applicable;
- Network available to same-process Voice Session `ACTIVE`: p95 `< 1000 ms`
  when applicable;
- abnormal terminal rate `< 0.5%`;
- correctness violations and voiced-sample silent loss: exactly zero.

The report generator validates and aggregates supplied evidence; it cannot
prove that a collector truthfully labelled a sample `live`. Release evidence
must therefore retain the invocation manifest, provider/Profile configuration,
browser versions, network shaping configuration, and the content-free raw
JSONL alongside the generated reports. Raw PCM, transcripts, prompts, model
tokens, credentials, and Tool secrets must never enter this file.

## Current state

The deterministic gate, report generator, strict release script, and Chrome
E2E are implemented. Admission decisions/resource pressure, negotiated device
capture settings, capture failures, playback, barge-in and reconnect-to-Active
are recorded as content-free diagnostics; the collector exports them into the
strict JSONL contract. The repository contains the passed 2026-08-21
real-provider 200-turn corpus, invocation manifest and generated reports under
[`docs/reports/evidence`](./reports/evidence/); the reviewed result is
[`2026-08-21-voice-runtime-phase1-live.md`](./reports/2026-08-21-voice-runtime-phase1-live.md).
Phase 1 therefore satisfies the M5 live Profile gate.
