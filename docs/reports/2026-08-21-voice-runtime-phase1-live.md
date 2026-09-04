# Phase 1 Voice Runtime Live Gate — 2026-08-21

## Result

**PASSED.** The committed Cascaded Desktop Chrome release Profile contains
exactly 200 attempted full turns from the real browser microphone path and real
Doubao ASR → DeepSeek Brain → Doubao TTS provider chain.

| Metric | Result | Gate |
| --- | ---: | ---: |
| EOT accepted → client playback p50 | 635.7 ms | < 800 ms |
| EOT accepted → client playback p95 | 1035.8 ms | < 1500 ms |
| Abnormal terminal rate | 0.000% | < 0.5% |
| Correctness violations | 0 | 0 |
| Voiced-sample silent loss | 0 | 0 |

Environment: Chrome 151.0.7922.170, `desktop-web-phase1-v1`,
`cn-local`, ordinary-result group. Barge-in and reconnect latency are not
fabricated into this group; their deterministic/Chrome recovery contracts
remain separate, and these fields are `null` in the committed ordinary-turn
evidence.

## Evidence

- [Content-free 200-turn JSONL](./evidence/2026-08-21-phase1-live-200.jsonl)
- [Campaign manifest](./evidence/2026-08-21-phase1-live-200.manifest.json)
- [Machine report](./evidence/2026-08-21-phase1-live-200-report.json)
- [Human gate output](./evidence/2026-08-21-phase1-live-200-report.md)

The evidence retains opaque attempt/session IDs, Profile dimensions and
content-free timing/correctness counters. It excludes PCM, transcripts,
prompts, model tokens, credentials and Tool secrets. The raw ledger SHA-256 is
`e0ad457866769864bbe4695dda2c48cd00d6941f6a88cfc6115f57c645e48af5`.

## Replacement decision

This report satisfies the M5 statistical gate required by M6. The v1 inbound
`audio_chunk` parser/bridge/worklet and the old
`use-conversation-engine.ts` implementation were deleted after the replacement
contracts, Chrome E2E and this live Profile gate were green.
