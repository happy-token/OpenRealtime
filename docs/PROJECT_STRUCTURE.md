# Project Structure

A snapshot of the repo layout. See [ARCHITECTURE.md](ARCHITECTURE.md) for how
these pieces interact at runtime, and [CONTEXT.md](../CONTEXT.md) for term
definitions (Seam, Brain, Router, ...).

```
OpenRealtime/
├── server/                               # Framework package. Every Seam directory holds a
│   │                                    # Protocol + the framework's zero-config default;
│   │                                    # a Seam with a real, vendor-backed conformer nests
│   │                                    # it under that Seam's own plugins/ subfolder.
│   ├── core/                            # Generation Lease, Turn Content — shared value objects
│   ├── application/                     # Process composition root + durable services
│   ├── voice_session/                   # Lifecycle, reconnect barrier, context/control recovery
│   ├── realtime/                        # Stateful Engine, Cascaded capabilities, WS bridge
│   ├── endpoint_session/                # Reconnect/resume Seam (EndpointSession/Registry)
│   ├── turn_policy/                     # 5-state / 11-transition full-duplex dialogue FSM
│   │   ├── dual_intent.py               # Protocol + DefaultDualIntentClassifier
│   │   ├── eot_classifier.py            # Protocol + EotDecision
│   │   └── plugins/                     # LlmDualIntentClassifier, LlmEotClassifier, EnsembleEotClassifier
│   ├── signals/                         # EnergyVad, VisionSource, Voiceprint
│   ├── speech/                          # AsrEngine / TtsEngine Protocols + deterministic defaults
│   │   └── plugins/                     # DoubaoAsrEngine, DoubaoTtsEngine, BellaAsrEngine
│   ├── brain/                           # Brain/LlmClient Protocols, ChatBrain, ToolCallingBrain,
│   │   │                                # Router, DelegationPolicy, StatusInquiryClassifier
│   │   └── plugins/                     # OpenAiCompatibleLlmClient, KeywordDelegationPolicy
│   ├── tools/                           # Canonical Tool Schema + function-calling / skill /
│   │                                    # MCP / knowledge-base / web-search / clock sources
│   ├── knowledge_base/                  # Retrieval Protocol (RAG/知识库) + in-memory default
│   ├── web_search/                      # Retrieval Protocol for live web results
│   │   └── plugins/                     # ByteWebSearch
│   ├── agent_session/                   # Agent Session Protocol (delegate a turn externally)
│   │   └── plugins/                     # AcpDriver
│   ├── device_fleet/                    # Device activation/firmware/inventory contract
│   ├── voiceprint/                      # Speaker embedding matching + enrollment service
│   ├── observability/                   # Stage tracer — timing and error logging
│   ├── transport/                       # TransportAdapter Protocol + wire framing
│   │   └── plugins/                     # WebSocketTransportAdapter, UdpTransportAdapter
│   ├── hooks/                           # Hook Point — sync/async extension mechanism
│   └── ledger/                          # Event Ledger — async Observer fan-out
│
├── demos/                                # Runnable service-side launcher scripts
│   ├── basic_ws_server.py               # WebSocket demo server (text-only)
│   ├── voice_web_server.py              # Browser voice demo server (Bella ASR/TTS/LLM)
│   └── acp_opencode_live_demo.py        # Real ACP Agent backend demo
│
├── src/                                   # Next.js frontend — Next.js only auto-detects the App
│   │                                    # Router at <root>/app or <root>/src/app, so this is
│   │                                    # the framework-mandated name, not a generic default
│   ├── app/                              # App Router entry (layout.tsx, page.tsx) — the browser
│   │                                    # frontend, talks directly to demos/voice_web_server.py's
│   │                                    # WS server
│   ├── components/                       # OpenRealtimeApp, call/chat views, config drawer, shared UI
│   ├── hooks/                            # useConversationEngine — WS reconnect/backoff, mic
│   │                                    # capture, playback-with-barge-in
│   ├── lib/                              # Frame types + pure audio helpers (base64/PCM), unit-tested
│   └── styles/                           # oklch design tokens, dark/light theme
├── public/voice-input-worklet.js         # v2 Device Audio Input Runtime worklet
├── public/voice-input-worklet.js         # v2 device input epoch/buffer worklet
│
├── clients/                               # Reference client usage code, by device/transport type —
│   │                                    # demo-grade, not a distributable SDK (ADR-0025)
│   ├── websocket/client.py              # Raw WebSocket demo client (text-only)
│   ├── udp/client.py                    # Raw UDP demo client
│   └── esp32/                           # Reference device-side client for the Device Fleet contract
│
├── tests/                               # Mirrors server/'s structure
│   ├── live/                             # Opt-in live smoke tests against real vendors
│   ├── voice_session/ , realtime/ , speech/ , fixtures/
│
├── tests-e2e/                            # Playwright smoke test against the Next.js app
│
├── docs/
│   ├── ARCHITECTURE.md                  # Seam map, one-turn walkthrough, Seam→Protocol→ADR table
│   ├── PROJECT_STRUCTURE.md             # This file
│   ├── COMPLETION_STATUS.md             # PRD points vs. what's actually built
│   ├── ISSUES.md                        # Tracked gaps and accepted divergences
│   ├── VERSIONING.md                    # SemVer policy
│   ├── full-duplex-survey.md
│   └── adr/                             # 0001–0028, one architectural decision per file
│
├── CONTEXT.md      # Glossary
├── README.md       # Project overview, setup, package layout
├── CHANGELOG.md
├── ROADMAP.md
├── package.json / scripts/dev_server.sh # Root pnpm orchestration (dev/build/start)
└── pyproject.toml / uv.lock
```
