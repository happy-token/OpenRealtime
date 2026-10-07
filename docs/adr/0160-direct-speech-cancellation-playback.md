# ADR 0160: Propagate direct speech cancellation to its original playback

Date: 2026-10-07
Status: Accepted for the direct-cancellation WebAudio increment only.

## Problem

The speech lifecycle emits `SpeechCancelled` after an actual `CancelSpeech`, but the WebSocket Bridge only mapped response cancellation to output stop. Direct/manual/external speech could therefore stop generation while already queued browser audio continued. A new input can cancel an older speech using its newer execution generation; that generation cannot identify the audio to stop.

## Decision

Map `SpeechCancelled` to the existing output-stop protocol using the retained original playback context, generation and speech identity. Require the same tenant/user/device/Voice Session/thread scope. Unknown speech and foreign scope do not affect playback. Precise controls target the old speech; legacy generation-only controls cannot stop an old speech after replacement on the same generation. Repeated legacy cancellation is ignored. Preserve the existing current-sentence permit for `barge_in_floor_claim`; other direct cancellations are immediate. Reuse existing stop facts, receipt deadlines, delivery gates and telemetry; add no actor, state machine, storage table or production default.

## Verification

Use actual speech lifecycle commands in the Bridge regression, including old/new input generations, five foreign-scope identities, redelivery and late PCM before generation completion. Add a same-generation A→B→late cancellation of A regression for both precise and legacy modes. The initial two direct-cancel cases failed because no stop frame reached the wire; the final six cases pass.

Extend the opt-in loopback renderer fixture with normal, stop, missing-receipt and disconnect scenarios. Each uses a fresh owned PG login schema and isolated Next3029. The production browser generates its own receipt. Fault scenarios drop only the real stop receipt on the wire; stop scenarios leave audio generation incomplete so late-audio rejection is specifically tested after cancellation. Compare saved stop facts, canonical playback, native WebAudio buffers, received PCM, full sent WAV, Settings projection and the no-Cookie exact-Session Agent endpoint. The unified diagnostics endpoint distinguishes confirmed stop spans from unknown/failed handoff.

See the [report](../reports/2026-10-07-direct-speech-cancellation-playback.md) and [reproduction guide](../guides/recording-browser-integration.md).

## Limits

This is a local controlled-provider WebAudio proof, not physical sound, semantic correctness or the full renderer/provider matrix. Stop-request→receipt is not user effective-interruption onset→stop (LAT02). Recording is Memory-backed; PG supplies identity only. All original OBS02/03, G0–G5, durable unknown-action, real JEV fairness/paired latency and S3/deployment acceptance remain open.
