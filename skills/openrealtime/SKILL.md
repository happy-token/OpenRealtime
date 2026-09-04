---
name: openrealtime
description: Guidance for working in the OpenRealtime repo — a Python/asyncio full-duplex voice conversation framework with swappable ASR/TTS/Brain/TurnPolicy plugins. Use when adding or modifying a Seam plugin (speech/plugins, brain/plugins, turn_policy/plugins), wiring a new transport, debugging the Conversation Kernel or Endpoint Session resume protocol, writing tests in this repo, or delegating a turn to an external agent via the Agent Session Protocol.
---

# OpenRealtime

A framework for full-duplex voice conversation agents. The core loop —
audio/text in, ASR, turn-taking decisions, Brain, TTS, audio/text out — is
fixed; everything else is a swappable plugin behind a Seam (a Python
`Protocol`).

## Orient yourself first

Before writing code, read:

- `CONTEXT.md` — canonical glossary. Terms like Seam, Brain, Router, Endpoint
  Session, Turn Policy, Dialogue State, Agent Session Protocol have precise
  meanings here; don't improvise synonyms.
- `docs/ARCHITECTURE.md` — the Seam map and the "one turn, end to end" walkthrough.
- `docs/adr/` — decisions with rationale. Check for an existing ADR before
  assuming a design gap is unintentional (e.g. features that look missing may
  be deliberately deferred).

## Quick start: adding a plugin

1. Find the Seam's `Protocol` definition (e.g. `server/speech/asr.py`'s
   `AsrEngine`/`AsrSession`).
2. Implement it in a new file under the matching `plugins/` directory
   (e.g. `server/speech/plugins/`).
3. Compare against a real reference implementation in the same directory
   (e.g. `doubao_asr.py`, `bella_asr.py`) — not just the in-memory test double.
4. Write a test under the mirrored path in `tests/`.

See [references/write-your-own-plugin.md](references/write-your-own-plugin.md)
for a full worked example.

## Deep dives

- [references/architecture.md](references/architecture.md) — Seams, the
  Conversation Kernel, and how a turn flows through Router → Brain → TTS.
- [references/workflow-and-handoffs.md](references/workflow-and-handoffs.md) —
  DelegationPolicy and the Agent Session Protocol for handing a turn to an
  external agent.
- [references/testing-patterns.md](references/testing-patterns.md) — how
  `tests/` mirrors `server/`, AAA structure, and the opt-in live-smoke-test
  convention.

## Conventions worth knowing up front

- Zero new third-party runtime dependencies without an ADR (see ADR-0024) —
  prefer stdlib.
- Every default/in-memory implementation (`InMemory*`, `Preloaded*`) exists to
  make a Seam testable without a real backend; it is not a production fallback.
- `EndpointSessionRegistry` sends `SessionAckFrame` immediately on a fresh
  session, before the kernel processes any turns — client code must consume
  that frame before reading the first real reply.
