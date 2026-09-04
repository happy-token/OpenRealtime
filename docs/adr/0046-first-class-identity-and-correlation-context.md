---
status: accepted
---

# Carry first-class identity and correlation context across every Seam

Every inbound event, Conversation Action, tool call, Delegated Task, output event, and observability record will carry one immutable Interaction Context. The context distinguishes tenant, user, device, live Voice Session, persistent thread, accepted turn, and supersession generation, with optional `call_id`, `worker_id`, `confirmation_id`, and `handoff_id` for correlated work. This closes the current anonymous-session foundation gap and follows GPT Voice's observable use of session, thread, item/tool-call, handoff, and generation-like correlation while adding the explicit tenancy and device identity a vendor-neutral production runtime needs.

## Consequences

- `voice_session_id` identifies the user-facing live interaction; `endpoint_session_id` identifies transport continuity; `thread_id` identifies persistent conversational context.
- `turn_id` is stable identity, while Generation remains a monotonic cancellation and stale-output epoch.
- Identity fields exist in contracts before authentication and persistence adapters are implemented; anonymous operation is explicit rather than represented by unrelated UUIDs.
- IDs are opaque values. Authorization uses verified claims associated with them, never caller-supplied identifiers alone.
- Tool, worker, confirmation, and handoff results are rejected or stored silently when their Interaction Context no longer matches the active session policy.
