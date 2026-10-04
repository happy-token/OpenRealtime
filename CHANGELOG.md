# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning policy
is described in [docs/VERSIONING.md](docs/VERSIONING.md).

Released sections correspond to annotated Git tags. New work is collected
under **Unreleased** until the next version is cut.

## [Unreleased]

### Added

- Knowledge, memory and history management guide covering CRUD, reset boundaries,
  API contracts, shared storage and backup recovery; current project improvement
  checklist and documentation navigation, available in the web documentation menu.

### Changed

- Manual memory management remains available while automatic memory is disabled.
  Memory settings show loading and capacity, support refresh and deletion confirmation,
  and discard the editing draft when switching roles.
- Runtime memory projection selects the twenty most recently updated records,
  so edits to older preferences are included in the bounded prompt context.

## [0.3.0] - 2026-08-21

### Added

- Server-authoritative Voice Session Runtime with explicit lifecycle,
  authenticated rotating resume tokens, semantic reconnect/continuation,
  bounded model-context projection and summary checkpoints.
- Device Audio Input/Output runtimes with AudioWorklet epoch buffering,
  cumulative ACK/backpressure, playback truth, interruption-safe scheduling,
  browser transport recovery and content-free diagnostics.
- Durable delegated work recovery, bound confirmation restoration and
  speculative Brain-to-TTS speech generation.
- Strict live quality tooling and a committed real-provider Desktop Chrome
  campaign of 200 attempted turns.

### Changed

- Renamed the project, public UI, documentation, coding skill, package metadata,
  and reference coordinator to **OpenRealtime**. The former Python
  `VoiceAgent` export remains as a compatibility alias, and existing
  `VOICEAGENT_*` configuration plus persisted session identifiers are unchanged.
- Desktop Chrome now uses WebSocket v2, Voice Session Runtime and the device
  audio runtimes as the only production voice path.

### Removed

- The legacy Conversation Kernel/Engine/Scheduler production path, v1 inbound
  `audio_chunk` compatibility worklet/parser/bridge, legacy Realtime adapter,
  UDP Kernel demo and the old React conversation-engine hook.

## [0.2.0] - 2026-08-18

### Added

- **Stateful Realtime Engine contracts and cascaded runtime**: typed commands,
  ordered events, capability sessions for VAD/ASR/Turn Manager/Brain/TTS,
  profile resolution, plugin manifests, audio-plugin graph slots, failure
  recovery, Journal projection, WebSocket bridging, and a native-engine
  compatibility path behind the same public interface.
  ([ADR-0063](docs/adr/0063-stateful-realtime-engine-command-event-contract.md),
  [ADR-0065](docs/adr/0065-typed-cascaded-capabilities-and-audio-plugin-slots.md))
- **Duplex text/audio streaming and multi-representation delivery**: incremental
  text can enter TTS while the Brain is still producing it, while semantic,
  display, spoken, intended, and actually delivered content remain separately
  correlated and persisted.
  ([ADR-0062](docs/adr/0062-duplex-text-audio-streaming-tts.md),
  [ADR-0064](docs/adr/0064-multi-representation-content-and-speech-delivery.md))
- **Two-speed Voice Runtime tools**: fast tools complete inline; variable-latency
  search emits one intent-specific acknowledgement, executes asynchronously,
  resumes the same bounded tool turn, and supports transient Byte-search retry
  without delegating routine weather/search requests to Agent Runtime.
  ([ADR-0061](docs/adr/0061-two-speed-voice-tool-runtime.md))
- **Replaceable semantic EOT evidence** with FireRedChat ONNX support, DeepSeek
  Responses fallback, conservative open-slot arbitration, committed-history
  context, and a checked-in Chinese semantic-completeness evaluation corpus.
  ([ADR-0066](docs/adr/0066-replaceable-eot-evidence-and-deepseek-responses.md))
- **Administrator diagnostics UI** with authenticated access, overview metrics,
  session history and batch deletion, turn-level timeline analysis, dialogue and
  recording metadata, provider/tool latency, playback quality, and error logs.
