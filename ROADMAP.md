# Roadmap

> 中文版：[docs/ROADMAP.zh-CN.md](docs/ROADMAP.zh-CN.md)

For "is X done" cross-referenced against the original requirements, see
[docs/COMPLETION_STATUS.md](docs/COMPLETION_STATUS.md). For the itemized
gap list this roadmap draws on, see [docs/ISSUES.md](docs/ISSUES.md). This
file includes historical planning entries. The current priorities below take precedence
over older status assertions; numbered links are retained for traceability.

## Current documentation and adoption priorities (2026-10-11)

- English-first README with a Chinese counterpart and clear documentation navigation.
- Reproducible cloud-service configurations and English voice acceptance.
- Unified external Agent onboarding and voice task collaboration (**TODO**), while
  documenting existing backend adapters separately.
- Reconcile older requirement/gap entries with current implementations and versioned evidence.

WebSocket v2, session recovery and CI checks exist today. Their presence does not
establish production readiness for every network/device or integration.

## Phase 1 Voice Runtime (M0–M6)

**Completed 2026-08-21.** Desktop Chrome now uses the Voice Session Runtime,
WebSocket v2 and device input/output runtimes as the only production voice
path. The committed real-provider 200-turn gate passed (p50 635.7 ms, p95
1035.8 ms, abnormal rate 0, correctness violations 0); v1 inbound
`audio_chunk`, its worklet, the legacy runtime packages and the old React
conversation hook were deleted. See
[the live report](docs/reports/2026-08-21-voice-runtime-phase1-live.md) and
[the replacement matrix](docs/VOICE-RUNTIME-REPLACEMENT-MATRIX.md).

RTC, Native Realtime Engine and Edge remain explicitly deferred and do not
block this milestone.

## Now

**Revised 2026-08-09** against the GPT-Voice document set and the current live
runtime. The local Voice Web Demo now uses the streaming Pipeline Conversation
Engine, direct Silero VAD, Generation cancellation, Conversation Journal, and a
PostgreSQL-selectable application composition root. RTC is deliberately later.

**Fast-tool baseline completed 2026-08-09:** the live Pipeline Engine now emits
versioned `CallToolAction` values, the application executes them through the
server-authoritative Policy Gateway and a per-turn Fast Tool Loop, journals
intent before execution and result before model reinjection, and cancels an
active handler on Generation supersession. The same Engine response resumes
from correlated feedback. Low-risk clock/search tools use this path in the
Voice Web Demo; the Brain no longer executes their handlers directly there.

**Simple voice-product baseline completed 2026-08-09:** the WebSocket handshake
now declares ASR/TTS and text-streaming capabilities. Configured deployments
use direct provider ASR with direct Silero VAD; browser speech is only a
last-resort conformer when server ASR is unavailable, while assistant text is
always rendered cumulatively as Engine deltas arrive.
Empty ASR output is rejected at the Kernel boundary instead of becoming an
invalid user turn. A deterministic browser-speech flow and a two-speaker,
two-turn live flow cover the product path; speaker diarization remains a later
multi-party capability, not something this sequential simulation claims to do.

**Realtime grounding baseline completed 2026-08-10:** the ordinary speculative
ChatBrain path now freezes one authoritative clock per SentenceEnd candidate,
plans respond/clock/lookup through a replaceable interface, and injects bounded,
typed web evidence as untrusted data. Date offsets use target-timezone calendar
semantics; missing search credentials fail before network access. Stable EOT
acceptance reuses the same planner/search/main-response producer, while new
VAD/ASR activity cancels it so one revision cannot spawn duplicate work. See
[Realtime Grounding](docs/REALTIME-GROUNDING.md).

In order:

1. **Complete interactive confirmation and multi-call tool turns.** The current
   policy creates and persists a bound confirmation and returns a safe spoken
   prompt without executing the side effect. Add the authenticated client
   decision frame, exact-digest approval/rejection handling, and response resume;
   then generalize the current one-tool Brain adapter to bounded sequential tool
   calls without weakening the per-turn budget.
