# Session recording query, authorized access and replay entry

2026-10-07; continued explicit “commit, 继续未完成的” authorization.

## Delivered

Commit `397c0ad` implements [ADR0152](../adr/0152-session-authoritative-recording-read.md): Journal original Session/recording scope proof, paginated manifests and Artifact point lookup, controlled0037 index, exact index predicate validation, strict recording/source/owner/retention integrity and post-IO authority revalidation. Eight actual application reads retain ownership through caller timeout/cancellation and block purge/pool close; four metadata workers avoid serial200 round trips and are all joined before actual read settlement.

The following [ADR0153](../adr/0153-authorized-session-recording-api-and-player.md) integration connects production runtime readers to private HTTP/CLI/demo, admin/exactSession grant public catalog/audio routes and a same-theme diagnostic replay entry. Unified GET advertises an independent catalog URL without claiming it has queried audio. Agent bundles include catalog pagination and protected audio access instructions. A single selected segment uses native controls with no preload/autoplay. Missing metadata, expiry/deletion, incomplete catalog and volatile storage remain visible.

## Corrected during review

- Private recording routes initially lacked loopback Host/Origin guards. Actual Runtime HTTP malicious Host/Origin requests reproduced200; guards now403 before invoking readers. Loopback/noOrigin backend calls remain valid.
- Enum validation coerced JSON arrays with String(), admitting malformed rows. Exact string type guards and raw route regressions now reject them.
- Early source/header/body-length failures initially left the upstream response body unread. All paths now issue best-effort cancellation without waiting on noncooperative cancellation completion; formal stream tests verify it.
- Serial metadata queries were changed to four fixed joined workers, preserving original sequence and actual task ownership. Formal red/green regression confirms four simultaneous reads and output order; reviewer error+blocked-peer probe confirms no early release.
- Two new HTTP Future-variable type collisions were removed; existing18HTTP Mypy failures remain baseline, not reported as globally green.

## Validation

- Full Python: 2615 passed,90 skipped,3 subtests;70.92s. Includes new8reader/12query/actualRuntimeHTTP and existing regression suite. Skipped tests include provider/PG opt-ins.
- Real localPG16/tmp randomized schemas:21 passed2.45s (newQuery2/index-predicate2/schema render1,Journal15,default recording1); fixture-only cleanup, not a production migration or actual S3.
- Full Vitest:1381 passed,7 skipped;19.62s. A subsequent additional exactSession Agent audio regression was verified in final39 route tests;3 controlled-hook UI regressions cover duplicate clicks, continuation retry, player removal on refresh and cancelled late responses. These additions were verified separately, not represented as a repeated full suite.
- Isolated3028 actualChrome desktop/mobile preview:1 passed9.3s. It verifies themed entry and no private/audio reads; does not verify live playback. Generated Next config changes were inspected/restored, user3010/8765/8766 unchanged.
- TypeScript noEmit, scoped ESLint/Ruff/diff, four core query/owner/reader Mypy checks pass. Two existing reviewers gave limited APPROVE for core/privateAPI and publicAPI/UI. The UI reviewer additionally drove duplicate-click, failed continuation/cursor retry, refresh-player removal and late-response fencing with controlled hooks.

## Remaining

No real S3/provider call, production migration, credential configuration, user service restart or push. Existing Sessions are not backfilled; production deployment and actual admin/externalAgent/browser-audio acceptance remain open. Session preservation controls, confirmed renderer epoch/speech/sample joins and complete recording evidence remain OBS03 work. SDK corruption peak memory is not bounded by the response cap. OBS02 input evidence aggregation/fault causal dedup/coldwarm reconnect, original G0 marked real audio/oracle, G1 realJEV fairness/budgets/paired latency-accuracy, G2 durable unknown-action reconciliation, G3/G4 full correction/handoff/fault/renderer matrices and G5 realprovider/load experiments remain open. Whole plan is not complete.
