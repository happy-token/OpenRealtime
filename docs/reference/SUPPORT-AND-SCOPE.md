# Support and scope

| Area | Available foundation | What to check |
| --- | --- | --- |
| Voice | Streaming ASR → turn coordination → answer model/tools → TTS; generation-aware cancellation | Provider support, language, microphone, network and actual playback |
| Knowledge | Text/file/Web import, retrieval testing and role binding | Keyword retrieval limits and answer quality with your documents |
| Roles, memory and history | Persona, voice, knowledge and tool configuration; scoped memory and conversation continuation | Storage, retention and recovery for your deployment |
| Turn decisions | Independently configurable LLM/Jev adapters | Model decisions and runtime cancellation policy are separate; defaults are `llm` |
| Chat Agent integration | Compatible text-chat APIs and custom reply adapters | Validate your API's streaming, cancellation, tools and session behavior |
| Optional avatars | Anam integration, a separate HeyGen LiveAvatar route, local/video presentation | Access and capabilities differ; not every route is available on the homepage |
| External Agents | ACP, Codex app-server, Claude stream-JSON and Hermes adapter foundations | Unified onboarding and complete voice task collaboration remain **TODO** |
| Devices and transport | Browser WebSocket v2; UDP/ESP32 references | RTC and production device support are not implied |

English ASR/TTS configurations, reproducible English voice examples and full English conversation acceptance still need work. An English README does not establish multilingual runtime quality. Reports apply to their recorded versions and configurations. [Roadmap](../../ROADMAP.md) · [Runtime quality](../../docs/VOICE-RUNTIME-QUALITY.md)

## Self-host and extend

A full hosted deployment includes Next.js, the Python voice/control-plane service and PostgreSQL. Durable media storage depends on your chosen features. Supply your own authentication, credentials, storage and quotas. Cloud inference avoids self-hosted model GPUs; optional local neural rendering has separate compute requirements. [Deployment](../../docs/deployment/public-trial.md)

```text
src/          Web application and browser voice runtime
server/       Python runtime, providers, tools and persistence
demos/        Service launchers and console demos
config/       Configuration and persona resources
clients/      Device/transport reference clients
deploy/       Deployment configurations and optional services
docs/         User guides, architecture and validation evidence
```

[Architecture](../../docs/ARCHITECTURE.md) · [Plugin contracts](../../docs/SEMANTIC-DECISION-PLUGINS.md) · [Protocol](../../docs/asyncapi.json) · [Configuration examples](../../docs/reference/WEB-DEMO-CONFIGURATION.md)

Existing `VOICEAGENT_*` settings and legacy storage/protocol identifiers remain supported following the rename; consult upgrade notes before changing durable identifiers.


[README](../../README.md) · [Documentation](../README.md)
