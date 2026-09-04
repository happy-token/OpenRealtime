---
status: accepted
---

# Core stays Python; npm surface is an additive skill package, not a rewrite or a client SDK

The user asked to restructure the project against two reference repos:
`QwenAudio/qwen-audio-agent` (a Node.js npm-workspace monorepo — CLI,
gateway, TUI, Electron desktop — that fronts *other* coding agents over
ACP) and `livekit/agents` (a pip-installable Python framework whose only
npm-distributed artifact is a separate coding-agent skill package,
installed via `npx skills add livekit/agent-skills --skill livekit-agents`).
The prompt's "支持npm安装" (support npm install) read, on its face, as
license to rewrite the runtime in Node — a real option given qwen-audio-agent
is proof that a voice-frontend product can be built that way, and given
this project's own prior attempt, VoiceLoop (`docs/references/voiceloop-modular-runtime-review.md`),
shipped a published TS `packages/web-sdk/`.

We decided against a rewrite: OpenRealtime's concurrency profile (many
concurrent WebSocket/UDP sessions, each mostly waiting on ASR/TTS/LLM
vendor round-trips) is exactly the I/O-bound shape both Python's asyncio
and Node's event loop are built for — neither has a structural ceiling
advantage here, and CPU-bound spikes (VAD, resampling) hit both models'
single-threaded event loop the same way regardless of language. Meanwhile
the Conversation Kernel, five-state/eleven-transition Turn Policy FSM,
Generation Lease, and Response Scheduler represent real accumulated
correctness work, documented across ADR-0001 through ADR-0025 — porting
that timing-sensitive logic to a new language from scratch would
reintroduce exactly the race conditions those ADRs already fought through
once, for no concurrency benefit.

## Decision

- The framework's core (`voiceagent/`) stays Python/asyncio, pip/uv
  packaged, as it is today.
- The only new npm-distributed artifact is a **coding-agent skill package**
  (`npx skills add ... --skill voiceagent`) providing architectural
  guidance, workflow/handoff patterns, and a "write your own plugin"
  walkthrough for a coding agent building on OpenRealtime — no runtime code.
- This explicitly does **not** reverse ADR-0018 or ADR-0025: `clients/`
  remains demo-grade reference code, not a maintained, published SDK.
  VoiceLoop's `packages/web-sdk/` precedent was considered and declined for
  this pass.