- Rich conversation rendering with Markdown/GFM, tables, streaming-safe text
  repair, transcript role/deduplication safeguards, and improved voice/theme
  configuration including in-dialog voice preview.
- **Latest-wins semantic interruption** on playback-time ASR revisions:
  exact stop/backchannel rules, five-character and 100ms-idle model
  scheduling, strict six-label DeepSeek classification, stale revision and
  playback-generation guards, immediate Generation cancellation, and EOT-time
  separation of control-only `stop` from turn-creating
  `correction`/`interrupt`. Plain `complete()` LLM calls now reuse the
  cancellation-aware SSE path, so superseding a revision closes the old HTTP
  response instead of leaving an orphaned worker request. The implementation uses OpenRealtime's own Kernel,
  Turn Policy, and LLM seam; no Pipecat dependency was added.
  ([ADR-0060](docs/adr/0060-latest-wins-semantic-interruption-gate.md),
  [guide](docs/SEMANTIC-INTERRUPTION.md))
- **Speculative realtime date/search grounding** for the default ChatBrain:
  one frozen clock per SentenceEnd candidate, strict LLM planning for
  respond/clock/lookup, target-timezone calendar-day semantics, typed and
  explicitly untrusted `LookupEvidence`, bounded Byte search failures, and
  reuse/cancellation through the existing speculative response lifecycle.
  Clock/WebSearch ToolSources reuse the same hardened modules instead of a
  second provider-specific implementation.
  ([ADR-0059](docs/adr/0059-speculative-realtime-date-and-search-grounding.md),
  [guide](docs/REALTIME-GROUNDING.md))
- **`DoubaoDirectTtsEngine`** (`server/speech/plugins/doubao_tts_direct.py`):
  the direct Volcengine V3 bidirectional TTS endpoint
  (`wss://openspeech.bytedance.com/api/v3/tts/bidirection`), previously
  marked "confirmed broken" in ADR-0011, now works — the endpoint needed a
  different framing convention (`MsgTypeFlagWithEvent` plus a full
  connection/session/task event lifecycle) than the ASR-style flags every
  prior attempt used, not a broken or undocumented server. It's the new
  default TTS backend; `VOICEAGENT_TTS_BACKEND=bella` opts back into the
  gateway path. ([ADR-0038](docs/adr/0038-doubao-direct-tts-and-deepseek-v4-flash.md),
  supersedes [ADR-0011](docs/adr/0011-doubao-asr-tts-as-swappable-speech-seam.md)'s
  "confirmed broken" conclusion)
