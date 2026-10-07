# Direct speech cancellation and actual WebAudio fault evidence

2026-10-07, continuing after `5ecd516`. Local commits authorized; no push, production migration, user-service restart, provider/S3 call or secret/default change.

## Finding and fix

Actual `StartSpeech`/`AppendSpeechText`/`CommitSpeech` then `CancelSpeech` produced `SpeechCancelled`, but Bridge ignored that event. Two formal precise/legacy cases first failed with zero stop frames, despite audio already being sent. The production fix maps the terminal event to the existing stop protocol with the original output identity and five-dimensional scope check. New input generations do not replace the old audio generation. Legacy controls skip an older speech when a new speech has replaced it on the same generation, and ignore duplicate cancellation.

The final six formal tests cover old/new input cancellation, actual canonical stop/fact confirmation, unknown/foreign target rejection, duplicate delivery, late audio, and same-generation A→B→late-A cancellation preserving B. The four direct-cancel cases exposed a duplicate legacy stop during expansion; the guard fixed it. A temporary missing test import caused NameError and was corrected; that was an editing failure, not a production finding.

Independent review found the first browser late-audio oracle insufficient: the fixture had already completed generation, which alone rejects late audio. Stop/fault scenarios now keep generation incomplete. Fresh four-mode Chrome runs use that corrected fixture. Initial successful runs are superseded for this late-audio claim.

## Actual browser matrix

Each mode used a newly created owned schema, actual Memory Application Runtime, speech lifecycle/shared stop store, Bridge/parser, recording worker and observer, real loopback WebSocket/private HTTP, production `/conversation` hook and native WebAudio, Settings diagnostics and a no-Cookie Agent. Only provider PCM/microphone recognition are controlled. The browser does not fabricate playback or stop receipts.

|Mode|Browser case / total setup time|Actual evidence|
|---|---|---|
|Normal|8.5s / 12.9s|6400 samples finished/canonical; Settings0.400/0.400s; no stop operation|
|Stop|10.1s / 15.2s|Two native sources stopped; browser/canonical/store confirmed2048 samples; reported2048/64000; one requested/receipt/handoff-ready operation|
|Missing receipt|8.5s / 12.9s|Real browser stopped1792 samples, receipt deliberately not sent; store STOP_UNKNOWN with no stop position; prior positive canonical prefix1707/64000 only; deadline failure and user-visible recovery message|
|Disconnect|8.6s / 13.5s|Real browser stopped1877 samples, receipt deliberately not sent then socket detached; store STOP_UNKNOWN with no stop position; prior positive canonical prefix1877/64000 only; transport-detached failure|

Intermediate clock positions vary by run; assertions derive from actual canonical/receipt evidence, not these example constants. All non-normal modes received only the two unfinished audio chunks; late1600-sample PCM was rejected and never appeared in sent WAV or browser frames. Full4s sent audio remains64000 samples/128044bytes in each stop/fault case; SHA256 `8e1e2dc6f4c907e174ab3948ad79cd2a0406d51cec0ba4d8e0029acc30c1c161`. Saved PCM equals ordered ±1000 chunks and actual incoming wire PCM; native buffers and scheduling are independently checked. Normal WAV remains12844bytes with the prior6400-sample hash.

The actual unified Agent diagnostics GET records exactly one stop request. Successful stop has one receipt and a2.679ms request→receipt span plus3.638ms request→handoff span. These single local command spans are not semantic interruption latency, a provider average or P95. Missing/disconnect have timeout/error handoff events and no successful stop-receipt span. Saved unknown facts do not invent a stopped/completed canonical event or inferred endpoint. Settings retains the last genuinely reported prefix, even when it happens to equal the locally observed stop position. Agent preservation POST remains403; collection health is not exposed.

Artifacts are in `/tmp/voiceagent-{normal,stop,missing,disconnect}-renderer-matrix-20261007/`, with browser/backend/catalog/unified diagnostics evidence. Matrix process metadata and owned-schema cleanup checks are in `/tmp/voiceagent-renderer-matrix-20261007.json`. They are local run artifacts, not checked-in semantic oracles. All four fixture processes exited0 and owned schemas were absent afterward. Disconnect logged the expected failed attempt to notify an already closed socket; backend cleanup and recording settlement still succeeded. Other backend/page/cleanup errors were absent.

## Validation and remaining scope

- Full Python snapshot:2701 passed,111 skipped,3 subtests,62.66s. Collected before the additional two replacement tests; final direct-cancel subset6 passed.19s.
- TSC, scoped ESLint/Ruff and explicit-package-base Mypy3 sources passed. An initial Mypy invocation without the required package mapping was corrected; no source change was needed.
- Independent reviewers: Python34 and transport48 regression subsets passed; limited approvals include source/fixture/scope and honest fault evidence. They do not claim independent Chrome execution.
- Four fresh actual Chrome modes passed; no production TypeScript source changed in this batch, so the unchanged previous1428-pass Vitest result is not reported as a fresh run.

This accepts the local direct-cancel/partial/unknown WebAudio recording seam. Physical output/hearing, all avatar renderers, true microphone completeness, semantic effective-interruption latency, durable deployed recording/S3 and real external Agent acceptance remain open. Original OBS02 input aggregation/causal fault dedup/cold-warm reconnect, marked G0–G5 oracles, true JEV fairness/global wait/history budgets and paired latency/accuracy, durable unknown-action handling, general supplement/manual/model-delivery and noncooperative/provider/load matrices remain at their original scope.
