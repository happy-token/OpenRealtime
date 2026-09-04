---
status: superseded by ADR-0063
---

# Make Conversation Engine output end-to-end streaming and cancelable

**Implemented and live in the Voice Web Demo:** `server/conversation_engine/`
defines the typed, ordered action stream, cooperative cancellation token, bounded
Pipeline Engine, sentence segmentation, streaming TTS handoff, and latency
milestone trace. `ConversationTurnCoordinator` now connects accepted local turns
to this Engine from `ConversationKernel`, writes the accepted user item before
Engine dispatch, streams cumulative text and audio frames through the current
Generation lease, and coalesces the terminal assistant item into Conversation
Journal. `ChatBrain` preserves native LLM deltas, and the OpenAI-compatible client
exposes provider SSE chunks rather than accumulating the full answer first.

The Pipeline Engine's canonical fast-tool continuation is also implemented:
`ToolCallingBrainStreamingAdapter` emits a versioned `CallToolAction`, the
Coordinator delegates it to the application Tool Action Handler, and correlated
`ToolResultFeedback` resumes the same response after the Policy Gateway/Fast
Tool Loop has journaled the outcome. Active tool handlers receive Generation
cancellation. `DelegateTaskAction`, Native Realtime, RTC, and the interactive
confirmation decision/resume transport remain later increments.

Generation advances cancel the active Engine token. Engine invocations for one
Voice Session are serialized, so a superseded turn must exit before the next one
enters a stateful model/TTS pipeline; a queued turn that is already stale never
calls the provider. The browser replaces the current assistant transcript entry
for cumulative deltas instead of rendering one message per chunk. The legacy
Response Scheduler remains only as a compatibility path for delegated Agent
ack/results and error speech. Canonical `DelegateTask` action execution, Native
Realtime, and RTC remain later increments.

Conversation Engine resolves each accepted turn as an ordered, asynchronous Response Stream rather than returning one fully materialized reply. This is the common contract for both Native Realtime Engine and Pipeline Engine. It preserves GPT Voice / OpenAI Realtime's publicly observable incremental response behavior while giving OpenRealtime a provider-neutral interface that can also support Doubao and later engines.

This ADR expands ADR-0041 and ADR-0047. It does **not** claim that OpenAI's private implementation uses this exact Python interface or these internal type names. The alignment target is the published behavior and protocol surface: stateful realtime sessions, incremental server events, streamed audio/text deltas, correlated tool calls, continuation after tool output, and explicit interruption.

## Public evidence and inference boundary

OpenAI's public documentation establishes the following observable facts:

- Realtime is a stateful, event-driven session. Applications send client events and consume server events.
- WebSocket sessions deliver audio in `response.output_audio.delta` events; output text and audio transcripts also have delta events.
- Function calls have a `call_id`; the application executes the function, adds a `function_call_output` item, and requests response continuation.
- Interruption can cancel a response. WebRTC/SIP sessions have server-managed output buffering and truncation; WebSocket clients must stop playback and manage unplayed audio themselves.
- The Voice Agents guidance exposes both speech-to-speech Realtime and a chained speech-to-text → agent → text-to-speech architecture. The published Python chained example consumes generated audio through an asynchronous event stream.
- Sideband server connections let application servers monitor a Realtime session, update it, and handle tools while business logic remains server-side.

The following are OpenRealtime design choices inferred from those behaviors, not claims about OpenAI internals:

- one canonical asynchronous iterator for both engine forms;
- the exact Conversation Action type names below;
- sentence/semantic segmentation in Pipeline Engine;
- bounded internal queues and our backpressure policy;
- the division of responsibilities among Conversation Kernel, Engine, Output Scheduler, and provider adapters.

## Contract

Conceptually, a conformer provides:

```python
class ConversationEngine(Protocol):
    def respond(
        self,
        turn: TurnInput,
        *,
        context: InteractionContext,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ConversationAction]: ...
```

