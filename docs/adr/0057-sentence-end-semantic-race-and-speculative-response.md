---
status: accepted
---

# ASR sentence-end, semantic activity race, and speculative response reuse

The effective state machine, timeouts, failure behavior, and operating guide
are maintained in [Semantic EoT](../SEMANTIC-EOT.md).

## Context

The prior audio path was serial:

`VAD silence → await semantic classifier → commit turn → start LLM → TTS`

That shape had three concrete problems. First, Doubao's bidirectional streaming
WebSocket already returned incremental/final recognition, but
the adapter reduced it to one mutable string and hid its `definite` sentence
boundary. Second, `ConversationKernel` awaited the semantic LLM inside its
frame loop, so the very signals that should invalidate an incomplete endpoint
— new VAD speech and a newer ASR hypothesis — could not be observed until the
decision had already completed. Third, the response LLM started only after the
semantic wait, leaving independent work serialized on the latency-critical
path.

This ADR adopts the useful VoiceLoop interaction shape without taking its
Pipecat wrapper: ASR endpoint observations, semantic confirmation, and
speculative response generation are separate modules connected by narrow
interfaces.

## Decision

### 1. One ASR WebSocket per logical voice session

`ConversationKernel` opens `AsrEngine.start_session()` on the first audio frame
of an active microphone session. It does not open the vendor socket merely
because the page WebSocket connected: the real Doubao endpoint ends a socket
that receives no audio, so page-level preconnection adds cost without creating
a usable warm session. Once audio starts, the returned `AsrSession` is reused
across utterances while the microphone continues streaming. It is restarted if
`is_alive` becomes false and closed when the logical session ends.

The browser defaults to full-duplex microphone upload, including while
assistant audio is playing. Echo cancellation and noise suppression remain
enabled, and playback-state/VAD policy decides whether detected overlap is a
barge-in. This keeps the ASR stream fed and lets it observe user speech during
assistant output. If the operator disables “允许随时打断”, microphone upload is
intentionally paused during playback; the server then lazily restarts ASR on
the next audio frame if the provider closed the idle socket.

Doubao defaults to the bidirectional streaming endpoint
`wss://openspeech.bytedance.com/api/v3/sauc/bigmodel`. This is a WebSocket
stream, not the submit/query recording-file API. Its endpoint window is 300ms
by default in the live adapter. The measured endpoint choice and the optional
`bigmodel_async` override are documented in
[ADR-0058](0058-doubao-bigmodel-asr-default-and-latency-baseline.md).

### 2. Normalize provider state through `AsrSnapshot`

Every built-in ASR session exposes:

| Field | Meaning |
|---|---|
| `text` | Current transcript accumulated for the active user turn |
| `revision` | Monotonic counter advanced when recognized text changes |
| `sentence_end_revision` | Revision finalized by the provider |
| `supports_sentence_end` | Whether the adapter has a real provider-final event |

Doubao maps `result.definite` or an utterance-level `definite`; Bella maps
`SentenceEnd`. Provider events are observations, not direct Turn Policy
transitions.

The live path uses `LlmEotClassifier` directly. Provider-added punctuation is
not a semantic shortcut, and the older punctuation ensemble is not part of the
demo composition. The model returns a structured decision with confidence and
an optional stability wait. The Gate owns the hard deadline and degrades model
errors to a bounded `UNCERTAIN` hold rather than silently treating them as
complete.

### 3. Require both semantic and stop latches without blocking frame intake

`SemanticEndpointGate` receives an immutable `EndpointCandidate`, an
`EndpointActivity` signal, and a resettable `EndpointStop` latch. SentenceEnd
starts classification and speculative response generation, but never commits
by itself. The task keeps running independently of the audio intake loop.

The state rules are:

| Current state | Event | Result |
|---|---|---|
| Listening | New provider `sentence_end` revision | Start one semantic candidate and one speculative response; do not commit |
| Semantic pending, classification in flight | VAD reports speech | Invalidate as `vad_speech`; cancel/discard speculation; continue the same utterance |
| Semantic `COMPLETE`, revision unchanged | VAD reports speech | Retain the semantic result and speculation; reset the stop latch and commit the original revision after fresh ASR idle |
| Semantic pending | ASR revision changes | Invalidate as `asr_increment`; cancel/discard speculation; continue the same utterance |
| Semantic pending | VAD stop | Satisfy the acoustic stop latch; wait for semantic result if needed |
| Semantic pending | ASR unchanged for 1000ms | Satisfy a synthetic `asr_idle` stop latch |
| Both latches ready | Semantic `COMPLETE` and revision stable | Commit `USER_EOT_CONFIRMED` and route the turn |
| Both latches ready | Semantic `INCOMPLETE` | Keep the turn open for activity, force-commit only after a stable 5000ms cap |
| Both latches ready | Semantic `UNCERTAIN` | Wait the model hint or 300ms default, then commit only if still stable |
| Classifier timeout/error | Candidate stable | Treat as `UNCERTAIN`; never infer `COMPLETE` from an operational failure |

