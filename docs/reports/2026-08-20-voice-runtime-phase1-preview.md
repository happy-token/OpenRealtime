# Phase 1 Voice Runtime Preview Gate — 2026-08-20

> Historical preview. Superseded by the
> [2026-08-21 passed live gate](./2026-08-21-voice-runtime-phase1-live.md).

Verification refreshed: **2026-08-21**.

Status: **PREVIEW**. Correctness/build gates are green, but GA statistical
evidence is intentionally not claimed.

## Verified evidence

- Python contract/integration suite after gated legacy source deletion and M5 collector hardening: `947 passed, 44 skipped`.
- Frontend unit suite: `89 passed`.
- TypeScript: `tsc --noEmit` passed.
- Next.js production build passed.
- Playwright with installed Google Chrome: `6 passed, 1 live-provider scenario skipped`.
- The Chrome v2 media test covers cumulative input ACK, negotiated/effective
  capture constraints, same-Session capture-graph rebuild with a fresh input
  epoch, resume hello after physical disconnect, and reconnect quality emission
  only after the resumed Session reaches `ACTIVE`.
- The release script allocates an isolated E2E port, requires Chrome in strict
  mode, and refuses release without a Passed statistical evidence report.
- v2 startup and recovery are guarded by `VoiceSessionRuntime`; matching
  `VoiceSessionReady` follows model-context restoration and input epoch readiness.
- v2 detached sessions do not replay raw text/audio frames.
- v2 resume authenticates transport identity, rotates detached-only tokens,
  restores a bounded event tail or semantic Snapshot, and falls back to a
  re-authorized Session Continuation after the recovery deadline.
- Process-wide Admission and the five-second fast-resume/quiesce policy bound
  live Session, Provider, memory, event-loop and audio-queue resources; process
  shutdown drains Voice Sessions for at most 15 seconds.
- Admission accepted/rejected/released decisions and resource-pressure reasons
  are available through content-free Session diagnostics without making
  telemetry availability part of the admission critical path.
- Model history uses the budgeted checkpoint projector; fixed 8-message / 4000-character
  truncation is no longer in the Cascaded answer path.
- A deterministic 200-turn/400-item context test verifies that the latest turn
  survives compression without reintroducing hidden truncation.
- The obsolete Kernel, Pipeline Conversation Engine, Response Scheduler,
  Speaking Clock, and old Application turn/tool-action coordinator paths are
  deleted; reusable streaming/tool-result/latency capabilities now live under
  Realtime/Observability.
- Strict JSONL evidence can now be converted atomically into grouped JSON and
  Markdown reports; synthetic, Chrome-only, duplicate, or per-Profile undersized
  evidence cannot produce `PASSED`.
- The diagnostics collector exports terminal Turn evidence into that JSONL,
  requires capture-epoch evidence, requires a Provider Call before accepting a
  `live` label, and writes an adjacent invocation manifest. It rejects malformed
  correctness violations instead of converting a missing code into evidence.
- A 2026-08-21 real-provider smoke passed all seven opt-in provider checks:
  Doubao direct TTS (one-shot, streaming and duplex), synthesized speech through
  Doubao ASR, and DeepSeek streaming/EOT/interruption requests. A separate real
  Chrome Voice Session smoke completed two text-injected Cascaded Turns with zero
  recorded errors/timeouts and zero playback underruns. DeepSeek provider calls
  were 721/892 ms, TTS first-audio spans were 900/1058 ms, and total Turn spans
  were 1126/1316 ms in that single run.

## Outstanding statistical evidence

- Real Cascaded Provider/Profile attempted full turns: **0 / 200 recorded for this report**.
- The two Chrome smoke Turns are deliberately excluded from that denominator:
  they exercised real Voice Session, DeepSeek and Doubao TTS, but used text
  injection rather than microphone audio through ASR. The real Doubao ASR check
  remains separate component evidence, so neither is mislabeled as a full Turn.
- The v1 `audio_chunk` compatibility adapter and the remaining React Hook
  compatibility implementation are retained until the real Profile quality
  gate passes and the remaining client migration closes;
  they are not production-primary paths and have not been declared deleted.
- Weak-network, device-change and provider-failure distributions have deterministic
  contract coverage, but no real-service grouped p50/p95 corpus yet.

Running 200 real provider turns can incur external API cost and requires an explicit
release profile/credential choice. Until that run is authorized and its grouped
report satisfies `VoiceRuntimeQualityGate`, this build remains Preview even though
the deterministic correctness gate is green.