The concrete Python signature may evolve during implementation, but the behavioral contract is fixed:

1. `respond` returns without waiting for the whole model response or synthesized utterance.
2. Actions are emitted in deterministic per-response sequence order.
3. Every action carries Interaction Context plus `response_id` and action sequence; correlated actions also carry `call_id`, `worker_id`, or `confirmation_id`.
4. The stream has an explicit start and exactly one terminal outcome: completed, cancelled, or failed.
5. Cancellation is cooperative end to end. A conformer must stop upstream generation and synthesis when supported, close its producers, and emit no further user-visible output for a stale Generation.
6. Empty or broken provider streams end as explicit failure, never silent success.

The initial canonical action families are:

| Family | Representative actions | Meaning |
|---|---|---|
| Lifecycle | `ResponseStarted`, `ResponseCompleted`, `ResponseCancelled`, `ResponseFailed` | Delimit one response attempt and its terminal outcome |
| User-visible output | `TextDelta`, `AudioDelta` | Incremental text and playable audio, with media metadata and sequence |
| Fast work | `CallTool` | Request one bounded, correlated Canonical Tool call |
| Background work | `DelegateTask` | Start one named-Agent Delegated Task without holding the voice turn open |
| Safety | `RequireConfirmation` | Suspend a sensitive action until a correlated decision event arrives |
| Session | `EndSession` | Request graceful end of the Voice Session |

`Speak` remains a semantic convenience at the model/engine boundary only if needed. Before transport delivery it must become incremental `TextDelta` and/or `AudioDelta` actions so that scheduling and cancellation have one observable contract.

## Native Realtime Engine mapping

The Native Realtime Engine does not insert a separate ASR/LLM/TTS pipeline. Its adapter maps provider events into canonical actions as soon as they arrive:

```text
provider response created       -> ResponseStarted
provider output text delta      -> TextDelta
provider output audio delta     -> AudioDelta
provider function call complete -> CallTool
provider response done          -> ResponseCompleted or ResponseFailed
provider cancellation/error     -> ResponseCancelled or ResponseFailed
```

Provider-specific item IDs remain boundary metadata when useful for protocol continuation; core correlation uses the canonical IDs in Interaction Context. Audio deltas are passed through without waiting for a sentence or a complete response.

When the Engine emits `CallTool`, the Application Control Plane dispatches it through the Fast Tool Loop. Completion returns as correlated `ToolResultFeedback`; the Engine adapter consumes that feedback through the provider's function-output mechanism and resumes response generation. Application policy, not the provider adapter, remains the authority for budgets, permissions, ordering, and cancellation.

## Pipeline Engine mapping

Pipeline Engine preserves streaming across every stage:

```text
streaming ASR / accepted turn
        -> incremental Brain output
        -> speakable-segment boundary
        -> streaming TTS
        -> AudioDelta
```

It must not wait for the full Brain response before starting TTS. A Sentence Segmenter (the implementation name may change) turns token deltas into speakable segments using punctuation/semantic boundaries plus a bounded maximum wait. It may buffer enough text to avoid unnatural fragments, but not the complete answer. Each completed segment enters TTS immediately while later text is still being generated.

Pipeline Engine must preserve two independently useful outputs:

- text deltas, for captions, audit, and clients that can render text early;
- audio deltas, for playback as soon as the first synthesized bytes are available.

TTS connection setup, synthesis, and transport send are separate timed milestones. A reusable streaming TTS session is preferred when a provider supports it; the unified contract does not require a specific vendor transport.

## Permitted buffering

"End-to-end streaming" does not mean zero buffering. The following bounded buffering is allowed:

- ASR endpointing needed to accept a user turn;
- a short text window needed to produce a natural speakable segment;
- fragmented structured tool arguments until the provider marks the call complete and the arguments parse against the Canonical Tool Schema;
- a small bounded audio jitter/prebuffer controlled by the Transport Adapter or client;
- bounded queues required for backpressure.

