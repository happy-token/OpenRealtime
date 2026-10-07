# ADR 0157: Correlate recording intervals with validated client receipts

Date: 2026-10-07
Status: Accepted for the local receipt projection increment; broader recording and renderer acceptance remains open.

## Decision

Preserve optional output epoch, exact played sample position and sample rate from ReportPlaybackProgress in SpeechPlaybackProgress and the existing telemetry event. Shared speech lifecycle, cascaded model speech and native model speech must all retain the same fields and phase flags. The event validates paired safe sample/rate fields, nonempty epoch, segment precision and agreement with rounded cumulative microseconds. Legacy or estimated positions stay unknown; no conversion from an imprecise microsecond clock into exact samples.

Recording metadata keeps `playback_confirmation=not-inferred`. A separate read projection can show the intersection of a saved sent interval with a matching reported client prefix. Match original tenant/user/Session/source thread, generation/turn/response, output epoch, speech and sample rate. Bridge recording uses the normalized speech-local cumulative clock and stream=speech; recordings lacking that attachment remain unknown. Never use admin identity, wall-clock proximity, sent bytes or playback completed to infer exact heard ranges. Input recordings have no output playback status.

Use one bounded telemetry page through existing DiagnosticsQuery and the recording owner's existing optional operation budget, keeping actual late IO owned. Evidence-source availability/truncation and collection health stay explicit. A found exact receipt is positive evidence of a reported prefix, including zero; a missing receipt is unknown even with no next page. A truncated page cannot establish total coverage or absence, and the Agent can continue raw telemetry pagination through its existing Session diagnostic endpoint. No claim that this bounded initial projection completes evidence collection or long-session lookup.

The initial page contains at most 5000 returned events. This limits projection input, not the underlying Memory adapter scan/sort or total query resources. Long-session targeted retrieval and its resource bounds remain a separate acceptance item. Source health and cursor status do not prove event completeness.

Implement the correlation as a stateless observability helper; do not add a playback actor, queue, delivery permission or recovery state. Public projection whitelists counts/source status; the existing recording panel shows numeric overlap with a tooltip explaining client reports are not physical speaker proof. Slow/error evidence must not hide valid audio or the independent preservation status. Signed admin/Agent read authorization remains ADR0153/0156.

## Implementation and acceptance plan

1. Formal red actual speech-lifecycle and recording-read tests; preserve and validate protocol/observer anchors across both engine styles.
2. Scoped receipt indexing and interval projection, missing/malformed/legacy/foreign identity and zero/partial/full/gap regressions.
3. Bound optional diagnostic IO in the same actual task ledger; unavailable/truncated/late/capacity regressions and real PostgreSQL read persistence.
4. White-listed public GET and themed numeric UI; isolated browser verifies real Bridge audio and precise receipts to the diagnostic projection. Preserve no-cookie Agent read and deny-write policy.
5. Review, controlled tests and document the actual scope. Real renderer/device oracles, evidence completeness/targeted long-session retrieval, S3/provider/deployment and all original OBS02/03/G0–G5 acceptance remain open.

## Local implementation evidence

All five local steps have been exercised. Actual speech lifecycle and recording-reader regressions first failed on lost anchors/missing projection; the native and cascaded model branches retain exact anchors and phase flags. The optional query shares the existing eight actual-task slots and a maximum 250ms wait within the root read deadline. A review-discovered child `CancelledError` initially cancelled the entire catalog; two formal regressions now verify independent policy/playback cancellation degrades only that source. Parent cancellation still retains actual IO ownership.

Real PostgreSQL tests verify stored JSON sample anchors and correct precise-versus-legacy projections after Runtime reconstruction. The isolated browser fixture uses a controlled wire sink with the actual Bridge, shared speech lifecycle, observer and Runtime. It sends 1600 samples and accepts a precise 800-sample client receipt. Chrome then verifies the public projection, numeric tooltip, native WAV replay and no-cookie Agent read. It does not produce an original production renderer receipt or physical device oracle. No user service or live provider is involved.

Validation and remaining scope: [implementation report](../reports/2026-10-07-recording-playback-receipts.md).