2. **Execute canonical delegated-task actions through the durable v2
   Supervisor.** Route `DelegateTaskAction` into the Transactional Outbox and
   `AgentSupervisorRuntime`, expose progress/status/result by `worker_id`, and
   reuse the existing dedupe/Backend Commit Point protections so one semantic
   request cannot spawn duplicate Claude/Codex/Hermes work.
3. **Project multi-turn context from Conversation Journal.** Build bounded,
   provider-specific projections rather than treating a provider session or the
   browser transcript as history. Include tool/Agent results through references
   and explicit visibility rules; never replay Journal records as commands.
4. **Close measured latency gaps.** Add enforced EoT-to-first-text,
   EoT-to-first-audio, and cancellation-to-stop benchmarks; then implement TTS
   connection reuse, HTTP pooling, and a slow-lookup acknowledgment event. The
   semantic classifier and realtime Grounder already have bounded deadlines;
   the streaming LLM → segmenter → TTS foundation is live, so optimization
   should now be measurement-driven.
5. **Harden the non-RTC deployment.** Add authentication/tenant derivation,
   readiness, rate limiting, metrics export, PostgreSQL migration operations,
   and S3 reconciliation/garbage collection before claiming production
   readiness. Container packaging and a first CI pipeline shipped as part of
   the 2026-09-04 open-source readiness pass
   ([ISSUE-0024](docs/ISSUES.md#issue-0024-no-ci-and-pytyped-promises-what-nothing-verifies));
   what remains here is the data-plane auth/rate-limit/routing work.

**Added 2026-09-03, from a competitive review against Pipecat and
Qwen-Audio-Agent** (see the full comparison in
`openrealtime-improvement-todo.md`, kept outside this repo — its
differentiation-strategy section is a separate, unmerged product decision).
In priority order:

6. **Add behavioral, interaction-outcome tests instead of state-transition-only
   tests.** ISSUE-0021 recorded 425 passing tests that still missed a P0
   barge-in regression, because the suite asserted Turn Policy FSM transitions
   rather than the actual interaction outcome. Add an end-to-end evaluation
   layer (real/simulated audio in, assert whether the interruption and final
   output actually happened) modeled on Pipecat's `pipecat.evals`. Blocked on
   [ISSUE-0025](docs/ISSUES.md#issue-0025-the-live-demos-barge-in-path-cannot-be-exercised-without-real-speech-audio)
   (synthetic tones don't trigger Silero VAD) — fix the test-audio realism gap
   first, or the barge-in path still can't be exercised.
7. **Wire tools into the production composition root, not just the demo.**
   `server/application/runtime.py` has zero references to `Brain`/
   `ToolRegistry` today; every real construction point is
   `demos/voice_web_server.py::_build_brain`, gated by
   `VOICEAGENT_DEMO_TOOLS` and a hardcoded Python list. This is the third
   occurrence of the same "built but never wired" failure mode after
   [ADR-0030](docs/adr/0030-chat-brain-datetime-grounding.md) and
   [ADR-0035](docs/adr/0035-silero-vad-and-live-demo-eot-interruption-wiring.md), with
   [ADR-0032](docs/adr/0032-wire-web-search-tool-calling-into-live-demo.md)
   having fixed it only in the demo layer once already. See
   [ISSUE-0027](docs/ISSUES.md#issue-0027-toolsbrain-have-never-been-wired-into-the-production-composition-root)
   for the full evidence. Needs one stable, config/manifest-driven
   `build_tool_registry()` shared by demo and production, plus an integration
   test asserting a configured tool is actually reachable by the LLM in a real
   session — not another one-off demo-layer fix.
8. **Write a front/back-end boundary ADR.** The Brain/ToolCallingBrain
   responsibility split (realtime layer stays thin; multi-step orchestration
   is delegated, not inlined) is not yet a documented, enforced contract —
   modeled on Qwen-Audio-Agent's `spawn_thinking` boundary. Add an ADR stating
   what Brain may and may not do, and evaluate whether an explicit async
   task-dispatch primitive is needed to keep long-running work out of the main
   Turn Policy loop.
9. **Replace the MCP adapter with a real client.**
   [ISSUE-0014](docs/ISSUES.md#issue-0014-mcp-and-rag-are-named-seams-without-implementations)
   already tracks this as a named-but-unimplemented seam; `mcp_source.py` is
   schema adapter only, with no stdio/SSE/HTTP transport or handshake. Bind
   its acceptance criteria to item 7 above: "zero-code tool add" must be
   verified end-to-end (config gains an MCP server entry → tool is actually
   callable by the LLM in a live session), not just "client connects to
   server".
10. **Introduce a binary/codec transport abstraction.** Audio today is
    base64-in-JSON (~33% bandwidth overhead) with no binary framing or codec
    negotiation, tracked in
    [ISSUE-0019](docs/ISSUES.md#issue-0019-transport-is-not-deployable-over-a-real-network).
    Design a `FrameSerializer`-like abstraction (Pipecat's telecom-protocol
    serializers are a useful reference for the codec details) before deciding
    whether telephony-provider transports are in scope.
11. **Add call-level tool cancellation and interim result updates.** Today
    cancellation is response-scoped
    (`realtime/tool_controller.py`'s `ToolCancellation`) and
    `ToolResultChannel` is single-delivery per `call_id` — there is no way to
    cancel one in-flight background tool without tearing down the whole
    response, and no way for a long-running tool to report progress before
    its final result. Evaluate call-level cancellation and multi-submit result
    channels; land after item 8's boundary ADR so the async contract is
    settled first. Also revisit
    [ADR-0061](docs/adr/0061-two-speed-voice-tool-runtime.md), which undersells
    that `LatencyClass` is already a per-tool declarative field.

## Later

No committed order among these — each is deferred behind a stated
prerequisite in [docs/ISSUES.md](docs/ISSUES.md), not scheduled:

- **RTC / MQTT / direct-LiveKit transport conformers**
  ([ISSUE-0001](docs/ISSUES.md#issue-0001-rtcmqttdirect-livekit-transport-remain-contract-only))
  — satisfies the rest of PRD point 1. Needs an SDK/vendor decision per
  protocol first.
- **A real `VisionSource` conformer**
  ([ISSUE-0002](docs/ISSUES.md#issue-0002-no-real-visionsource-conformer))
  — completes PRD point 6's multi-modal integration.
- **Real `Driver`s for GPT-live and Grok voice** specifically — `AcpDriver`
  ([ADR-0017](docs/adr/0017-acp-driver-real-agent-backend-conformer.md))
  already closes the Qwen-audio-agent-style slice of PRD point 3 for any
  ACP-stdio backend; neither GPT-live nor Grok voice speaks ACP, so each
  would need its own `Driver` against its own real API if named again
  ([ISSUE-0003](docs/ISSUES.md#issue-0003-no-real-driver-for-a-named-external-agent-backend)).
- **Live GitHub issue tracker**
  ([ISSUE-0007](docs/ISSUES.md#issue-0007-no-live-github-issue-tracker-yet))
  — completed: the open-source repository is hosted at `happy-token/OpenRealtime`.
- **Multi-Agent backend breadth after canonical delegation is live.** Keep one
  `AgentDriver` contract and add verified configurations/adapters for Claude,
  Codex, and Hermes according to each backend's real protocol. Agent selection
  remains explicit; an unavailable named backend must fail visibly and must not
  silently fall back or spawn another backend. Non-ACP providers still need
  dedicated conformers per
  [ISSUE-0003](docs/ISSUES.md#issue-0003-no-real-driver-for-a-named-external-agent-backend).
- **ESP32/UDP device-client weak-network resume**
  ([ISSUE-0011](docs/ISSUES.md#issue-0011-esp32udp-device-clients-dont-use-session-resume-on-reconnect))
  — porting ADR-0019's resume mechanism + the web client's backoff pattern
  into `clients/esp32`/`clients/udp`. Deferred: these stay reference/demo-grade
  per ADR-0025 until there's real intent to move past that.
- **Plugin realization (Increment 3 candidate shape).** Pick one
  currently-stub plugin Protocol — e.g. `VisionSource`
  ([ISSUE-0002](docs/ISSUES.md#issue-0002-no-real-visionsource-conformer))
  or `AddresseeClassifier`/`Wake Word` — for a real conformer, in its own
  future plan-mode cycle. Not yet scoped into its own plan.
- **Transport hardening**
  ([ISSUE-0019](docs/ISSUES.md#issue-0019-transport-is-not-deployable-over-a-real-network))
  — distinct from ISSUE-0001's "which protocols exist". The older description of absent sequence numbers and protocol versions is
  superseded by WebSocket v2. Codec/binary framing, network-specific quality
  and device/transport hardening still require route-specific validation.
- **Authenticated identity derivation and distributed session mapping**
  ([ISSUE-0016](docs/ISSUES.md#issue-0016-no-identity-or-tenancy-model-across-the-three-session-abstractions))
  — canonical `InteractionContext` and persistence tenant keys now exist, but
  the live demo still derives tenant/user/device from trusted environment
  defaults rather than an authenticated connection. Prerequisite for data-plane auth
  ([ISSUE-0020](docs/ISSUES.md#issue-0020-the-data-plane-has-no-authentication))
  and for everything in the data/operations tier.
  Historical scope: the current demo has explicit development identity and
  authenticated/public-ticket deployment modes; distributed identity/routing
  still needs deployment-specific validation.
- **A real `AddresseeClassifier` conformer**
  ([ISSUE-0023](docs/ISSUES.md#issue-0023-no-addresseeclassifier-conformer-ships-so-third-party-filtering-is-unreachable))
  — the seam is elegant, and the only shipped conformer returns `True` always,
  so τ11 can never fire and PRD requirement 11 (排除第三方对话) is unsatisfied in
  behavior despite being satisfied in structure.
- **A recorded-speech fixture corpus**
  ([ISSUE-0025](docs/ISSUES.md#issue-0025-the-live-demos-barge-in-path-cannot-be-exercised-without-real-speech-audio))
  — `SileroVad` correctly rejects synthetic tones, so the shipped wiring's
  barge-in path cannot be exercised by a scripted client at all. A contributing
  cause of ISSUE-0013 surviving so long.
- **Real MCP and real RAG**
  ([ISSUE-0014](docs/ISSUES.md#issue-0014-mcp-and-rag-are-named-seams-without-implementations))
  — both are currently seams named after capabilities that do not exist.
  **Prerequisite:** pick an MCP client library and a vector store.
- **A turn-level timeout**
  ([ISSUE-0015](docs/ISSUES.md#issue-0015-no-session-or-turn-level-timeout-anywhere))
  — nothing bounds a turn today; a hung delegation leaves the user with an ack
  and then permanent silence. Needs its own ADR, since a wall-clock timer sits
  awkwardly against ADR-0007's frame-driven determinism rule.
- **Distributed live-session routing and operations completion**
  ([ISSUE-0018](docs/ISSUES.md#issue-0018-the-data-and-operations-tier-does-not-exist)).
  Authoritative semantic/work state now has PostgreSQL conformers, but active
  media/dialogue sessions remain process-local; multi-replica routing,
  recording policy, dashboards, and operational reconciliation remain open.
- **CI and type-checking follow-up (historical gap now partly superseded)**
  ([ISSUE-0024](docs/ISSUES.md#issue-0024-no-ci-and-pytyped-promises-what-nothing-verifies)),
  Current CI runs Python tests, a mypy baseline gate and Web checks.
  Future work is to maintain coverage and versioned latency/SLO gates, rather
  than establish CI from scratch.

## Explicitly not on this roadmap

- `EotClassifier`/`DualIntentClassifier` aligning to voiceloop's dual-model/
  rules-first/confidence-threshold design — the user reviewed the divergence
  and chose to keep the current implementation as-is
  ([ISSUE-0005](docs/ISSUES.md#issue-0005-eotinterruption-design-intentionally-diverges-from-voiceloop)).
  This is a closed decision, not a deferred one.
- A filler/latency-hiding subsystem (voiceloop's ~5,400-line "垫词" system)
  and voiceloop's "who owns agent/tool logic" split (push everything to an
  external customer Brain, no native tool-calling) — both deliberate,
  already-decided divergences, not gaps to close
  ([ISSUE-0012](docs/ISSUES.md#issue-0012-broader-comparison-against-voiceloop-2026-08-05--production-infra-fillers-tool-calling-philosophy-vad)).
