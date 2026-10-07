# Production browser recording/receipt verification

2026-10-07, continuing after `3a3caf5`. Local commit authorized; no push, running user-service restart, production migration, provider request, S3 request or secret/default flag change.

## Finding and fix

The new actual Chrome `/conversation` test first uncovered a fixture initialization issue: the page recreated an empty connection, but the fixture permanently rejected every subsequent connection. Removing the administrator Cookie did not fix it. Captured evidence showed two connections; the fixture now permits only an empty, fully settled predecessor to be replaced, while preserving ownership after scenario start or cleanup failure. The final browser test uses the administrator Cookie for Settings access and no Cookie for the Agent read.

Once the actual playback ran, the browser reported 6401 samples for two 3200-sample chunks. Its empty terminal marker was scheduled as a one-sample WebAudio source and incorrectly contributed to the speech-local clock. The actual Bridge canonical event already limited that receipt to 6400. Two formal regressions at 16k and 24k failed with `played_position_samples: 6401` versus expected `6400`; the focused command completed in 405ms. The fix excludes empty PCM from `playedSegments`, preserving the terminal source and completion callback.

## Verified evidence

The isolated fixture uses actual Memory Application Runtime, recording worker, speech lifecycle, parser, Bridge, observer and private HTTP. Real local `/tmp` PostgreSQL supplies only the owned administrator login schema. Playwright starts and stops its own Next on 3029. The production hook and WebAudio graph run unmodified apart from the clock fix; browser socket/audio wrappers observe real operations and redirect the wire to the loopback fixture. SpeechRecognition is controlled, and input recording is pre-seeded synthetic PCM.

The final actual Chrome test passed in 19.6s (27.7s including server setup). Its artifact `recording-renderer.json` records:

- Two accepted initialization connections, one started scenario; actual cleanup completed, no backend/page/cleanup errors.
- Browser receipts: started0, playing1621/3243/4779/6400, finished6400; intermediate positions depend on the actual audio clock and are not hard-coded assertions.
- Canonical events preserve original `fixture-renderer-output`, `fixture-speech`, generation0, rate16000 and positions, with final `completed=true` at6400.
- Real WebAudio PCM sources last0.2s each, are scheduled contiguously, and their entire native buffers are uniform +1000/32768 and -1000/32768. The empty terminal source remains 1/16000s and contributes no PCM position.
- Settings displays `回执覆盖 0.400 / 0.400 秒`, with exact6400/6400 sample tooltip and its physical-output limitation.
- No-Cookie exact-Session Agent GET returns one normalized sent row (`stream_id=speech_id`), 6400samples, reported endpoint/overlap6400, `playback_confirmation=not-inferred`. Agent preservation POST is403.
- The verified WAV is12844bytes, SHA256 `80ad62547b87b618bd5b9afd174f624ae7393fa61e478af8be9bcfbec1389a3b`. Every saved PCM byte equals both the known ordered two-chunk fixture and the actual browser incoming wire PCM.

Independent review found two fixture faults and they were corrected: a cleanup failure could release ownership without a failure latch, and browser `finally` evidence retrieval could replace the original assertion failure. Formal actual-loopback tests now cover cleanup-error1013 rejection and permitted empty settled replacement. A separate reviewer Memory gated-upload probe verified a pending recorder remains Runtime-owned after close timeout, and reconnect is denied until it settles; this probe is not a new provider/deployment acceptance claim.

## Validation and limits

- Full Vitest:1428passed,7skipped,24.13s.
- Related Python Bridge/recording/anchor/fixture tests:57passed,1.09s; fixture ownership subset2passed,.31s.
- Playback/control subset:48passed,.422s; independent reviewer48passed,.360s.
- TSC, scoped ESLint/Ruff and two fixture Mypy (`--explicit-package-bases --follow-imports=silent --ignore-missing-imports`) pass.
- Existing controlled receipt/WAV preservation and preview Chrome regressions:2passed16.6s, using a separately recreated default-mode fixture. Both fixture processes exited0; all six owned schema absence checks passed. Generated Next route paths were inspected and restored.
- The browser test is opt-in and does not replace the previous controlled receipt/WAV preservation test. No repeat of the entire Python suite is claimed for this fixture/frontend increment.

This proves the normal production WebAudio receipt joins its original sent recording through the real local diagnostic chain. It does not prove physical sound/user hearing, full avatar renderer and interrupt/disconnect scenarios, end-to-end microphone completeness, real provider latency/JEV fairness, S3 durability or deployment/external Agent behavior. Original OBS02/03 and all G0–G5 remain open. The next original-scope work includes stopped/partial renderer recording evidence and the remaining input/fault/connection aggregation and real paired provider experiments.