Each candidate is semantically classified once. The system then waits for
activity or the appropriate stability deadline; it does not poll the model
every 300ms until it changes its answer. A semantic hold keeps the speculative
response buffer alive. Transcript activity discards it; VAD-only activity also
discards it while classification is pending, but preserves an already-complete
result for the unchanged revision until the next idle stop.
This preserves low latency without creating duplicate semantic or main-response
tasks.

VAD stop can arrive before or after SentenceEnd. If a provider final never
arrives, VAD stop judges the latest transcript; if acoustic stop never arrives,
the revision-bound ASR-idle timer provides a bounded fallback. Adapters compiled
against the older ASR contract retain the same VAD candidate path.

### 4. Start the main response once and reuse its stream

`SpeculativeStreamingBrain.prepare(TurnContent)` starts the ordinary local
conversation LLM immediately for a sentence-final candidate. Deltas are held
in a per-session buffer. When semantic confirmation commits the same
`generation + text`, `PipelineConversationEngine` calls `stream()` and receives
the already-buffered prefix followed by live deltas from the same producer.
It never issues a second LLM request for that key.

If VAD speech, an ASR increment, a hook veto/transformation, or a stale
generation invalidates the candidate, the producer is cancelled and its
buffer is discarded. A later sentence-end revision creates the new, latest
candidate. This makes “take the latest prepared response” precise without
allowing old text to leak into a newer turn.

Speculation is enabled only for the default side-effect-free Chat Brain. The
tool-calling Brain is excluded because speculative tool execution needs its own
prepare/commit protocol; starting external side effects before endpoint commit
would violate the tool policy boundary.

## Interfaces and ownership

| Module | Owns | Does not own |
|---|---|---|
| ASR Adapter | Vendor connection, transcript/final event normalization | Dialogue transition or semantic policy |
| VAD Adapter | One-pass speech measurement and acoustic signals | Transcript meaning |
| Semantic Endpoint Gate | Semantic/stop dual latch, classifier deadline, activity cancellation | Provider wire format, response delivery |
| Speculative Streaming Brain | LLM request deduplication and delta buffer | Turn commit, tools, TTS |
| Conversation Kernel | Module composition and Generation checks | Provider-specific logic |
| Pipeline Conversation Engine | Committed text/audio streaming and TTS handoff | Deciding whether user finished |

`VadObservation` exposes measurement and signal from one model inference, so
the Kernel can test `is_loud` during a semantic wait without running recurrent
Silero twice on the same PCM chunk.

## Verification

Tests pin the following outcomes:

- Doubao partial/final frames advance transcript revisions and surface the
  finalized revision.
- VAD speech wins the race against a blocked classifier and cancels it.
- SentenceEnd alone cannot commit before VAD/ASR-idle stop.
- `INCOMPLETE` is classified once, held for activity, and force-committed only after its timeout.
- `UNCERTAIN` preserves the model wait hint; classifier failures use the bounded uncertain path.
- Repeated `prepare()` for one key starts exactly one underlying Brain stream.
- A committed turn replays buffered deltas and follows the same live response.
- A VAD continuation cancels an in-flight semantic candidate. If classification
  is already `COMPLETE` and ASR produces no new revision, the original candidate
  and prefetched response survive until a fresh ASR-idle stop commits them.

## Consequences

Semantic classification, stop detection, and response generation now overlap,
and none blocks audio intake. On the normal path, the 300ms VAD window is the
stop latch; the 1000ms ASR-idle path is a recovery mechanism, not an added delay
after every SentenceEnd. The remaining first-audio bottleneck is normally the
main LLM/TTS first-chunk path rather than a serialized semantic wait.

The design intentionally does not claim that it reproduces private GPT Voice
internals. It implements the observable low-latency contract documented in
this repository: revisioned input events, cancellable generation, streaming
text, and streaming TTS behind provider-neutral interfaces.
