# Project structure

Updated 2026-10-13. This is an orientation map of the current source tree, not an assertion that every optional adapter is production-ready. No source directories were moved by this documentation update.

```text
OpenRealtime/
├── apps/backend/           Session management service (backend): API routes and initialization
├── server/                 Voice interaction service (backend): Python runtime and integrations
│   ├── application/        Composition root and durable application services
│   ├── voice_session/      Session lifecycle, recovery and admission
│   ├── realtime/           Cascaded engine, coordination capabilities, speech and protocol
│   ├── turn_policy/        Turn-decision contracts, coordination policies and classifiers
│   ├── speech/             ASR/TTS contracts and adapters
│   ├── brain/              Answer generation, grounding and tool integration
│   ├── tools/              Canonical tools, execution policy and data sources
│   ├── knowledge_base/     Retrieval contracts and catalog implementations
│   ├── agent_session/      External Agent sessions and backend adapters
│   ├── persistence/        Persistence contracts and PostgreSQL implementations
│   ├── conversation_journal/ Semantic conversation history
│   ├── artifacts/          Artifact storage contracts and adapters
│   ├── transport/          Transport adapters and framing
│   └── observability/      Runtime diagnostics and telemetry
├── src/
│   ├── app/                Frontend routes, page composition and local API forwarding
│   ├── components/         Conversation UI, roles, resources, settings and documentation
│   ├── voice/              Browser input/output and session runtime
│   ├── hooks/              Application/session hooks
│   ├── lib/                Data access, configuration, auth and shared helpers
│   └── styles/             Product visual styles and tokens
├── demos/                  Runnable service/console launchers
├── clients/                WebSocket, UDP and ESP32 reference usage
├── config/                 Service/persona configuration assets
├── public/                 Public frontend assets and audio worklets
├── scripts/                Launchers, checks, migrations and operational utilities
├── deploy/                 Deployment configurations and optional services
├── tests/                  Python tests
├── tests-e2e/              Browser journeys
└── docs/                   Guides, architecture, decisions and versioned evidence
```

Both the session management service and voice interaction service belong to the backend; `src/app` owns the frontend. See the [deployment guide](deployment/frontend-backend.md) for their build and execution boundaries.

The runtime and the reference application share this repository. Current Web turn coordination lives under `server/realtime/capabilities/` with decisions and policies in `server/turn_policy/`; the historical five-state FSM is background, not a complete map of the current coordinated runtime.

External Agent adapters include ACP, Codex app-server, Claude stream-JSON and Hermes. Their configuration and execution capabilities differ. UDP/ESP32 clients are reference-grade; their existence does not establish production device or RTC support.

See [documentation paths](README.md), [architecture](ARCHITECTURE.md), [turn coordination](TURN-COORDINATION.md), [glossary](../CONTEXT.md), and [configuration examples](reference/WEB-DEMO-CONFIGURATION.md). Local ignored model/research/generated directories are not part of this source orientation or necessarily included in an open-source checkout.
