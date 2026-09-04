---
status: accepted
---

# Opt-in voiceprint manual-confirm gate

ADR-0005 committed to an explicit stance: voiceprint metadata is
informational and never gates a Turn Policy transition by default. Voiceloop
(`../realtime`) has a manual-confirm gate that blocks a non-matching
transcript from reaching the LLM until a human confirms it really was them —
functionality worth having, but by nature a hard gate. Building it into
`ConversationKernel`'s own wiring would reverse ADR-0005 for every host
application, not just the ones that want it.

Instead, `voiceagent/signals/voiceprint_gate.py`'s `VoiceprintGate` is built
entirely as an opt-in building block on the existing `HookPoint` seam
(ADR-0002): a `Middleware`-shaped callable
(`__call__(self, value: str) -> str | None`) that a host application may
choose to register as its own `before_turn_policy_hook`. `ConversationKernel`
never constructs one, references one, or imports the module by default — a
host application that never wires `VoiceprintGate` in sees ADR-0005's
guarantee hold exactly as before, unchanged by this ADR's existence.

**Why a `HookPoint` and not a new Kernel parameter or a new turn-policy
branch**: `HookPoint`/`Middleware` already exists precisely for "a host may
want to intercept and veto text before it reaches turn policy" — reusing it
means no new Kernel surface, no new constructor parameter, and no risk of
this composing awkwardly with any other hook a host has already registered
there. It also means `VoiceprintGate` is fully testable in isolation (see
`tests/test_voiceprint_gate.py`) with a bare stub in place of a real
`EnrolledSpeakerVoiceprintMatcher`.

**Why it reads `last_result` synchronously instead of calling `match()`**:
`HookPoint`'s `Middleware.__call__` is synchronous and carries no
`generation` parameter, while `EnrolledSpeakerVoiceprintMatcher.match` is
`async` and needs one. The Kernel's own `await
self._voiceprint_matcher.match(generation=...)` call in `_route_and_respond`
always fires *after* the before-turn-policy hook has already run, so the
hook cannot simply await `match()` itself — the result wouldn't exist yet.
This is resolved on the matcher side (ADR-0022): `add_audio` eagerly computes
and caches a `(generation, VoiceprintResult)` tuple as soon as
`min_audio_ms` of buffered audio for the current generation has
accumulated, exposed via a synchronous `last_result` property.
`VoiceprintGate.__call__` reads that property directly — no `await`, no
Kernel change required beyond the `add_audio` plumbing ADR-0022 already
added for its own reasons.

**Veto and confirm semantics**: vetoes (returns `None`, same as any other
`HookPoint` veto) only on a confirmed `"no_match"`. `"unavailable"` and
`"adaptive"` pass the text through unchanged — neither is a positive signal
of a mismatch, so gating on them would block legitimate turns whenever the
matcher lacks a profile, lacks enough audio, or is still in adaptive
enrollment. A vetoed turn's text is stored keyed by `generation` with a TTL
(default 30s, via `time.monotonic()` — acceptable here since `VoiceprintGate`
lives outside the Kernel's own deterministic frame-processing core that
ADR-0007 constrains). `confirm(generation) -> str | None` retrieves and
clears a pending entry once (single-use, matching a real "did a human
confirm this" interaction), returning `None` for an unknown generation or
one whose TTL has elapsed. A host's own control-message handler is
responsible for calling `confirm` and re-submitting the result as a fresh
`UserTextFrame` — `VoiceprintGate` itself has no opinion on how that
resubmission happens, keeping it decoupled from any particular transport.
