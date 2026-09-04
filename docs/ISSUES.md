# Known issues

Local, GitHub-Issues-shaped tracker. `origin` is hosted at
`github.com/happy-token/OpenRealtime`; this file remains the architecture-gap
tracker. Each entry:
id, title, status, description, related ADR/PRD point.

Status values: **open** (real gap, not yet worked), **deferred**
(acknowledged, intentionally not being worked yet, has a stated
prerequisite), **accepted** (not a bug — a deliberate design choice,
recorded so it isn't re-litigated as if it were an oversight).

---

### ISSUE-0001: RTC/MQTT/direct-LiveKit transport remain contract-only

**Status:** closed
**Related:** PRD point 1; `TransportAdapter` Protocol (`transport/base.py`)

Only Raw WebSocket and raw UDP have real conformers. RTC, MQTT, and
direct LiveKit each need either a live external service or a new SDK
dependency — a decision deliberately not papered over with a stub
indistinguishable from the existing `FakeTransport` test double. See the
Transport Adapter entry in [CONTEXT.md](../CONTEXT.md).
**Prerequisite:** pick one SDK/vendor per protocol before starting.

---

### ISSUE-0002: No real `VisionSource` conformer

**Status:** open
**Related:** PRD point 6; `signals/vision_source.py`

`NoVisionSource` (no-op) is the only implementation. The `TurnContent.vision_text`
plumbing (periodic snapshot or async vision-model text description) is
wired end-to-end, but nothing populates it from a real vision model yet.

---

### ISSUE-0003: No real `Driver` for a named external Agent backend

**Status:** Done
**Related:** PRD point 3; `agent_session/`; [ADR-0017](adr/0017-acp-driver-real-agent-backend-conformer.md)

The Agent Session Protocol + `Driver` seam is generic and worked from the
start (`InMemoryDriver`), but none of the three backends the PRD names by
name — Qwen-audio-agent, GPT-live, Grok voice — had its own `Driver`
(launch/auth/workspace details). `AcpDriver` ([ADR-0017](adr/0017-acp-driver-real-agent-backend-conformer.md))
closes this for any backend speaking Agent Client Protocol over
stdio — confirmed live against `opencode acp`, which is exactly the
backend qwen-audio-agent itself delegates to, so this covers the
qwen-audio-agent-style delegation path the PRD called out. GPT-live and
Grok voice speak neither ACP nor anything else OpenRealtime has a `Driver`
for yet — reopen as a new, narrower issue if either is named again with a
concrete API to integrate against.

---

### ISSUE-0004: PRD point 7's vendor delegation-mechanism research isn't captured as a doc

**Status:** Done
**Related:** PRD point 7

The PRD asks how 豆包 end-to-end realtime voice, 声网 (Agora),
qwen-audio-agent, and GPT-live each delegate (MCP / tool-use /
function-calling / skills). `DelegationPolicy`/Router (the mechanism itself)
shipped via [ADR-0001](adr/0001-two-layer-external-agent-integration.md);
the comparative vendor survey is now written up in
[docs/references/vendor-delegation-survey.md](references/vendor-delegation-survey.md).

---

### ISSUE-0005: EOT/interruption design intentionally diverges from voiceloop

**Status:** resolved (2026-08-10)
**Related:** `turn_policy/eot_classifier.py`, `turn_policy/semantic_interruption.py`, `turn_policy/dual_intent.py`

Compared against voiceloop (`../realtime`) this session: voiceloop's EOT
judgment is a dual-model ensemble (FireRedChat + optional parallel LLM,
disagreement forces `uncertain`, time-bounded liveness via `wait_ms`/
`incomplete_timeout_ms`) with FireRed as a structural fallback if the LLM
fails; OpenRealtime's `EotClassifier` is LLM-only with a count-based liveness
bound (`eot_max_deferrals`) and fails open to `COMPLETE` (no second model to
fall back to). Voiceloop's interruption classifier is rules-first
(phrase-match before ever calling the LLM) with a confidence field and a
threshold-based demotion step (`apply_interruption_threshold`, default 0.8)
that OpenRealtime's bare-word LLM protocol has no equivalent for; OpenRealtime's
`DualIntentClassifier` is LLM-first with a duration-based fallback and no
confidence signal at all. The user explicitly decided (2026-08-02) to keep
OpenRealtime's current implementation as-is rather than align it to
voiceloop's approach — logging this here so the divergence reads as a
recorded decision, not an unnoticed inconsistency.

**Superseded 2026-08-03**: the user reopened this decision and asked to
close the gap on all three fronts (EOT, interruption, and voiceprint).
Re-reading voiceloop's actual source this time around also found this
issue's own `apply_interruption_threshold` claim to be factually wrong —
no such mechanism exists anywhere in `tmp/voiceloop-modular-runtime`;
voiceloop's real interruption mechanism is a static `interrupt_strategy`
config choice (`"transcript"` vs `"vad"`) plus an unused
`backchannel_classifier` stub, and the same incorrect claim had also been
repeated in
[ADR-0015](adr/0015-content-aware-dual-intent-classifier.md)'s original
text (corrected alongside this entry). What was actually built this round:
`EnsembleEotClassifier` (a real dual-scorer EOT ensemble, portable in spirit
from voiceloop's design — see
[ADR-0021](adr/0021-eot-dual-scorer-ensemble-and-split-liveness-bound.md));
a rules-first stop-phrase short-circuit plus confidence-threshold demotion
for `LlmDualIntentClassifier` (new design work loosely inspired by
voiceloop's filler-gate shape, not a port of anything voiceloop actually
runs for interruption — see
[ADR-0020](adr/0020-rules-first-confidence-threshold-dual-intent-classifier.md));
and a real voiceprint embedding/matching/enrollment service plus an opt-in
manual-confirm gate (see
[ADR-0022](adr/0022-voiceprint-embedding-matching-enrollment-service.md) and
[ADR-0023](adr/0023-opt-in-voiceprint-manual-confirm-gate.md)). This entry
stays as the record of the original decision and why it changed, rather
than being deleted.

**Superseded again 2026-08-10:** after reviewing the current
`tmp/voiceloop` source, OpenRealtime adopted the portable SentenceEnd precompute
and VAD/ASR-idle stop-latch workflow, but kept the explicitly requested
LLM-only semantic judge. The live path no longer uses the ensemble, deferral
counters, or fail-open-to-`COMPLETE` parser described above. See
[Semantic EoT](SEMANTIC-EOT.md) and
[ADR-0057](adr/0057-sentence-end-semantic-race-and-speculative-response.md).

**Resolved for semantic interruption 2026-08-10:** the later
`docs/voiceloop/semantic-interruption.md` and current `tmp/voiceloop` source do
contain the rules-first six-label processor described by the updated reference
material. OpenRealtime has now adopted its portable domain behavior behind a
native `SemanticInterruptionGate`: playback-time partial revisions, exact
rules, confidence demotion, latest-wins cancellation, generation guards, and
separate stop-vs-create-Turn admission. The Pipecat processor itself remains
out of scope. See [Semantic Interruption](SEMANTIC-INTERRUPTION.md) and
[ADR-0060](adr/0060-latest-wins-semantic-interruption-gate.md).

---

### ISSUE-0006: Large body of implemented work is currently uncommitted

**Status:** open (housekeeping, not a code bug)
**Related:** [ROADMAP.md](../ROADMAP.md) **Now** section

Everything traced to ADR-0011 through ADR-0016 in
[CHANGELOG.md](../CHANGELOG.md) — Doubao ASR/TTS, streaming TTS, EOT
classifier, WebSearch/Clock tool sources, content-aware dual-intent
classifier, ByteWebSearch — is implemented and tested but sitting
uncommitted in the working tree (`git status`). No commit has been made
this session per the standing "commit only when explicitly asked" rule.
**Prerequisite:** user asks for a commit.

---

### ISSUE-0008: pipecat analysis not written up

**Status:** Done
**Related:** PRD 需求(requirement) point 5; `tmp/pipecat`

The PRD asks for pipecat specifically to be studied ("分析为什么这么多人用" —
analyze why it's so widely used) as an input to the framework's own design.
Written up in
[docs/references/pipecat-analysis.md](references/pipecat-analysis.md),
covering its Frame/FrameProcessor/Pipeline core, turn-taking/EOT precedent,
tool-calling schema, adoption drivers, and where OpenRealtime's Seam model
deliberately differs.

---

### ISSUE-0009: voiceloop-modular-runtime reference not written up

**Status:** Done
**Related:** PRD 需求(requirement) point 3; `tmp/voiceloop-modular-runtime`

The PRD calls out `voiceloop-modular-runtime` (the user's own unfinished
second attempt) as something to review for signal on what the finished
product should look like ("看看我想要的产品是什么样的"). Written up in
[docs/references/voiceloop-modular-runtime-review.md](references/voiceloop-modular-runtime-review.md),
covering its product surface, how far the rearchitecture got before
stalling, and concrete implications for OpenRealtime's roadmap.

---

### ISSUE-0010: Endpoint Session named in CONTEXT.md but never built

**Status:** Done
**Related:** Seam entry in [CONTEXT.md](../CONTEXT.md);
[ADR-0019](adr/0019-endpoint-session-reconnect-resume.md)

CONTEXT.md's own **Seam** entry has listed "Endpoint Session" as one of
the project's Backbone Seams from the start, and the **Transport Adapter**
entry already described itself as conforming to "the Endpoint Session's
wire protocol" — but no `EndpointSession` module or glossary entry ever
existed, so a dropped physical connection (the weak-network case) simply
ended `ConversationKernel.run()` for good. `EndpointSessionRegistry` +
`InMemoryEndpointSession` ([ADR-0019](adr/0019-endpoint-session-reconnect-resume.md))
close this: a session's identity and continuity now outlive any one
`TransportAdapter` connection, resumable within a grace period via a new
`SessionHelloFrame`/`SessionAckFrame` handshake. Single-process only, same
scope caveat as `InMemoryDriver`/`InMemoryDeviceFleet`.

---

### ISSUE-0011: ESP32/UDP device clients don't use session resume on reconnect

**Status:** deferred
**Related:** [ADR-0019](adr/0019-endpoint-session-reconnect-resume.md);
[ADR-0025](adr/0025-examples-vs-clients-directory-split.md);
`clients/esp32/main/main.c`; `clients/udp/client.py`

The server side of reconnect/resume (`SessionHelloFrame.resume_session_id`,
`EndpointSessionRegistry`) has existed since ADR-0019, and
`src/voice/session/transport.ts` (the Next.js web client runtime) already
uses it with a real exponential-backoff reconnect loop. The ESP32 and UDP
reference clients under `clients/` do not: ESP32's `send_session_hello()`
always sends a fresh hello with no `resume_session_id`, and neither client
has a reconnect-on-disconnect loop, so a dropped link ends the session for
good on those clients. Deliberately not closed by writing the logic into
`main.c` — see `clients/esp32/README.md`'s "Weak-network reconnect
(deliberately not implemented)" section, which documents the target
design (port ADR-0019's wire mechanism + `transport.ts`'s
backoff pattern) for whoever adapts this reference client for real
hardware. **Prerequisite:** intent to move ESP32/UDP past reference/demo
status per ADR-0025 — the user explicitly chose to keep this
documentation-only for now rather than implement it.

---

### ISSUE-0007: No live GitHub issue tracker yet

**Status:** deferred
**Related:** this file; `git remote -v`

`origin` is a live private GitHub repository under the HappyToken account.
This issue was closed when the repository was published and transferred.

---

### ISSUE-0012: Broader comparison against voiceloop (2026-08-05) — production infra, fillers, tool-calling philosophy, VAD

**Status:** mixed (see sub-items)
**Related:** ISSUE-0005 (prior, narrower voiceloop comparison);
[ADR-0034](adr/0034-silero-vad-sole-conformer-in-live-demo.md)

A wider comparison against voiceloop (`../realtime`) than ISSUE-0005's —
that one covered only EOT/interruption/voiceprint; this pass covered
production readiness, the filler/latency-hiding subsystem, transport
parity, and the LLM tool-calling/delegation model. Findings, by topic:

- **VAD weaker than voiceloop's.** Closed today: `demos/voice_web_server.py`
  already preferred `SileroVad` since ADR-0035, but silently fell back to
  `EnergyVad` on any construction failure. `SileroVad` is now the demo's
  sole VAD, no fallback — [ADR-0034](adr/0034-silero-vad-sole-conformer-in-live-demo.md).
  Voiceloop's own VAD (a custom ONNX "FireRed VAD" with a worker pool) is
  still a strictly stronger model than Silero; swapping VAD *models* (not
  just closing the wiring gap) is not in scope here and isn't tracked as
  its own issue yet.
- **Production infrastructure gap.** **Status: partial.** OpenRealtime now has
  direct PostgreSQL repositories for Conversation Journal, Agent tasks/events,
  tool authorization, and Transactional Outbox, plus S3-compatible Artifact
  contracts and an application composition root that wires PostgreSQL into the
  live Voice Demo when explicitly configured. Voiceloop also ships
  a multi-stage Dockerfile, an nginx+uvicorn supervisor, real `/health`/
  `/ready` probes, per-IP/per-app rate limiting, PII redaction, and
  MySQL+S3 session/event persistence with an admin dashboard. OpenRealtime has
  none of this — the control plane is deliberately "unauthenticated,
  localhost-only" ([ADR-0027](adr/0027-asyncapi-protocol-spec-and-unauthenticated-localhost-control-plane.md)),
  and OpenRealtime still has no Dockerfile, readiness policy, rate limiter,
  metrics exporter, or production deployment packaging. This wasn't in the original PRD's scope, so
  it isn't a broken promise, but it's the single largest capability gap
  found in this comparison if the goal is ever to run this outside a local
  demo. **Prerequisite:** decide a production deployment target (container
  platform, whether session state needs to survive a process restart)
  before scoping real work — logged here rather than acted on unprompted.
- **No filler/latency-hiding subsystem.** **Status: accepted, not a gap.**
  Voiceloop has a ~5,400-line subsystem for rule-based and small-LLM-backed
  filler phrases while the main Brain is still thinking. OpenRealtime
  deliberately does not have this — [ADR-0006](adr/0006-delegation-latency-ack-pull-status-error-gating.md)
  and [ADR-0008](adr/0008-status-inquiry-classifier-and-single-inflight-delegation.md)
  already chose a single-Ack-then-pull-based-status model over tiered
  fillers for delegation latency specifically. Recording this comparison
  point so it isn't relitigated as an oversight: it's a known, considered
  difference in product shape, not an unimplemented feature.
- **Opposite tool-calling/delegation philosophy.** **Status: accepted, not
  a gap.** OpenRealtime owns native LLM tool-calling (`ToolCallingBrain`,
  Canonical Tool Schema) and multi-backend agent delegation
  (`BackendCatalog`/`DelegationPolicy`, ADR-0031). Voiceloop has neither by
  design — it pushes all tool/RAG/agent logic to an external customer-owned
  "Brain" (`docs/internals/architecture-boundary.md` in that repo) and
  previously removed its own internal "hosted fast/slow brain" orchestration
  mode rather than grow it further. These are two different products
  answering "who owns agent logic" oppositely — OpenRealtime's PRD explicitly
  wants the multi-agent-delegation shape, so this is not something to
  converge on.
- **Transport parity is a wash.** No new gap: voiceloop is also
  WebSocket-only in practice (WebRTC/LiveKit/telephony are on *its* "Later"
  roadmap too, not shipped) — same conclusion as
  [ISSUE-0001](#issue-0001-rtcmqttdirect-livekit-transport-remain-contract-only),
  now cross-confirmed against a second real system rather than assumed.
- **Web client lacks operational diagnostics.** **Status: open, low
  priority.** Voiceloop's web app has a latency breakdown panel, a
  conversation timeline replay, and an interaction-settings panel exposing
  turn-policy/interruption-strategy knobs at runtime. `src/components/` here
  has none of this. Not in the original PRD; noted as a nice-to-have for
  whoever debugs turn-taking issues against a live session, not scheduled.
- **Barge-in window still text-length estimated, not real playback
  timing.** No new finding — [ADR-0035](adr/0035-silero-vad-and-live-demo-eot-interruption-wiring.md#3-semantic-interruption-speakingclock-sizing-and-llmdualintentclassifier)
  already documents this exact gap against voiceloop's real
  `PlaybackProjectionProcessor`-based approach as out-of-scope/future work.
  Re-confirmed, not re-opened as a separate issue.

---

### ISSUE-0013: Four P0 interaction defects on the core turn path

**Status:** open (being fixed now)
**Related:** [ASSESSMENT.md](ASSESSMENT.md), [INTERACTION-CASES.md](INTERACTION-CASES.md),
[ADR-0036](adr/0036-concurrent-turn-execution-and-real-barge-in-cancellation.md),
[ADR-0037](adr/0037-re-armable-vad-utterances-and-client-reported-playback.md);
PRD architecture point 2

Found by the 2026-08-05 review. Each was invisible to all 425 passing tests
because every test asserted a τ-transition list rather than an observable
interaction outcome — see [ISSUE-0021](#issue-0021-the-test-suite-asserts-fsm-traversal-not-interaction-outcomes).

- **P0-1 — the Kernel is structurally half-duplex.**
  `ConversationKernel.run()` (`kernel/conversation_kernel.py:161-163`) is a
  single sequential loop, so no inbound audio frame is read for the entire
  `router.decide()` + `deliver()` window (up to 15s by the LLM client's own
  default). The whole τ8–τ11 overlap family is therefore unreachable once a
  real LLM or TTS engine is wired in — it is demonstrable only under the
  zero-latency test defaults.
- **P0-2 — barge-in does not interrupt anything.** On `ResponseAction.YIELD`
  the Kernel only set `_speaking_ms_remaining = 0.0` (`:528-529`). It never
  advanced the Generation, so the lease stayed current and
  `scheduler/streaming_spoken_response_scheduler.py:60-62` kept streaming.
  The interrupting utterance was `peek_transcript()`ed but never consumed, and
  τ9 lands in LISTEN with the VAD tracker still `_speaking = False`, so no EOT
  could ever close it — the user's words were discarded.
  `ARCHITECTURE.md:135` documented the cancel-and-bump behaviour that did not
  exist.
- **P0-3 — semantic EOT could deadlock.** `_should_defer_eot` returning True
  made `_handle_audio_chunk:369-370` return early, but
  `_OnsetEotTracker.advance` (`signals/energy_vad.py:82-86`) had already
  committed its own `_speaking = False; _silence_ms = 0` reset. A user judged
  INCOMPLETE who then waited for a reply waited forever;
  `eot_max_deferrals` bounds deferrals, not silence.
- **P0-4 — sustained noise bricked the session.** `_speaking_ms_remaining`
  decremented only on quiet chunks in SPEAK (`:461-463`) and never in DUAL,
  so noise above the energy threshold meant `SYSTEM_EOT` never fired and the
  FSM ping-ponged SPEAK ↔ DUAL. Since τ1 only has a rule from IDLE, the user
  could never start another turn.

Not closed by this work: the survey's ~200ms yield bound (barge-in is now
correct but still waits for the overlap to end), and the acoustic-vs-semantic
conflation in hesitation handling. Both are itemized in
[INTERACTION-CASES.md](INTERACTION-CASES.md) cells 3 and 6.

---

### ISSUE-0014: MCP and RAG are named seams without implementations

**Status:** partial (WebSocket v2 continuity fixed; binary/codec and UDP remain)
**Related:** PRD architecture point 8; `tools/mcp_source.py`,
`knowledge_base/in_memory_knowledge_base.py`

`COMPLETION_STATUS.md` marked PRD architecture point 8 Done on the strength of
the seams existing. Corrected 2026-08-05:

- **No MCP.** `tools/mcp_source.py` is a schema adapter — it repackages a
  `handler` and `input_schema` the caller already constructed into a
  `CanonicalTool`. There is no MCP client, no transport (stdio/SSE/HTTP), no
  handshake, and no server discovery anywhere in the repo. The only other
  `mcp` mention is the empty `mcpServers: []` param passed to the ACP
  subprocess (`agent_session/plugins/acp_driver.py:271`).
- **No RAG.** `knowledge_base/in_memory_knowledge_base.py:20` is
  case-insensitive substring matching over a fixed list supplied at
  construction — no embeddings, chunking, vector store, or similarity
  scoring. The module's own docstring is honest about this ("the
  EchoLlmClient of Knowledge Base"); the completion record was not.

The `KnowledgeBase` Protocol is generic enough that a real backend could drop
in. `ByteWebSearch` is the one genuinely production-grade external-knowledge
conformer in the tier.
**Prerequisite:** pick an MCP client library and a vector store.

---

### ISSUE-0015: No session- or turn-level timeout anywhere

**Status:** open
**Related:** PRD requirement point 8;
[ADR-0006](adr/0006-delegation-latency-ack-pull-status-error-gating.md)

PRD requirement point 8 asked for a timeout mechanism and was marked Done
citing ADR-0006. But ADR-0006 reasons about *fillers* and deliberately rejects
a tiered filler schedule — rejecting a filler schedule is not a timeout.

- `kernel/conversation_kernel.py:314` awaits `session.result()` with no
  deadline. `AcpDriver` does not handle `fs/*` or `terminal/*` peer requests
  and its own docstring notes a backend needing those "will hang", so the
  user hears the single ack (correctly, per ADR-0006) and then permanent
  silence.
- `PROACTIVE_TIMER` (τ2) has exactly one producer — `:335`, speaking a
  delegation result — so there is no idle or proactive timer either. A user
  who goes silent is never prompted.
- Per-vendor socket timeouts exist (`timeout_s=15.0` on the LLM clients and
  3.0s on web search). The read-only realtime Grounder is additionally bounded
  to 5.0s end to end ([ADR-0059](adr/0059-speculative-realtime-date-and-search-grounding.md)),
  but delegated Agent turns and the overall conversation turn still have no
  general deadline.

Note that a wall-clock timeout would sit awkwardly against ADR-0007's
frame-driven determinism rule, so this needs its own ADR rather than a bare
`asyncio.wait_for`.

---

### ISSUE-0016: No identity or tenancy model across the three session abstractions

**Status:** partial
**Related:** PRD architecture point 5; `endpoint_session/`, `agent_session/`,
`device_fleet/`

`InteractionContext` now carries canonical tenant, user, device, Voice Session,
thread, turn, response, call, and worker correlation through Conversation
Engine, Journal, tools, Agent tasks, PostgreSQL, and artifacts. The live demo
constructs that context at its composition boundary. The remaining problem is
trusted derivation and physical-session binding:

- `endpoint_session/` owns physical-connection continuity (hello/resume/grace).
- `agent_session/` owns one delegated turn's lifecycle against an ACP backend.
- `device_fleet/` owns activation/firmware/inventory.

Endpoint sessions are still anonymous `uuid4()` connections. The demo takes
tenant/user/device defaults from server environment variables; the WebSocket
handshake does not authenticate or authorize them, and Device Fleet activation
is not bound to an Endpoint Session. Voiceprint remains informational and is not
an authentication mechanism (ADR-0005).

Blocking for a production runtime: authenticate the Session Plane, derive the
canonical context from trusted credentials, enforce tenant/device predicates,
and route reconnects to the owning live-session process. Prerequisite for the
remaining operations work in
[ISSUE-0018](#issue-0018-the-data-and-operations-tier-does-not-exist).

---

### ISSUE-0017: No real device audio path in any device client

**Status:** open
**Related:** PRD architecture point 5; `clients/esp32/`

`clients/esp32/main/main.c` is 149 lines and stubs both directions:
`:10` documents that I2S mic capture is intentionally omitted, and `:79` logs
`assistant_audio_chunk sequence=%d (playback not implemented)`. So the ESP32
client proves the JSON handshake round-trips and nothing else — no audio has
ever flowed from real hardware through this framework.

Per [ADR-0025](adr/0025-examples-vs-clients-directory-split.md) these clients
stay reference-grade until there is real intent to move past that; recorded
here because `COMPLETION_STATUS.md` previously read as if the device ecosystem
were done. Compounded by the base64-in-JSON wire format
([ISSUE-0019](#issue-0019-transport-is-not-deployable-over-a-real-network)),
which an embedded device on cellular cannot afford.

---

### ISSUE-0018: The data and operations tier does not exist

**Status:** partial
**Title note:** retained for stable links; the data foundation now exists and
the remaining gap is operational/distributed completion.
**Related:** [ASSESSMENT.md](ASSESSMENT.md); supersedes the infra half of
[ISSUE-0012](#issue-0012-broader-comparison-against-voiceloop-2026-08-05--production-infra-fillers-tool-calling-philosophy-vad)

The authoritative-state foundation now exists: direct PostgreSQL conformers
cover Journal, Agent tasks/events, tool authorization, Transactional Outbox,
and Artifact metadata; S3-compatible object storage owns large artifacts; the
live application runtime selects PostgreSQL explicitly and never performs
implicit migrations. Remaining operations gaps are:

- **Live-session distribution.** `EndpointSessionRegistry` and active media /
  dialogue state remain process-local even though semantic and work state can
  survive a restart in PostgreSQL. Multi-replica session routing is not built.
- **Metrics.** `StageTracer` deliberately does not aggregate (no p50/p95, by
  its own docstring). No exporter, no dashboard, no SLO.
- **Session recording / replay / analytics.** `EventLedger` is a correct
  fan-out point with **no shipped `Observer` implementation** other than
  demo logging.
- No Dockerfile, health/readiness probes beyond `/healthz`, or rate limiting.

Under the previous "framework, not application" positioning this was out of
scope. With a production-runtime target it is the largest single body of
missing work.
**Prerequisite:** decide a deployment target.

---

### ISSUE-0019: Transport is not deployable over a real network

**Status:** open
**Related:** PRD architecture point 1; `transport/frames.py`,
`transport/plugins/udp.py`

Distinct from [ISSUE-0001](#issue-0001-rtcmqttdirect-livekit-transport-remain-contract-only)
(which is about *which* protocols exist). This is about the two that do:

- **Audio is base64-encoded PCM inside JSON** (`frames.py:22-29`) — ~33%
  bandwidth inflation, a per-chunk encode/decode cost on both ends, and a
  per-byte `String.fromCharCode` loop in the browser (`src/lib/audio.ts:5-21`).
  No binary WebSocket path exists. No codec (opus or otherwise), no codec
  negotiation.
- **WebSocket v2 continuity is implemented.** `InputAudioFrame` carries
  `input_epoch`, sequence and sample positions; cumulative ACK, explicit
  `AudioGap`, bounded device buffering and protocol negotiation are enforced.
  The former v1 `AudioChunkFrame` was deleted in M6.
- **The remaining network gap is media efficiency/adaptation.** There is still
  no binary WebSocket audio path, codec negotiation or network jitter buffer;
  RTC is deliberately deferred until product features are complete.
- **No heartbeat or idle eviction on UDP.** A vanished peer's queue and task
  linger until the process dies (the module's own docstring, `udp.py:8-11`,
  records this as a deliberate simplification). The per-peer `asyncio.Queue`
  is also unbounded (`udp.py:60,70`) — no backpressure or drop policy.

---

### ISSUE-0020: The data plane has no authentication

**Status:** open
**Related:** [ADR-0027](adr/0027-asyncapi-protocol-spec-and-unauthenticated-localhost-control-plane.md)

ADR-0027 deliberately leaves the *control plane* unauthenticated and binds it
to loopback, which is a defensible, documented choice. The **data plane** has
no equivalent reasoning: the WebSocket transport accepts any connection, the
UDP transport accepts any datagram, and `SessionHelloFrame` carries no token,
device credential, or signature. `resume_session_id` is accepted on trust, so
any client that guesses or observes a session id can attach to that session
and receive its buffered frames.

Acceptable for a local demo; blocking for a production runtime, and easy for
an integrator to ship as-is without noticing. Depends on
[ISSUE-0016](#issue-0016-no-identity-or-tenancy-model-across-the-three-session-abstractions)
for who the credential would identify.

---

### ISSUE-0021: The test suite asserts FSM traversal, not interaction outcomes

**Status:** open (partially addressed)
**Related:** [ISSUE-0013](#issue-0013-four-p0-interaction-defects-on-the-core-turn-path);
`tests/bench/test_full_duplex_scenarios.py`

The root cause of [ISSUE-0013](#issue-0013-four-p0-interaction-defects-on-the-core-turn-path):
425 tests passed while four P0 interaction defects sat on the core path. The
whole suite runs in 4.25s, which is itself the signal — a voice system's tests
that finish in four seconds contain no timing assertions.

- Every one of the six survey acid-test cells in
  `tests/bench/test_full_duplex_scenarios.py` asserts only a τ-transition list
  plus `end_state`. The barge-in case (`:119-131`) never checks that audio
  stopped, that the interrupting utterance was answered, or how long the yield
  took.
- `test_latched_zero_gap_handoff_is_still_tau3` (`:107`) encodes
  *"zero-gap handoff is not implemented"* as its expected value.
- `test_hesitation_with_long_silence_then_resume_via_tau4_tau6` (`:169`) is
  driven by a 350ms silence, so utterance content is irrelevant — a semantic
  hesitation and a complete sentence produce identical results.
- `tests/scheduler/test_streaming_spoken_response_scheduler.py:123` fakes a
  barge-in with `on_yield=counter.advance`, manually doing the thing the
  Kernel failed to do.

Partially addressed: the ISSUE-0013 fixes each ship with a test that fails on
the parent commit for a behavioural reason, and
`tests/kernel/test_full_duplex_concurrency.py` asserts outcomes under real
concurrency. Still open: no latency assertions anywhere, and cells 2/5/6/10/12
of [INTERACTION-CASES.md](INTERACTION-CASES.md) remain untested.

---

### ISSUE-0022: A text frame arriving during SPEAK/DUAL is silently dropped

**Status:** deferred
**Related:** [ISSUE-0013](#issue-0013-four-p0-interaction-defects-on-the-core-turn-path);
`kernel/conversation_kernel.py:186-196`

`_TABLE` has no `(SPEAK, USER_EOT_CONFIRMED)` rule, so a `UserTextFrame`
arriving while the assistant is speaking makes `_evaluate_and_record` return
`None` at `:196` and the turn vanishes — with no ledger event to show it
happened. Nearly unreachable before the ISSUE-0013 work; now that turns run
concurrently with a nonzero `SpeakingClock`, typing twice quickly in the web
demo loses the second message.

The fix routes τ8 → τ9 → τ3, reusing only existing transitions and inheriting
the whole barge-in path from
[ADR-0036](adr/0036-concurrent-turn-execution-and-real-barge-in-cancellation.md).
**Prerequisite:** none — deferred only so its ledger-sequence changes are
reviewable separately from the P0 fixes, not because it is blocked.

---

### ISSUE-0023: No `AddresseeClassifier` conformer ships, so third-party filtering is unreachable

**Status:** open
**Related:** PRD architecture point 9, PRD requirement point 11;
[ADR-0004](adr/0004-unified-addressee-classifier.md)

PRD architecture point 9 and requirement point 11 (排除第三方对话) are both
marked Done, and the *mechanism* genuinely is: one `AddresseeClassifier` gates
both τ1 and τ11 (ADR-0004), which is a clean unification. But the only shipped
conformer is `DefaultAddresseeClassifier`
(`turn_policy/addressee.py:18-20`), which always returns `True` — so with the
default wiring **τ11 can never fire** and third-party speech is treated as the
user. `tests/bench/test_full_duplex_scenarios.py:151` proves the wiring works
by supplying `OnsetOnlyAddressedClassifier`, a test double built for the
purpose; nothing flags that no real classifier exists.

Candidate approaches: speaker-conditioned (personal) VAD, or promoting the
existing voiceprint matcher (ADR-0022) from informational to gating — which
ADR-0005 deliberately declined, so that would need a new ADR.

---

### ISSUE-0024: No CI, and `py.typed` promises what nothing verifies

**Status:** partial
**Related:** `pyproject.toml`, `server/py.typed`, `.github/workflows/ci.yml`

- **No CI at all** — no `.github/workflows`, no other config. Every regression
  check depends on a human remembering to run `uv run pytest` and
  `ruff check` before pushing. Nothing enforces either on `main`.
- **`server/py.typed` ships a marker asserting the package is fully typed**,
  but there is no mypy or pyright in the dev dependencies, so that promise to
  consumers is unverified. The codebase is annotated throughout, so adopting a
  checker should be cheap — and `Vad.resume_user_utterance`
  ([ADR-0037](adr/0037-re-armable-vad-utterances-and-client-reported-playback.md))
  is the first seam where liveness depends on a Protocol method existing,
  which is exactly what a checker should be guarding.
- Related minor hygiene from the same review: `.coverage` was stale (it
  referenced `src/voiceagent/`, a path from before the ADR-0028 rename, so
  `coverage report` errored) and has been removed; and two ADRs were both
  numbered `0031` — the later one is now
  [ADR-0035](adr/0035-silero-vad-and-live-demo-eot-interruption-wiring.md).

**Partially closed (2026-09-04, open-source readiness pass):** `.github/workflows/ci.yml`
now runs `uv run pytest`, `pnpm lint`, `pnpm exec tsc --noEmit`, and `pnpm test`
as blocking checks on every push/PR, and adds `mypy>=1.13` to the dev
dependency group — so `server/py.typed`'s promise is finally checked by
something. What's still open: running `uv run mypy server` for the first time
surfaced a **pre-existing backlog of 105 errors across 36 of 235 files**
(mostly `Protocol`/`Union` mismatches in `realtime/runtime.py`,
`agent_session/supervisor.py`, and `control_plane/http.py`, plus missing
third-party stubs for `silero_vad`, `asyncpg`, and `onnxruntime`) — none of
which are new regressions from this pass, all pre-dating mypy's adoption. Per
this project's own "no unrelated refactoring" norm, that backlog is not being
fixed as a side effect of an open-source cleanup: the CI `mypy` step runs
with `continue-on-error: true` and an inline comment pointing back here, so it
is visible on every run but does not block merges. **Prerequisite to flipping
it to blocking:** clear the existing 105 errors (or file targeted follow-up
issues per file/module and suppress the rest narrowly), then remove
`continue-on-error`.

---

### ISSUE-0025: The live demo's barge-in path cannot be exercised without real speech audio

**Status:** open
**Related:** [ADR-0034](adr/0034-silero-vad-sole-conformer-in-live-demo.md),
[ADR-0036](adr/0036-concurrent-turn-execution-and-real-barge-in-cancellation.md);
[ISSUE-0021](#issue-0021-the-test-suite-asserts-fsm-traversal-not-interaction-outcomes)

Found while verifying ADR-0036 against the real transport. `SileroVad` is the
sole VAD in `demos/voice_web_server.py` (ADR-0034), and it correctly classifies
synthetic tones as non-speech — so a scripted client sending constant-amplitude
PCM never produces a loud measurement, never reaches τ8, and cannot drive the
DUAL/barge-in transitions at all. The smoke run had to substitute `EnergyVad`
(which is an RMS threshold and does treat a tone as loud) to exercise the path.

Consequence: **the shipped wiring's most important interaction cannot be
verified without real recorded or synthesized speech.** This is a direct
contributing cause of the P0-2/P0-4 defects surviving so long — they were not
reachable by any cheap manual check, and the unit suites all use `EnergyVad`.

`tests/live/test_bella_voice_pipeline_live.py` already solves the audio-source
half of this by synthesizing an utterance with real Bella TTS, but it only
covers a plain turn, not barge-in. The natural fix is a small corpus of short
recorded WAVs (speech, backchannel, silence, noise) committed as fixtures, plus
a barge-in scenario in the `RUN_LIVE`-gated suite — no vendor credentials needed
once the audio is checked in.

---

### ISSUE-0026: GPU avatar rendering is spawned from the Next.js frontend, not the backend

**Status:** open
**Related:** `src/lib/livetalking-process.ts`, `src/app/api/avatar-renderer/preparations/route.ts`,
`src/app/api/liveportrait/retarget/route.ts`, `scripts/avatar_services.sh`

`ensureLiveTalkingProcess` (`src/lib/livetalking-process.ts`) `spawn()`s the
LiveTalking/Wav2Lip GPU inference process directly from a Next.js API route,
keyed on a `globalThis` map so it survives across requests within one Node
process. This puts a stateful, GPU-bound, long-running child process under
the frontend's process lifecycle instead of the Python backend's — a Next.js
deployment that isn't a single always-on Node process (serverless, multiple
replicas, edge) cannot host this at all, and the frontend now owns a
responsibility (subprocess supervision, port probing) that has nothing to do
with rendering UI. `scripts/avatar_services.sh` already treats avatar
rendering as an optional out-of-process service for local dev, which is the
right shape; it just isn't the shape `livetalking-process.ts` implements.
Not fixed in this pass — moving GPU process ownership to `server/` is a real
architecture change, not open-source cleanup, and
`OPENREALTIME_AVATAR_RENDERER_MODE=disabled` (the new default — see
[ROADMAP.md](../ROADMAP.md)) means self-hosters never hit this path unless
they explicitly opt in.
**Prerequisite:** decide whether avatar rendering becomes a `server/`-owned
service (matching every other capability's Seam shape) or stays a
frontend-adjacent sidecar with that tradeoff documented, not accidental.

---

### ISSUE-0027: Tools/Brain have never been wired into the production composition root

**Status:** open
**Related:** `server/application/runtime.py`, `server/tools/`,
`demos/voice_web_server.py::_build_brain`;
[ADR-0030](adr/0030-chat-brain-datetime-grounding.md),
[ADR-0032](adr/0032-wire-web-search-tool-calling-into-live-demo.md),
[ADR-0035](adr/0035-silero-vad-and-live-demo-eot-interruption-wiring.md)

`server/application/runtime.py` — the only production composition root — has
**zero references** to `Brain`, `ToolRegistry`, or `ToolCallingBrain`. Every
`ToolSource` (`ClockToolSource`, `WebSearchToolSource`,
`KnowledgeBaseToolSource`, `McpToolSource`, `FunctionCallingToolSource`,
`SkillToolSource`) and `ToolCallingBrain` itself is constructed **only** in
test files and in `demos/voice_web_server.py::_build_brain` /
`_build_tool_registry`, and even there it's gated behind an all-or-nothing
`VOICEAGENT_DEMO_TOOLS` environment variable with the tool list hardcoded as
a Python list literal — adding a tool means editing that line of demo code.
There is no configuration- or manifest-driven tool registration anywhere in
the repo (`tools.yaml`, `register_tool`, `load_tools`, `discover_tools` — none
exist).

This is the **third** occurrence of "built but never wired into the real
runtime": [ADR-0030](adr/0030-chat-brain-datetime-grounding.md) (time
grounding) and [ADR-0035](adr/0035-silero-vad-and-live-demo-eot-interruption-wiring.md)
(Silero VAD / semantic EOT / semantic interruption) were the first two,
each caught and fixed in the demo layer only.
[ADR-0032](adr/0032-wire-web-search-tool-calling-into-live-demo.md) fixed
this exact pattern for web-search tool-calling — but it wired
`demos/voice_web_server.py`, not `server/application/runtime.py`, so the
underlying failure mode (new capability lands, composition root is never
checked) was never actually closed, only patched at the point it was noticed
each time.

Practical consequence for anyone trying to add their own tool without forking
the project: even once [ISSUE-0014](#issue-0014-mcp-and-rag-are-named-seams-without-implementations)'s
real MCP transport lands, they would still need to (1) implement a
`ToolSource`, (2) hand-edit a composition root to register it, and (3) trust
an integration point that has silently been "zero tools in production" three
times before without anyone noticing until it was checked directly.
**Prerequisite:** a single, stable, integration-tested tool-registration
entrypoint (e.g. `build_tool_registry()` reading a config/env-driven list of
`ToolSource`s + MCP server declarations) shared by `demos/voice_web_server.py`
and `server/application/runtime.py`, with a test asserting that a configured
tool is actually reachable by the LLM in a real session — not just that the
`ToolSource` class instantiates.

---

### ISSUE-0028: `public/digital-human/` preview assets are not distributed with the open-source release

**Status:** open
**Related:** `public/digital-human/README.md`; `src/lib/avatar-renderer-preparation.ts`,
`src/lib/builtin-avatar-actions.ts`, `src/components/digital-human/**`

The realistic-person preview images/videos previously at `public/digital-human/`
(portrait/voice rights, not owned for redistribution) are excluded from the
public repository — see `public/digital-human/README.md` for what self-hosters
need to supply. 15+ call sites across `src/components/digital-human/**`,
`src/lib/builtin-avatar-actions.ts`, and `src/lib/avatar-renderer-preparation.ts`
hardcode `/digital-human/...` paths. Most of these are `<img>`/`<video>` `src`
values, so a missing asset just renders broken media — no test failure, no
crash, since the test suite asserts URL strings, not file existence.
`avatar-renderer-preparation.ts` is the one server-side reader of these paths
(e.g. `public/digital-human/builtin-motion/liveportrait-optimized.mp4` as a
LiveTalking source), and has no defensive handling for the file being absent —
this path is only reachable at all when
`OPENREALTIME_AVATAR_RENDERER_MODE` is not `disabled` (the new default), so a
self-hoster only hits it after opting in to GPU rendering **and** supplying
their own assets.
**Prerequisite:** none blocking; a defensive existence check + clear error in
`avatar-renderer-preparation.ts` would be a reasonable follow-up but is not
required for the framework to run with rendering disabled.

---

### ISSUE-0029: Internal vendor codename "Bella" persists in a public reference doc

**Status:** open (low priority)
**Related:** `docs/voiceloop/semantic-interruption.md`

`docs/voiceloop/semantic-interruption.md` (a migration-reference doc for
OpenRealtime's own semantic-interruption design, kept public per this
project's open-source review) repeatedly names `BellaSemanticInterruptionClient`,
a company-internal LLM-gateway codename, in prose, a diagram label, and a
credential-handling note (`resolve_semantic_interruption_api_key`'s
docstring quote). This is not a credential or secret — `API_KEY` itself is
never a literal value in the doc — but it is internal terminology that leaked
into a document written about a different (internal) codebase and copied in
for reference. Not fixed in this pass to avoid rewriting a reference document
under open-source time pressure; a future pass could s/Bella/a generic
"OpenAI-compatible gateway"/ without losing the doc's technical content.