- **`DoubaoAsrEngine` single-key auth**: the direct ASR endpoint now
  authenticates with the same `X-Api-Key`/`DOUBAO_API_KEY` style TTS
  already used, instead of the legacy `X-Api-App-Key`/`X-Api-Access-Key`
  pair — one credential now covers both. It's also wired as this demo's
  default ASR backend alongside TTS, via a new `VOICEAGENT_ASR_BACKEND` env
  var (`"bella"` opts back into the gateway path).
  ([ADR-0039](docs/adr/0039-doubao-direct-asr-single-key-auth-and-default-wiring.md),
  supersedes ADR-0038's "ASR unchanged" note)
- Explicit `deepseek-v4-flash` model plus a `disable_thinking`
  constructor param (and `VOICEAGENT_LLM_DISABLE_THINKING` env var) on
  `OpenAiCompatibleLlmClient`/`OpenAiCompatibleToolCallingLlmClient`,
  sending `"thinking": {"type": "disabled"}` explicitly instead of relying
  on the `deepseek-chat` alias's undocumented default.
  ([ADR-0038](docs/adr/0038-doubao-direct-tts-and-deepseek-v4-flash.md))

### Fixed

- Slow search continuation no longer loses its task-local pending tool turn
  after the acknowledgement is spoken; one producer task now drives planning,
  tool feedback, sequential follow-ups, and the final LLM response.
- Admitted Barge-in text now still passes through semantic endpointing before a
  user turn is committed, preventing unfinished or repeated ASR revisions from
  creating alternating `thinking`/`reply` loops. A concurrent ASR-idle and
  interruption verdict can no longer emit a duplicate floor claim.
- Realtime transcript projection now keeps user and assistant roles distinct,
  coalesces cumulative ASR/TTS revisions, and avoids duplicate or fragmented
  chat bubbles during interruption and follow-up speech.
- Response cancellation, empty streams, tool errors, late provider output, TTS
  cleanup, and no-response states now settle explicitly instead of leaving the
  browser indefinitely in `listening` or `replying`.
- **Barge-in now actually interrupts.** `ResponseAction.YIELD` (τ9) only zeroed
  an internal countdown; nothing advanced the Generation, so the lease stayed
  current and `StreamingSpokenResponseScheduler`'s per-chunk check never tripped
  — the assistant talked over the user and finished its old answer. And because
  τ9 lands in LISTEN with the VAD's onset tracker still believing the user was
  silent, the interrupting utterance could never reach an end-of-turn, so its
  transcript was discarded and the user had to repeat themselves.
  `_yield_floor_to_user` now advances the Generation, sends the new
  `AssistantSpeechCancelledFrame` so the client drops already-buffered audio,
  supersedes any pending delegation, and re-arms the VAD.
  ([ADR-0036](docs/adr/0036-concurrent-turn-execution-and-real-barge-in-cancellation.md),
  corrects [ADR-0012](docs/adr/0012-streaming-tts-as-a-separate-protocol.md))
- **The Kernel is no longer half-duplex at runtime.** `run()` was a single
  sequential loop, so no inbound audio frame was read for the entire
  `router.decide()` + `deliver()` window — making Turn Policy's τ8–τ11 overlap
  family unreachable with any real LLM or TTS in the loop, and demonstrable only
  under the zero-latency test defaults. Each committed turn's Brain call and
  delivery now run in a tracked `asyncio.Task`.
  ([ADR-0036](docs/adr/0036-concurrent-turn-execution-and-real-barge-in-cancellation.md))
- **Semantic end-of-turn could deadlock.** Deferring an EOT left the VAD's
  silence timer already reset, so no further `USER_EOT_CONFIRMED` could fire
  unless the user spoke again: a user judged `INCOMPLETE` who then waited for a
  reply waited forever. New `Vad.resume_user_utterance()` re-arms the timer, so
  `eot_max_deferrals` bounds the wait for the first time.
  ([ADR-0037](docs/adr/0037-re-armable-vad-utterances-and-client-reported-playback.md),
  corrects [ADR-0013](docs/adr/0013-llm-semantic-eot-classifier.md) and
  [ADR-0021](docs/adr/0021-eot-dual-scorer-ensemble-and-split-liveness-bound.md))
- **Sustained noise bricked the session.** The speaking budget decremented only
  on quiet chunks in SPEAK and never in DUAL, so noise above the energy
  threshold meant `SYSTEM_EOT` never fired and the FSM ping-ponged SPEAK ↔ DUAL
  — and since τ1 only has a rule from IDLE, the user could never start another
  turn. The budget now ticks on every chunk, and an exhausted budget in DUAL
  resolves the overlap through the existing τ9/τ10/τ11 classification rather
  than adding a twelfth transition.
  ([ADR-0037](docs/adr/0037-re-armable-vad-utterances-and-client-reported-playback.md))
- Renumbered the second of two ADRs both numbered `0031` to
  [ADR-0035](docs/adr/0035-silero-vad-and-live-demo-eot-interruption-wiring.md),
  and removed a stale `.coverage` that still referenced the pre-ADR-0028
  `src/voiceagent/` path (so `coverage report` errored out).

### Added

- **`docs/ASSESSMENT.md`**, **`docs/INTERACTION-CASES.md`**, and
  **`docs/LATENCY.md`** — a product/engineering/technical review against a
  declared target of a *production voice runtime*: a five-tier maturity map, a
  blueprint-vs-runtime comparison, a per-case interaction audit against the
  survey's T×I×R ontology, and a latency budget (currently 1.5–4.5s
  end-of-speech to first audio) with a ranked optimization plan. Five
  `COMPLETION_STATUS.md` verdicts are corrected from Done to Partial, and
  `docs/ISSUES.md` gains ISSUE-0013 through ISSUE-0025.
