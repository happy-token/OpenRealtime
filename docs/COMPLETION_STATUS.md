# Completion status

Cross-references [docs/prompts/prd_0730.md](prompts/prd_0730.md) — the
original Chinese PRD — against what's actually implemented. That PRD is two
separate lists, tracked as two tables below. Status values: **Done**,
**Partial**, **Open**. Every Partial/Open row links the
[docs/ISSUES.md](ISSUES.md) entry tracking the gap.

## 架构组件 (Architecture components), PRD points 1–10

| # | PRD point | Status | Evidence |
|---|---|---|---|
| 1 | Multi-protocol transport: RTC / UDP / MQTT / direct LiveKit access | **Partial** | Raw WebSocket + raw UDP have real conformers (`transport/websocket.py`, `transport/udp.py`). RTC/MQTT/LiveKit remain contract-only — [ISSUE-0001](ISSUES.md#issue-0001-rtcmqttdirect-livekit-transport-remain-contract-only). |
| 2 | Unified 听(ASR)/说(TTS)/对话状态管理(Turn-Taking+VAD) module, referencing voiceloop's semantic-completeness/semantic-interruption modules, pipecat, and the full-duplex survey | **Done** | Turn Policy's 5-state/11-transition FSM + Speech Seam (`AsrEngine`/`TtsEngine`/`StreamingTtsEngine`) are built directly from [full-duplex-survey.md](full-duplex-survey.md). **Updated 2026-08-10:** VoiceLoop's portable SentenceEnd and semantic-interruption behavior is integrated without Pipecat: LLM-only EOT with VAD/ASR-idle latch and speculative reuse, plus playback-time ASR revisions, exact interruption rules, latest-wins six-label classification, generation-safe stop, and EOT-time Turn admission. See [Semantic EoT](SEMANTIC-EOT.md), [Semantic Interruption](SEMANTIC-INTERRUPTION.md), [ADR-0057](adr/0057-sentence-end-semantic-race-and-speculative-response.md), and [ADR-0060](adr/0060-latest-wins-semantic-interruption-gate.md). |
| 3 | External Agent access: Qwen-audio-agent, GPT-live, Grok voice | **Done** (Qwen-audio-agent-style); **Partial** (GPT-live, Grok voice) | Agent Session Protocol + `Driver` is a generic, working mechanism (`InMemoryDriver`, [ADR-0001](adr/0001-two-layer-external-agent-integration.md)). `AcpDriver` is a real `Driver` conformer for any Agent Client Protocol stdio backend, confirmed live against `opencode acp` — the same backend qwen-audio-agent itself delegates to ([ADR-0017](adr/0017-acp-driver-real-agent-backend-conformer.md), [ISSUE-0003](ISSUES.md#issue-0003-no-real-driver-for-a-named-external-agent-backend)). GPT-live and Grok voice speak neither ACP nor any other protocol OpenRealtime has a `Driver` for yet. |
| 4 | Extensibility and Hooks | **Done** | Dual hook mechanism: async read-only `Observer` (Event Ledger) + synchronous mutating `Hook Point` ([ADR-0002](adr/0002-dual-hook-mechanism.md)). |
| 5 | Multiple ecosystems (参考小智平台), multi-device | **Partial** (was: Done at contract level) | Device Fleet Seam (`activate`/`checkFirmware`/`listDevices`) + `InMemoryDeviceFleet` ([ADR-0003](adr/0003-device-fleet-as-standardized-seam.md)). **Corrected 2026-08-05**: there is no device audio path at all — `clients/esp32/main/main.c:10` stubs I2S mic capture and `:79` logs `playback not implemented`, so the ESP32 client only proves the JSON handshake round-trips. And `device_fleet`'s `device_id` never reaches `endpoint_session` or `agent_session`, so nothing can say which device a session belongs to — [ISSUE-0016](ISSUES.md#issue-0016-no-identity-or-tenancy-model-across-the-three-session-abstractions), [ISSUE-0017](ISSUES.md#issue-0017-no-real-device-audio-path-in-any-device-client). |
| 6 | Multi-modal integration: action / vision / text | **Partial** | `TurnContent.vision_text` and `ActionOutput` are wired end-to-end through the Kernel and Brain. `NoVisionSource` (no-op) is the only `VisionSource` — [ISSUE-0002](ISSUES.md#issue-0002-no-real-visionsource-conformer). **Corrected 2026-08-05**: understated. `transport/frames.py` has no image or video frame type at all, so vision content cannot reach the server over the wire in the first place; and no Brain conformer in the repo ever populates `ActionOutput`, so `emotion`/`gesture` are unwritten placeholder fields. |
| 7 | LLM-vs-delegation routing; research whether 豆包/声网/qwen-audio-agent/GPT-live use MCP/tool-use/function-calling/skills | **Done** | `DelegationPolicy`/Router mechanism shipped and generic ([ADR-0001](adr/0001-two-layer-external-agent-integration.md)). Comparative vendor research written up in [docs/references/vendor-delegation-survey.md](references/vendor-delegation-survey.md) — [ISSUE-0004](ISSUES.md#issue-0004-prd-point-7s-vendor-delegation-mechanism-research-isnt-captured-as-a-doc). |
| 8 | RAG / knowledge base / MCP external knowledge injection, adaptable across verticals | **Partial** (was: Done) | Knowledge Base retrieval is exposed as an ordinary tool call via `KnowledgeBaseToolSource` + `InMemoryKnowledgeBase` ([ADR-0010](adr/0010-knowledge-base-as-tool-source.md)); MCP-shaped declarations share the Canonical Tool Schema ([ADR-0001](adr/0001-two-layer-external-agent-integration.md)). **Updated 2026-08-10:** `ByteWebSearch` now returns typed, explicitly untrusted evidence and is available to the default speculative ChatBrain through bounded realtime grounding as well as the canonical tool path ([Realtime Grounding](REALTIME-GROUNDING.md)). This row remains Partial: there is still no embeddings/vector RAG backend and no MCP client, transport, handshake, or discovery. See [ISSUE-0014](ISSUES.md#issue-0014-mcp-and-rag-are-named-seams-without-implementations). |
| 9 | Distinguish dialogue addressed to the AI assistant vs. colleague chat (GPT-live feature) | **Done** | Unified `AddresseeClassifier` gates both user-onset and third-party-speech-ignore transitions ([ADR-0004](adr/0004-unified-addressee-classifier.md)). |
| 10 | Wake word / voiceprint as a pluggable add-on, core framework keeps its core characteristics | **Done** | `Voiceprint` (informational, no gating) and `Wake Word` (optional gate) stack independently and are both off by default ([ADR-0005](adr/0005-voiceprint-informational-wakeword-gating.md)). |

## 需求 (Requirements), PRD points 1–11

| # | PRD point | Status | Evidence |
|---|---|---|---|
| 1 | Study qwen-audio-agent's Agent-access pattern; support multiple access modes (MCP/skills/function tooling) behind a generalized interface | **Done** | Canonical Tool Schema unifies function-calling/skill/MCP sources; qwen-audio-agent's two-layer split and single-tool-call-per-turn constraint were adopted directly ([ADR-0001](adr/0001-two-layer-external-agent-integration.md), [ADR-0009](adr/0009-single-tool-call-per-turn.md)). `AcpDriver` now delegates through the same ACP-over-stdio backend qwen-audio-agent uses (OpenCode), confirmed live — [ADR-0017](adr/0017-acp-driver-real-agent-backend-conformer.md), [ISSUE-0003](ISSUES.md#issue-0003-no-real-driver-for-a-named-external-agent-backend). |
| 2 | Review voiceloop (architecture docs, depends on pipecat, growing structural complexity) | **Done** | Reviewed the actual `tmp/voiceloop` source. Portable SentenceEnd and semantic-interruption behavior was adopted behind OpenRealtime's own Seams; Pipecat and FireRed were not adopted. See [Semantic EoT](SEMANTIC-EOT.md) and [Semantic Interruption](SEMANTIC-INTERRUPTION.md). |
| 3 | Review voiceloop-modular-runtime (the user's own unfinished second attempt) as a signal for the intended product shape | **Done** | Reviewed and written up in [docs/references/voiceloop-modular-runtime-review.md](references/voiceloop-modular-runtime-review.md) — [ISSUE-0009](ISSUES.md#issue-0009-voiceloop-modular-runtime-reference-not-written-up). |
| 4 | Product design review — find and fill gaps | **Done** | This document plus [docs/ISSUES.md](ISSUES.md) and [ROADMAP.md](../ROADMAP.md) are that review. |
| 5 | Review pipecat; analyze why it's so widely adopted | **Done** | Analyzed in [docs/references/pipecat-analysis.md](references/pipecat-analysis.md) — [ISSUE-0008](ISSUES.md#issue-0008-pipecat-analysis-not-written-up). |
| 6 | Turn the full-duplex survey (html/pdf, `tmp/2606.19453v1.pdf`) into a doc under `docs/` | **Done** | [docs/full-duplex-survey.md](full-duplex-survey.md). |
| 7 | Improve dialogue-state management and interaction logic, referencing the full-duplex survey and architecture design | **Done** | Turn Policy's 5-state/11-transition FSM is built directly from [full-duplex-survey.md](full-duplex-survey.md); see [docs/ARCHITECTURE.md](ARCHITECTURE.md). |
| 8 | Timeout-handling mechanism, referencing `tmp/voice-ai-latency-tolerance.md` | **Partial** (was: Done) | [ADR-0006](adr/0006-delegation-latency-ack-pull-status-error-gating.md) explicitly weighs and rejects the tiered-filler pattern grounded in published latency-tolerance research. **Corrected 2026-08-05**: ADR-0006 reasons about *fillers*, not deadlines — and a rejected filler schedule is not a timeout mechanism. There is no session-level or turn-level timeout anywhere in `server/`: `kernel/conversation_kernel.py:314` awaits a delegation result with no deadline, so a hung backend leaves the user with the ack and then permanent silence; and `PROACTIVE_TIMER` (τ2) has exactly one producer (`:335`, speaking a delegation result), so there is no idle or proactive timer either. Per-vendor socket timeouts exist, but nothing bounds a turn. See [ISSUE-0015](ISSUES.md#issue-0015-no-session-or-turn-level-timeout-anywhere). |
| 9 | Task-delegation latency handling, referencing qwen-audio-agent's approach (`tmp/qwen-audio-realtime-agent-spawn.md`) | **Done** | [ADR-0006](adr/0006-delegation-latency-ack-pull-status-error-gating.md)'s pull-based `session/update`-style cached-notification mechanism is analogous to qwen's pattern. |
| 10 | Research how 豆包/声网/qwen-audio-agent/GPT-live call external business Agents or RAG/knowledge-base/extension components | **Done** | Same mechanism-plus-vendor-survey as component-list point 7 — mechanism shipped, comparative writeup in [docs/references/vendor-delegation-survey.md](references/vendor-delegation-survey.md): [ISSUE-0004](ISSUES.md#issue-0004-prd-point-7s-vendor-delegation-mechanism-research-isnt-captured-as-a-doc). |
| 11 | Exclude third-party dialogue — don't respond when the user is talking to someone else | **Done** | `AddresseeClassifier` third-party-speech filtering ([ADR-0004](adr/0004-unified-addressee-classifier.md)). |

## Summary

**Revised 2026-08-05.** This document previously reported 7/10 architecture and
11/11 requirement points Done. Those verdicts were accurate about *seams* and
overstated about *capabilities*, so five rows were corrected (architecture 2, 5,
6, 8 and requirement 8) after the review in
[docs/ASSESSMENT.md](ASSESSMENT.md). The revised counts:

- **Done**: 5 of 10 architecture points (4, 7, 9, 10, plus 3 for the
  Qwen-audio-agent-style backend specifically); 10 of 11 requirement points.
- **Partial**: 5 of 10 architecture points (1, 2, 5, 6, 8) and 1 of 11
  requirement points (8).
- The project's declared target is now a **production voice runtime**, not a
  reference framework, so contract-only completeness no longer counts as Done.
  [ASSESSMENT.md](ASSESSMENT.md#path-to-production) holds the ordered gap list.

### Prior summary (pre-correction, retained for the record)

- **Done**: 7 of 10 architecture points fully, plus point 3 for the
  Qwen-audio-agent-style backend specifically; 11 of 11 requirement points.
- **Partial**: 2 of 10 architecture points fully (points 1, 6), plus point 3
  for the GPT-live/Grok voice slice only — every Partial has an
  [docs/ISSUES.md](ISSUES.md) entry tracking the missing half, and all of
  them are now vendor-specific-conformer gaps, not missing research/analysis —
  [ISSUE-0001](ISSUES.md#issue-0001-rtcmqttdirect-livekit-transport-remain-contract-only),
  [ISSUE-0002](ISSUES.md#issue-0002-no-real-visionsource-conformer),
  [ISSUE-0003](ISSUES.md#issue-0003-no-real-driver-for-a-named-external-agent-backend)
  (partially closed — see that entry).
- **Open**: 0 architecture points; 0 requirement points. The pipecat analysis,
  voiceloop-modular-runtime review, and vendor delegation survey — the three
  items open as of the prior pass — are now written up under
  [docs/references/](references/) ([ISSUE-0004](ISSUES.md#issue-0004-prd-point-7s-vendor-delegation-mechanism-research-isnt-captured-as-a-doc),
  [ISSUE-0008](ISSUES.md#issue-0008-pipecat-analysis-not-written-up),
  [ISSUE-0009](ISSUES.md#issue-0009-voiceloop-modular-runtime-reference-not-written-up)).
- The former EOT divergence in
  [ISSUE-0005](ISSUES.md#issue-0005-eotinterruption-design-intentionally-diverges-from-voiceloop)
  is historical: portable LLM-only EOT and semantic interruption coordination
  are now adopted behind native OpenRealtime Seams; Pipecat remains out of scope.
