---
status: accepted
---

# Support multiple concurrent Delegated Tasks across named Agents

**Amended by ADR-0052:** Agent Task Store is the durable lifecycle authority and
Work Registry is its live Voice-Session projection. Concurrency does not permit
duplicate spawn: every delegation uses atomic create-or-get, stable request
idempotency, backend reconciliation, and bounded leases before an Agent Driver may
start execution.

**Amended by ADR-0054:** one delegation action carries one Agent Selection Plan
with a primary and explicitly permitted fallbacks. It still produces at most one
backend execution before Backend Commit Point; fallbacks are not implicit fan-out.
After start, migration requires a new correlated task/Handoff rather than running
another Agent under the original `worker_id`.

OpenRealtime will allow one Voice Session to hold multiple concurrent Delegated Tasks across Drivers registered in BackendCatalog, including future Claude, Codex, and Hermes conformers. Each delegation action still names one target Agent; fan-out occurs only through an explicit policy or multiple actions, never implicitly on every turn. This supersedes ADR-0008's single-in-flight constraint while preserving its StatusInquiryClassifier, pull-based progress, explicit cancellation, and stale-result protections.

## Consequences

- Every Delegated Task has a `worker_id`, target Agent name, lifecycle, progress snapshot, result version, cancellation handle, and resource budget.
- Work Registry, not a single `_pending_session` field, is the source of truth for active background work.
- Barge-in cancels current speech output but does not cancel Delegated Tasks; explicit user intent or policy cancels a task by `worker_id`.
- Results are reinjected independently only after session, user, task, generation, permission, and version checks.
- Concurrency is bounded per session and per Agent; the default DelegationPolicy still selects one target for one delegation action.