- **`PlaybackProgressFrame`** (inbound): clients report real end-of-playback
  from their audio source's `ended` event, which the Kernel trusts over
  `SpeakingClock`'s text-length estimate. `SpeakingClock` becomes a watchdog
  ceiling behind it rather than being switched off, so a client that reports
  once and then vanishes cannot hold SPEAK forever. Clients that never report
  keep the previous behavior byte-for-byte.
  ([ADR-0037](docs/adr/0037-re-armable-vad-utterances-and-client-reported-playback.md),
  partially supersedes [ADR-0007](docs/adr/0007-duration-threshold-dual-intent-classifier.md))
- **`tests/kernel/test_full_duplex_concurrency.py`**: the first suite that runs
  the Kernel *without* settling turns between frames, using an
  `asyncio.Queue`-backed transport plus gated Brain/TTS doubles to inject audio
  mid-turn. It asserts observable outcomes — audio stops, the interrupting
  utterance is answered, the vendor stream is closed — rather than τ-transition
  sequences, which is why the four defects above survived a green 425-test
  suite ([ISSUE-0021](docs/ISSUES.md#issue-0021-the-test-suite-asserts-fsm-traversal-not-interaction-outcomes)).
- `asyncio.Lock` around `InMemoryEndpointSession.send`/`_flush_buffer`, now that
  two coroutines can write to a session concurrently and reattach-time replay
  could reorder buffered frames ahead of live ones.

### Changed

- Renamed `voiceagent/` → `server/` and `examples/` → `demos/`; promoted
  `clients/web/` to a root-level Next.js (TypeScript, App Router) app under
  `src/` (`src/app/`, `src/components/`, `src/hooks/`, `src/lib/`,
  `src/styles/`) so the whole stack starts with `pnpm install && pnpm dev`.
  `demos/voice_web_server.py` no longer serves static files — the Next.js
  app owns the frontend now. Reverses ADR-0018/0025/0026's "plain HTML/JS
  demo, no build step" stance now that the web client is the product
  frontend, not just a demo.
  ([ADR-0028](docs/adr/0028-server-rename-and-nextjs-web-client.md))
- Split device-facing client code (`client.py`, `udp_client.py`,
  `web/`) out of `examples/` into a new top-level `clients/` directory,
  organized by device/transport type (`clients/websocket/`, `clients/udp/`,
  `clients/web/`); `examples/` now holds only the server-side service
  demos. Reorganization and framing only — no behavior change, no new
  packaging. ([ADR-0025](docs/adr/0025-examples-vs-clients-directory-split.md))
- Dropped the `src/` layer (`voiceagent/` now lives at the repo root) and
  split every Seam directory that has a real, vendor-backed conformer into
  the Seam's core files (Protocol + zero-config default) plus a nested
  `plugins/` subfolder holding the real conformer(s) — e.g.
  `speech/plugins/doubao_asr.py`, `brain/plugins/openai_compatible_llm_client.py`.
  Pure reorganization: no behavior, signature, or logic changes.

### Added

- Conversation Kernel, the five-state/eleven-transition Turn Policy FSM
  (per [full-duplex-survey.md](docs/full-duplex-survey.md)), Raw WebSocket
  and raw UDP Transport Adapters, `ChatBrain`/`ToolCallingBrain`, the
  Canonical Tool Schema (function-calling/skill/MCP sources), Generation
  Lease, and Event Ledger — the initial full-duplex conversation kernel.
- Two-layer external Agent integration: Agent Session Protocol + `Driver`,
  `DelegationPolicy`/Router, `InMemoryDriver`/`KeywordDelegationPolicy` demo
  conformers. ([ADR-0001](docs/adr/0001-two-layer-external-agent-integration.md))
- Dual hook mechanism: async read-only `Observer` (Event Ledger) vs.
  synchronous, mutating `Hook Point`. `HookPoint` wires the
  `asr.before_turn_policy` interception point into `ConversationKernel` and
  `tts.before_synthesis` into `SpokenResponseScheduler`/
  `StreamingSpokenResponseScheduler`. ([ADR-0002](docs/adr/0002-dual-hook-mechanism.md))
- Device Fleet Seam (`activate`/`checkFirmware`/`listDevices`) and
  `InMemoryDeviceFleet`. ([ADR-0003](docs/adr/0003-device-fleet-as-standardized-seam.md))
- Unified `AddresseeClassifier` gating both user-onset and third-party-speech
  ignore transitions. ([ADR-0004](docs/adr/0004-unified-addressee-classifier.md))
- `Voiceprint` (informational speaker-match metadata) and `Wake Word`
  (optional gate on user-onset), stacking independently.
  ([ADR-0005](docs/adr/0005-voiceprint-informational-wakeword-gating.md))
- Delegation Ack (single spoken acknowledgment, no tiered filler),
  pull-based status inquiry, and error gating for pending delegations.
  ([ADR-0006](docs/adr/0006-delegation-latency-ack-pull-status-error-gating.md))
- `DualIntentClassifier` plugin interface + `DefaultDualIntentClassifier`
  duration-threshold heuristic disambiguating barge-in from backchannel.
  ([ADR-0007](docs/adr/0007-duration-threshold-dual-intent-classifier.md))
- `StatusInquiryClassifier` and single-in-flight-delegation semantics
  (progress check vs. genuinely new topic).
  ([ADR-0008](docs/adr/0008-status-inquiry-classifier-and-single-inflight-delegation.md))
- Single-tool-call-per-turn constraint for `ToolCallingBrain`.
  ([ADR-0009](docs/adr/0009-single-tool-call-per-turn.md))
- Knowledge Base retrieval contract exposed as an ordinary tool call via
  `KnowledgeBaseToolSource`; `InMemoryKnowledgeBase` default.
  ([ADR-0010](docs/adr/0010-knowledge-base-as-tool-source.md))
- Swappable Speech Seam: `AsrEngine`/`TtsEngine` Protocols,
  `PreloadedAsrEngine`/`SilentTtsEngine` defaults, `DoubaoAsrEngine`/
  `DoubaoTtsEngine` real conformers (Volcengine Doubao, via the Bella
  OpenAPI gateway).
  ([ADR-0011](docs/adr/0011-doubao-asr-tts-as-swappable-speech-seam.md))
- `StreamingTtsEngine` as a separate Protocol from `TtsEngine`, delivered
  via `StreamingSpokenResponseScheduler` with true mid-playback barge-in
  cancellation (closes the vendor stream, not just a client-side filter).
  ([ADR-0012](docs/adr/0012-streaming-tts-as-a-separate-protocol.md))
- `EotClassifier` plugin interface, gated at the Conversation Kernel (one
  layer above Turn Policy) after `EnergyVad` confirms end-of-turn;
  `LlmEotClassifier` conformer with `eot_max_deferrals` liveness bound.
  ([ADR-0013](docs/adr/0013-llm-semantic-eot-classifier.md))
- `WebSearch` and `Clock` retrieval contracts as Tool Sources
  (`search_web`, `get_current_datetime`); `DeterministicWebSearch` default.
  ([ADR-0014](docs/adr/0014-web-search-and-clock-as-tool-sources.md))
- `LlmDualIntentClassifier`, a content-aware `DualIntentClassifier`
  conformer built on the existing `LlmClient` Protocol, falling back to the
  duration heuristic on empty/ambiguous/unparseable replies.
  ([ADR-0015](docs/adr/0015-content-aware-dual-intent-classifier.md))
- `ByteWebSearch`, a real `WebSearch` conformer speaking ByteDance's
  `search_api/web_search` endpoint over stdlib `urllib` (no new HTTP
  dependency), closing ADR-0014's deferred vendor decision.
  ([ADR-0016](docs/adr/0016-byte-web-search-conformer.md))
- `AcpDriver`, a real `Driver` conformer speaking Agent Client Protocol
  (JSON-RPC 2.0 over NDJSON on stdio, stdlib-only) to any ACP-stdio coding
  agent, confirmed live against `opencode acp`; one shared subprocess per
  `Driver`, auto-approving `session/request_permission` by default.
  Closes [ISSUE-0003](docs/ISSUES.md#issue-0003-no-real-driver-for-a-named-external-agent-backend)
  for the qwen-audio-agent-style backend delegation path.
  ([ADR-0017](docs/adr/0017-acp-driver-real-agent-backend-conformer.md))
- `BellaAsrEngine`, a second real `AsrEngine` conformer speaking the Bella
  OpenAPI gateway's own JSON NLS-style streaming ASR protocol directly
  (distinct from `DoubaoAsrEngine`'s binary framing). A full browser voice
  demo (`examples/voice_web_server.py` + `examples/web/`, plain HTML/JS, no
  build step) wires it together with `DoubaoTtsEngine` and an
  `OpenAiCompatibleLlmClient` pointed at the same Bella gateway, all off one
  shared `API_KEY`. ([ADR-0018](docs/adr/0018-bella-web-voice-demo.md))
- Endpoint Session Seam: `EndpointSessionRegistry` + `InMemoryEndpointSession`
  let a session's identity and continuity outlive any one `TransportAdapter`
  connection, resumable within a grace period via a new
  `SessionHelloFrame`/`SessionAckFrame` handshake — no code changes needed
  in `ConversationKernel` or either Response Scheduler, since
  `EndpointSession` itself conforms to the `TransportAdapter` contract.
  Closes [ISSUE-0010](docs/ISSUES.md#issue-0010-endpoint-session-named-in-contextmd-but-never-built).
  ([ADR-0019](docs/adr/0019-endpoint-session-reconnect-resume.md))
- Rules-first stop-phrase short-circuit and confidence-threshold demotion for
  `LlmDualIntentClassifier`: an obvious bilingual stop-phrase match returns
  `FLOOR_CLAIM` without ever calling the LLM, and a low-confidence LLM reply
  demotes to the existing duration-heuristic fallback instead of manufacturing
  a `FLOOR_CLAIM` from an unreliable signal. Corrects
  [ADR-0015](docs/adr/0015-content-aware-dual-intent-classifier.md)'s
  inaccurate claim that the prior fallback behavior mirrored a voiceloop
  mechanism that doesn't actually exist there.
  ([ADR-0020](docs/adr/0020-rules-first-confidence-threshold-dual-intent-classifier.md))
- `EnsembleEotClassifier`, a dual-scorer EOT ensemble pairing a fast, always-on
  `FastEotScorer` (`PunctuationEotScorer` default) with an existing
  `EotClassifier` (e.g. `LlmEotClassifier`), arbitrating asymmetrically and
  failing open to the fast result if the slow side errors. Split
  `eot_max_deferrals` into independent `INCOMPLETE`/`UNCERTAIN` liveness caps
  in `ConversationKernel`, the frame-driven, deterministic analogue of
  voiceloop's two-tier wall-clock wait.
  ([ADR-0021](docs/adr/0021-eot-dual-scorer-ensemble-and-split-liveness-bound.md))
- Real Voiceprint service: `SpeakerEmbedder` Protocol +
  `PreloadedSpeakerEmbedder`/`BellaSpeakerEmbedder` conformers,
  `VoiceprintProfile`/`VoiceprintRepository`/`InMemoryVoiceprintRepository`,
  `EnrolledSpeakerVoiceprintMatcher` (the first real `VoiceprintMatcher`
  conformer), and `enroll_recording`/`AdaptiveEnrollment` (static and passive
  first-N-turns enrollment, with a 2-means split to isolate the dominant
  speaker). `VoiceprintMatcher` gains an additive `add_audio` method, fed
  unconditionally from `ConversationKernel`'s existing audio-chunk handling.
  ([ADR-0022](docs/adr/0022-voiceprint-embedding-matching-enrollment-service.md))
- `VoiceprintGate`, an opt-in `HookPoint`-based manual-confirm gate that
  vetoes a turn on a confirmed voiceprint mismatch and lets a host
  application resubmit it once a human confirms it. Not wired into
  `ConversationKernel` by default — [ADR-0005](docs/adr/0005-voiceprint-informational-wakeword-gating.md)'s
  "never gates by default" guarantee is unchanged for any host that doesn't
  register it.
  ([ADR-0023](docs/adr/0023-opt-in-voiceprint-manual-confirm-gate.md))

### Testing

- Multi-turn Full-Duplex Bench scenario chaining three successive user turns
  (normal reply → cooperative barge-in yielding to LISTEN → a third turn
  resuming directly from LISTEN without a fresh onset) through one
  continuous `ConversationKernel` session, asserting per-turn transitions
  and monotonic generation continuity across the whole conversation
  (`tests/bench/test_full_duplex_scenarios.py`).
- `tests/test_acp_driver.py` against a scripted stdio ACP agent fixture
  (`tests/fixtures/fake_acp_agent.py`, a real subprocess) covering the
  prompt/result round trip, streamed `agent_message_chunk` updates,
  cancellation, permission auto-approval, JSON-RPC error responses, and
  subprocess crashes. Also confirmed live by hand against a real
  `opencode acp` subprocess (`examples/acp_opencode_live_demo.py`).
- `tests/speech/test_bella_asr.py` against a fake WebSocket connection
  double (no real socket) covering the `StartTranscription` handshake,
  raw-PCM `push_audio`, `TranscriptionResultChanged`/`SentenceEnd`
  transcript updates, `TaskFailed` swallowed without raising, and
  `StopTranscription` on `close()`.
- `tests/live/test_bella_voice_pipeline_live.py`: a live smoke test against
  the real Bella gateway that needs neither a human nor a browser — ports
  `../realtime`'s `test_live_full_turn_with_real_audio` pattern by having
  Bella's own TTS synthesize a test utterance into PCM (plus synthetic
  silence so `EnergyVad` detects end-of-turn), streaming it into a real
  `ConversationKernel` over a real WebSocket, and asserting on the resulting
  `assistant_text`/`assistant_audio*` frames. Skipped by default; opt in
  with `RUN_LIVE=1` and a real `API_KEY`.
- `tests/test_endpoint_session.py`: fresh vs. resumed connections, unknown/
  expired `resume_session_id` falling back to a fresh session, buffered
  outbound frames flushed in order on reattach, grace-period expiry closing
  and evicting a session, outbound buffer overflow dropping the oldest
  frame, and a structural-typing regression test confirming
  `ConversationKernel` needs no changes to run against an
  `InMemoryEndpointSession` in place of a raw transport.

### Documentation

- `docs/references/pipecat-analysis.md`: pipecat's Frame/FrameProcessor/
  Pipeline core, turn-taking/EOT precedent, tool-calling schema, and why
  it's widely adopted, plus where OpenRealtime's Seam model deliberately
  differs. Closes [ISSUE-0008](docs/ISSUES.md#issue-0008-pipecat-analysis-not-written-up).
- `docs/references/voiceloop-modular-runtime-review.md`: review of the
  user's own unfinished second attempt — product surface, how far its
  rearchitecture got before stalling, and concrete implications for
  OpenRealtime's roadmap. Closes [ISSUE-0009](docs/ISSUES.md#issue-0009-voiceloop-modular-runtime-reference-not-written-up).
- `docs/references/vendor-delegation-survey.md`: comparative survey of how
  qwen-audio-agent, OpenAI Realtime, 声网 (Agora) ConvoAI, and 豆包's
  end-to-end realtime voice API each delegate to external tools/agents and
  hide delegation latency. Closes [ISSUE-0004](docs/ISSUES.md#issue-0004-prd-point-7s-vendor-delegation-mechanism-research-isnt-captured-as-a-doc).

### Known gaps

Tracked individually in [docs/ISSUES.md](docs/ISSUES.md); summarized in
[docs/COMPLETION_STATUS.md](docs/COMPLETION_STATUS.md) against the original
PRD.