It is forbidden to accumulate an entire ordinary LLM reply, entire synthesized utterance, or unbounded provider event history before exposing the first useful output.

## Ordering, backpressure, and completion

- Per-response action sequence is monotonic. Concurrent Delegated Tasks have independent sequences and are correlated by `worker_id`; completion order is not creation order.
- Producers write through bounded queues. When a consumer slows down, producers await capacity or apply an explicit media-specific drop policy; they never grow memory without bound.
- Control actions and cancellation outrank queued future audio. Stale audio is discarded before transport delivery.
- `TextDelta` completion, provider response completion, TTS completion, transport send completion, and physical playback completion are distinct milestones.
- `ResponseCompleted` means the Engine will produce no more actions for that response. It does not claim the user has heard all audio. Client playback completion arrives separately as a Voice Event.

## Barge-in and supersession

A confirmed Barge-in advances Generation and cancels the active Response Stream:

1. Conversation Kernel invalidates the old Generation lease.
2. Output Scheduler immediately stops accepting its queued text/audio deltas.
3. Native Realtime Engine requests provider cancellation and, where the transport requires it, output-buffer clear/truncation.
4. Pipeline Engine cancels Brain and streaming-TTS producers and closes their iterators.
5. Already completed background Delegated Tasks remain available; active background tasks continue unless explicitly cancelled by `worker_id`.
6. Late deltas may still arrive from external systems, but Generation checks make them observationally inert.

This replaces the old operational assumption that turn tasks should never be cancelled. The Generation lease remains the final safety boundary, while cancellation now also propagates upstream to avoid wasted compute and reduce interruption latency. ADR-0036's safety invariant remains: only output holding the current lease can affect the user.

## Observability and acceptance metrics

Every response records at least these monotonic timestamps:

- user end-of-turn accepted;
- Engine invocation started;
- first text delta;
- first speakable segment (Pipeline only);
- TTS request and TTS first audio byte (Pipeline only);
- first canonical `AudioDelta`;
- first transport send;
- client playback started when reported;
- response completed, cancelled, or failed;
- client playback completed when reported.

The primary latency measures are end-of-turn → first audio sent, end-of-turn → playback started, tool-call round-trip, and Barge-in confirmed → playback stopped. Metrics must be tagged by Engine conformer, provider, transport, tool, and outcome without putting secrets or raw audio into labels.

Initial targets continue to follow `docs/LATENCY.md`: p50 end-of-speech to first audio below 800 ms, p95 below 1500 ms, and confirmed Barge-in to stop below 200 ms. These are acceptance targets, not guarantees of every provider.

## Consequences

- Both Engine conformers can be swapped without changing Conversation Kernel or client behavior.
- Pipeline latency work becomes measurable per stage instead of hidden behind one blocking Brain response.
- Tool continuation and interruption are first-class protocol flows rather than special callbacks.
- Adapters have more translation responsibility, but provider details remain out of the core.
- Existing whole-response `LlmClient.complete()` and `TtsEngine.synthesize()` paths may remain as compatibility conformers during migration, but they cannot satisfy the low-latency production profile and must be reported as non-streaming capability.

## References

- OpenAI, [Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)
- OpenAI, [Realtime API with WebRTC](https://developers.openai.com/api/docs/guides/realtime-webrtc)
- OpenAI, [Voice agents](https://developers.openai.com/api/docs/guides/voice-agents)
- OpenAI, [Webhooks and server-side controls](https://developers.openai.com/api/docs/guides/realtime-server-controls)
- OpenAI, [Realtime with tools](https://developers.openai.com/api/docs/guides/realtime-mcp)
- `docs/GPT-Voice/10-本机GPT-Voice源码证据索引.md`
- `docs/GPT-Voice/12-GPT-Voice完整链路流程图.md`
- `docs/LATENCY.md`
