---
status: accepted
---

# Delegation latency: single Ack, pull-based progress, generation-gated errors

**Amended by ADR-0052:** the single Ack and pull-based progress behavior remain
accepted. Completion/error delivery is no longer discarded to Event Ledger merely
because the originating Generation is stale. Agent Task Supervisor persists every
terminal outcome, and Result Delivery Policy decides whether to announce when idle,
queue a notification, remain silent until asked, or perform an explicitly
server-authorized urgent preemption.

When Router delegates a turn to an external Agent or a long-running tool call and first-response latency will be noticeable, Response Scheduler emits exactly one **Delegation Ack** at dispatch time, then goes silent — there is no tiered or periodic filler schedule. If the user asks about progress mid-wait, Router answers using the most recent `session/update` notification the Agent Session Protocol has cached for that delegation (ADR-0001); if none has arrived yet, it falls back to a generic "still working on it" reply. The framework never issues an out-of-band status request to the backend — only backend-pushed updates are ever surfaced. If the delegation ultimately fails, the error is checked against the Generation-lease exactly like a successful result (ADR-0001): while the originating generation is still current, the error reason is spoken immediately; once the user has moved to a new generation, the error is written to the Event Ledger only and does not interrupt the new topic.

We considered the industry-standard layered filler pattern (escalating filler content at fixed time offsets, as used by ElevenLabs/Telnyx) as an initial recommendation, grounded in published voice-AI latency research. We rejected it: the user wants exactly one acknowledgment plus reactive, pull-based status on request, not a scheduled push-based content stream — tiered fillers add scheduling/state complexity this project's delegation model doesn't need, since the Generation-lease already gives the user an implicit "give up and ask something else" escape hatch. We also considered making errors always interrupt regardless of generation staleness, since silently swallowing a failure feels unsafe; we rejected unconditional interruption because it reintroduces exactly the problem Generation-lease exists to prevent — a stale, superseded result (successful or not) speaking up over a conversation the user has already moved past. Treating error-result injection identically to success-result injection, rather than special-casing errors as "always urgent," is not the obvious choice a reader would guess, so it's recorded here.
