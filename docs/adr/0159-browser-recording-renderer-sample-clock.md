# ADR 0159: Verify recording evidence with the production browser renderer

Date: 2026-10-07
Status: Accepted for the local WebAudio recording/receipt increment only.

## Decision

Connect the actual `/conversation` page to an opted-in loopback WebSocket fixture using the production parser, `RealtimeWebSocketFrameBridge`, speech lifecycle and telemetry observer. The fixture supplies two distinguishable 200ms PCM chunks and an empty terminal marker; it never seeds a playback receipt. After the browser ends playback and leaves the conversation, read the actual recording through Settings diagnostics and the exact-Session Agent endpoint.

Keep the existing controlled-receipt fixture as its default mode. `RECORDING_BROWSER_RENDERER=1` selects the new fixture; it requires the existing isolated owned PG login schema and a separate 3029 Next instance. Provider audio and microphone input remain controlled, Memory recording remains volatile, and authentication is unchanged. The first empty connection may be replaced only after successful cleanup; starting the scenario or recording a cleanup error prevents another owner. WebSocket, HTTP, Runtime, owned schema and pool are independently cleaned up. Browser cleanup is bounded and cannot mask its primary assertion error.

The experiment exposed a production clock defect: `BrowserAudioOutput` scheduled a one-sample source for an empty final marker and also included that control source in `playedSegments`. Therefore 6400 transmitted samples produced a 6401-sample browser receipt, although Bridge correctly clamped its canonical event to 6400. Exclude empty PCM from the sample clock while retaining its source scheduling, stop handling and natural `onEnded` completion. No new business actor, queue, state machine or table is needed.

## Implementation and evidence

1. Add the actual socket/renderer fixture and exact original recording assertions.
2. Observe the actual Chrome receipt mismatch, then run two formal 16k/24k unit regressions red (6401 versus 6400).
3. Apply the small production clock fix; verify playback/stop regressions and actual browser chain green.
4. Verify incoming wire PCM, native AudioBuffer content and saved WAV bytes agree, and original epoch/speech/generation/sample identity survives the canonical event and public projection.
5. Record limited acceptance without closing the original OBS02/03 or G0–G5 gates.

See the [report](../reports/2026-10-07-browser-recording-renderer.md) and [reproduction guide](../guides/recording-browser-integration.md).

## Remaining scope

This closes the local normal WebAudio recording/receipt seam. It does not establish physical speaker output or user hearing, the full supported avatar renderer/interrupt/disconnect matrix, end-to-end microphone recording completeness, provider latency/load, S3/deployment persistence or external Agent acceptance. Original real JEV fairness and paired latency/accuracy, input/fault evidence, durable unknown-action handling and all full plan gates remain open.
