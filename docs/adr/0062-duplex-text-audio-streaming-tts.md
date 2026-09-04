---
status: accepted
---

# Duplex text-input and audio-output TTS

The live Conversation Engine previously converted LLM SSE output into fixed
12-character and 24-character segments. Each segment called
`synthesize_stream(text)`, creating a new provider synthesis Session before
audio could arrive. The output was audio-streaming, but text input was not.

Volcengine's official bidirectional TTS protocol accepts repeated
`TaskRequest` events in one Session and emits `TTSResponse` audio frames while
input is still open. The provider lifecycle is therefore:

`StartSession → TaskRequest × N ⇄ TTSResponse × M → FinishSession`.

We add a small `DuplexStreamingTtsEngine` interface at the speech seam:

```python
def synthesize_duplex(
    text_stream: AsyncIterator[str],
) -> AsyncIterator[SynthesizedAudioChunk]: ...
```

This is intentionally a deep module. Callers know only the two streams; the
Doubao adapter owns session framing, concurrent send/receive, connection reuse,
provider failures, and cleanup. `PipelineConversationEngine` forwards every
non-empty Brain delta without fixed character batching. The adapter sends
`FinishSession` only after the text iterator ends.

Cancellation closes both directions. If a barge-in, timeout, or provider error
ends a Session before `SessionFinished`, the adapter closes the text iterator
and discards the WebSocket so unread frames cannot leak into the next turn.
Duplex timeout is measured as maximum idle time between audio chunks, not total
response duration, so a healthy long response is not cut off after ten seconds.

`StreamingTtsEngine.synthesize_stream(text)` remains for legacy schedulers and
non-duplex adapters. The Pipeline selects duplex capability when the adapter
exposes it; the direct Doubao adapter is the production conformer.
