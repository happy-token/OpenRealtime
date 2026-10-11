# OpenRealtime

**Bring your AI agents to life with real-time voice and avatars.**

A composable real-time voice and avatar Agent runtime, with a Next.js reference application for conversations, roles, resources, and service configuration. Choose turn-decision providers, answer models, voices, and avatar presentation separately.

[Try the demo](https://realtime.happy-token.cn) · [Documentation](docs/README.md) · [中文](README.zh-CN.md) · [Contributing](CONTRIBUTING.md)

## Why OpenRealtime?

- **Talk naturally.** Semantic turn coordination handles pauses, backchannels, stops, interruptions, and corrections. Decision providers supply evidence; the runtime coordinates reply cancellation and admission of the next request. [Turn coordination](docs/TURN-COORDINATION.md)
- **Give your agent a face.** Connect answers and audio to cloud avatar presentation or supported local presentation modes. Streaming, lip sync, and interruption behavior vary by route. [Avatar guide](docs/DIGITAL-HUMAN-DRIVING.md)
- **Choose each layer.** Configure decision providers, answer models, voices, knowledge, tools, and avatar services for your application. Supported adapters have explicit configuration and capability boundaries. [Architecture](docs/ARCHITECTURE.md)
- **Start simply. Build your way.** Start with hosted speech, model, and avatar APIs. The cloud path requires no self-hosted model GPUs; application hosting, credentials, and service usage fees still apply. [Deployment](docs/deployment/public-trial.md)

### Jev for turn decisions. Your LLM for answers.

Jev is an optional provider for structured end-of-turn and interruption classification. The runtime applies timing, confidence thresholds, and cancellation policy; the answer model generates responses. Both decision providers default to `llm` in [.env.example](.env.example). Model-call latency is not end-to-end conversational latency. [Implementation and evidence](docs/product/CLAIMS-AND-EVIDENCE.md)

## What you can build

- A voice or avatar guide using your product documentation.
- A role-based assistant with configurable voice, persona, knowledge, and tools.
- A real-time conversation interface for supported external Agent backends.

The Web application includes role configuration, a resource library, conversation history, and settings for providers and model services. [User guide](docs/QUICK-START.md)

## Capability status

| Area | Current scope | Boundary |
| --- | --- | --- |
| Voice interaction | Cascaded ASR → turn coordination → Brain/tools → TTS; streaming audio and generation-aware cancellation | Real quality depends on providers, language, network, and configuration |
| Turn decisions | Independently configurable LLM/Jev decision adapters | Classification and runtime policy are separate; no blanket accuracy claim |
| Avatars | Anam cloud integration, HeyGen LiveAvatar comparison route, and optional local/video presentation | Video loops, local lip sync, and cloud real-time rendering are different modes |
| Knowledge and tools | Document import/binding/retrieval, canonical tools and permission handling | Retrieval and task outcomes require validation with your data |
| Memory and history | Role/user-scoped memory, conversation history and continuation | Storage, retention, and recovery depend on deployment |
| External Agents | ACP, Codex app-server, Claude stream-JSON, and Hermes adapter foundations | Backend capabilities differ; a unified setup and voice task workflow remain **TODO** |
| Transports and devices | Browser WebSocket v2; UDP/ESP32 reference clients | RTC and production device support are not implied |

**Planned — Bring your own agent. Talk through the task.** Connect an existing Agent, start tasks by voice, ask for progress, and refine instructions. A consistent onboarding experience and end-to-end task workflow remain **TODO**. [Delivery checklist](docs/product/POSITIONING.md)

English-facing ASR/TTS configurations, reproducible English examples, and end-to-end English conversation acceptance still need to be completed. An English README does not establish multilingual runtime quality. [Roadmap](ROADMAP.md)

## Quickstart

### Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/).
- Node.js 22 and pnpm 10, matching the current [CI configuration](.github/workflows/ci.yml).
- A browser with microphone permission for voice input; HTTPS or localhost is normally required.

### Run locally

```bash
git clone https://github.com/happy-token/OpenRealtime.git
cd OpenRealtime
uv sync
pnpm install
pnpm dev
```

Open `http://localhost:3000`. The launcher starts Next.js and the Python WebSocket/control-plane services on ports 8765/8766. Local GPU avatar rendering is disabled by default. [Step-by-step startup and troubleshooting](docs/getting-started/LOCAL-DEVELOPMENT.md)

Without provider credentials, the backend uses deterministic demo adapters. Browser speech may be offered as an explicit fallback when supported. This verifies the application/demo path; it is not a real cloud-model conversation. Typed chat remains available when browser speech is unavailable.

### Enable real services

Use [.env.example](.env.example) as the configuration reference and keep credentials in local environment files. Configure supported speech/model providers before testing real voice; cloud avatars need their own authorized service configuration. Personal provider keys and platform service keys have different scopes.

[Cloud service setup](docs/getting-started/CLOUD-SERVICES.md) · [Detailed configuration examples](docs/reference/WEB-DEMO-CONFIGURATION.md)

## Deployment

A full hosted deployment includes Next.js, the Python voice/control-plane service, and PostgreSQL. Durable media storage and optional rendering services depend on the selected features. Cloud inference avoids self-hosted model GPUs; optional local neural rendering has separate compute requirements.

The public demo provides limited voice access configured by its operator. Self-hosted deployments supply their own service configuration, authentication, storage, and quotas. [Deployment and boundaries](docs/deployment/public-trial.md) · [Reliability operations](docs/RELIABILITY-OPERATIONS.md)

Existing `VOICEAGENT_*` variables and legacy storage/protocol identifiers remain supported following the VoiceAgent → OpenRealtime rename. Consult upgrade notes before changing durable identifiers.

## Project structure

```text
server/       Python runtime, service contracts, providers and persistence
demos/        Service launchers and console demos
src/          Next.js application, components, browser voice runtime and libraries
clients/      Device/transport reference clients
config/       Configuration and persona assets
scripts/      Development, checks and operational tooling
deploy/       Deployment configurations and optional services
docs/         User/developer guides, architecture, ADRs and evidence
```

[Detailed structure](docs/PROJECT_STRUCTURE.md) · [Architecture](docs/ARCHITECTURE.md) · [Glossary](CONTEXT.md) · [Protocol reference](docs/asyncapi.json)

## Development and contribution

```bash
uv run pytest
uv run python scripts/check_mypy.py
pnpm lint
pnpm exec tsc --noEmit
pnpm test
```

Browser tests require `pnpm exec playwright install chromium`. `pnpm test:voice` is the deterministic voice regression; `pnpm test:voice:live` calls configured external services and can incur charges. Optional media tests need their local services/assets. [Contribution and test guidance](CONTRIBUTING.md)

## Documentation and project status

- [Documentation index](docs/README.md): getting started, role configuration, deployment and extension paths.
- [Roadmap](ROADMAP.md) and [Changelog](CHANGELOG.md): planned work and recorded changes.
- [Product positioning and comparisons](docs/product/README.md): adoption rationale and evidence boundaries.
- [Runtime quality](docs/VOICE-RUNTIME-QUALITY.md): validation methodology; reports apply to their recorded versions/configurations.
- [Architecture decisions](docs/adr/) and [historical status audit](docs/COMPLETION_STATUS.md): engineering background.

## License

The runtime and integration code are licensed under [Apache-2.0](LICENSE). Hosted model/avatar services and third-party assets retain their own terms. See [third-party notices](THIRD_PARTY_NOTICES.md), [security reporting](SECURITY.md), and the [code of conduct](CODE_OF_CONDUCT.md).
