---
status: accepted
---

# AsyncAPI as the published protocol spec; a minimal, localhost-only, unauthenticated control plane

Writing a OpenRealtime client in any language other than Python meant reading
`voiceagent/transport/frames.py`'s Pydantic models directly — there was no
exported, machine-readable schema, and the hello/resume handshake sequencing
(ADR-0019) existed only as prose in that ADR. This blocked the
multi-language reference client work (ADR-0026's skill package assumes a
coding agent — or a human — can implement a client without reading the
Python source). Separately, there was no operational surface at all: no
health check, no way to see active sessions, no way to force-close one.

## Decision

- **Protocol spec: AsyncAPI**, not plain per-frame JSON Schema and not
  OpenAPI. The wire protocol is bidirectional/event-driven (the server
  pushes `assistant_audio_chunk` frames unprompted, mid-turn) — OpenAPI's
  request/response model doesn't fit, and JSON Schema alone would still
  leave the hello/resume/generation-number sequencing as prose-only,
  undocumented outside ADR-0019. AsyncAPI captures channels and sequencing
  as first-class, not just frame shapes.
- **Control plane: health check + session introspection + force-close-session**,
  bound to localhost only, with no authentication. OpenRealtime ships as a
  framework/library a deployer embeds, not a multi-tenant hosted service;
  the deployer's own network boundary (reverse proxy, firewall) is the
  right place to add auth if this surface is ever exposed beyond localhost,
  rather than OpenRealtime inventing its own auth scheme for a boundary it
  doesn't own.
- **Config-reload is explicitly out of scope** for this control plane.
  There is no config abstraction anywhere in the codebase today — just
  scattered `os.getenv()` calls in a few Seams (`turn_policy/dual_intent.py`,
  `signals/energy_vad.py`, `signals/speaking_clock.py`) — so "reload config"
  has nothing to reload yet. It's deferred until a config subsystem exists.

## Consequences

Force-close-session and session introspection are real state-changing/
information-disclosing actions with no auth in front of them. This is safe
only under the localhost-only assumption above; if a future deployment
needs to expose the control plane beyond localhost, that changes the
threat model and needs its own auth decision — it should not be assumed
covered by this ADR.
