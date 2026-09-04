---
status: accepted
---

# Use explicit Agent Selection Plans and prohibit silent backend fallback

DelegationPolicy returns an immutable Agent Selection Plan containing one primary Agent, an ordered list of explicitly permitted fallbacks, required capabilities, security/workspace constraints, budget/latency bounds, and confirmation policy. Agent Task Supervisor may choose a fallback only before Backend Commit Point and only when the plan permits it. No Router, Driver, retry handler, health checker, or exception path may silently select another Agent, model, permission profile, or workspace mode.

Once Supervisor issues the first backend start side effect, target Agent is locked for that `worker_id`. Failure, timeout, lost connection, or UNKNOWN state after that point triggers reconciliation—not same-task fallback. Moving the work to another Agent requires a new Delegation Request ID, new `worker_id`, refreshed policy/confirmation, and explicit Handoff Package linked to the original task.

This rule is a OpenRealtime reliability and trust guarantee, not a claim about GPT Voice internals. It prevents capability downgrades, unexpected data movement, duplicate execution, and invisible changes in Agent behavior.

## Agent Selection Plan

Conceptually:

```python
@dataclass(frozen=True)
class AgentCandidate:
    agent_name: str
    model_constraint: str | None = None
    required_capabilities: frozenset[str] = frozenset()

@dataclass(frozen=True)
class AgentSelectionPlan:
    plan_id: str
    version: int
    primary: AgentCandidate
    allowed_fallbacks: tuple[AgentCandidate, ...]
    required_capabilities: frozenset[str]
    max_cost: Decimal | None
    start_deadline_ms: int
    workspace_mode: WorkspaceMode
    data_residency: str | None
    confirmation_on_fallback: ConfirmationRule
    fallback_reason_allowlist: frozenset[str]
```

The exact type may evolve, but the plan must answer:

- which Agent is preferred and why;
- which exact alternatives are acceptable and in what order;
- which capabilities and protocol versions are mandatory;
- whether model/provider substitution is allowed;
- permitted workspace/sandbox/data/credential boundaries;
- cost, latency, concurrency, and token limits;
- which failure reasons permit fallback;
- whether fallback requires Bound Confirmation or only notification;
- whether no fallback is allowed.

The plan is produced before Agent Task creation and stored by digest/version in Agent Task Record and Conversation Journal. Changing it after acceptance is a new policy decision, not mutable retry metadata.

## Legacy single-Agent policy

Existing `choose_agent(content) -> str | None` adapts mechanically:

```text
"codex" -> AgentSelectionPlan(primary="codex", allowed_fallbacks=())
None    -> stay on local Conversation Engine path
```

This preserves deterministic current behavior while allowing richer policy. A missing catalog entry is still a configuration error; it never means "pick any available Agent."

## Health and capability preflight

Before queue dispatch, Supervisor evaluates candidates in plan order against a cached, time-bounded Agent Backend Health snapshot plus task-specific constraints.

Health states:

- `AVAILABLE`: binary/endpoint, authentication/provider, protocol initialize, required model, and mandatory capabilities are currently usable;
- `DEGRADED`: usable under declared reduced performance/noncritical limitations that still satisfy this plan;
- `UNAVAILABLE`: known failure such as missing binary, login/provider/model, incompatible version, open circuit, or exhausted hard quota;
- `UNKNOWN`: probe is stale/incomplete or backend status cannot be trusted.

The snapshot includes observed Driver, binary/protocol/schema/model versions, capability descriptor digest, timestamp/TTL, reason codes, and circuit/rate-limit state. It excludes secrets.

Preflight rules:

1. health checks are bounded and normally cached; a full LLM inference is not required for every turn;
2. an AVAILABLE label cannot override missing required capability or policy scope;
3. DEGRADED may be chosen only if the plan explicitly tolerates the degradation;
4. UNKNOWN is not silently treated as healthy;
5. health says whether a new start is advisable, not whether an earlier start side effect happened;
6. candidate/model/schema version is pinned in Agent Task Record before dispatch;
7. capability or health changes after selection are surfaced, not silently repaired by switching targets.

The local findings from ADR-0053 become concrete health examples: Hermes is UNAVAILABLE because no provider is configured; Claude is UNAVAILABLE because it is not logged in; the PATH Codex/default-model pair is UNAVAILABLE because the CLI is too old for `gpt-5.6-sol`; Codex App Server with tested binary and `gpt-5.4-mini` is AVAILABLE for the verified minimum event path.

## Selection before Backend Commit Point

Agent Task Supervisor selects exactly one candidate while the task remains pre-start:

```text
Agent Selection Plan
       │
       ▼
evaluate primary capability + health + policy
       │
       ├── suitable -> select primary
       │
       └── unsuitable with allowed reason
               -> evaluate explicitly listed fallback in order
                       ├── suitable and permitted -> select fallback
                       └── none -> fail/ask user; do not spawn
```

Selection is atomically persisted with:

- selected Agent/candidate index;
- plan ID/version/digest;
- health/capability snapshot IDs;
- reason primary was not selected;
- whether notification/confirmation is required;
- exact Driver/model/workspace/security configuration;
- selection revision and timestamp.

Only after this record and any required confirmation are accepted may dispatcher cross Backend Commit Point.

## Notification and Bound Confirmation

Fallback is never invisible.

- Low-risk read-only task: if plan and tenant policy pre-authorize the named fallback, the one Delegation Ack identifies the Agent actually selected and may briefly state the primary was unavailable.
- Writable task, sensitive data access, different provider/data residency, weaker isolation, material cost/quality change, or expanded permissions: fallback requires a new Bound Confirmation describing the exact target and changed consequences.
- A previous confirmation bound to primary Agent, model, workspace, or permission digest does not authorize a changed candidate.
- Fallback cannot reduce sandbox strength, broaden Workspace Lease, add scopes, or expose more Conversation Items merely to make execution succeed.
- If the user declines or confirmation expires, no Agent starts.

Notification is generated from trusted selection facts, not Agent text. The system must not say "Codex is working" when Claude or Hermes was actually selected.

## Backend Commit Point

Backend Commit Point occurs immediately before/when the first externally effective backend start request is issued—not when an eventual `AgentRunStarted` callback arrives.

At the commit transaction Supervisor persists:

- selected Agent/Driver/model and immutable dispatch configuration;
- dispatch idempotency token and current fencing token;
- `backend_committed_at` and task revision;
- selected Workspace Lease/policy grant;
- outbox/dispatch ownership.

After this point:

- target Agent cannot change on the same `worker_id`;
- a timeout or lost response is UNKNOWN until reconciled;
- retry may contact only the same backend with the same idempotency token when safe;
- health becoming UNAVAILABLE does not authorize a second backend;
- an error that proves the backend rejected before any execution still terminates/reconciles this attempt according to Driver semantics; cross-Agent continuation is a new Handoff task;
- result, cancellation, and late events remain correlated to the locked target.

This conservative boundary prevents the classic crash window: Agent A accepted work but acknowledgement was lost, so the system starts Agent B and both modify the same repository.

## Post-start failure and Handoff

If a committed task cannot continue on its selected Agent:

1. reconcile exact backend run/session and request cancellation when appropriate;
2. enter a truthful terminal/UNKNOWN state in Agent Task Store;
3. persist progress, partial artifacts, permissions, and known side effects;
4. Result Delivery Policy tells the user what failed or remains uncertain;
5. only explicit user/policy authorization creates a new Delegation Request;
6. new request uses a new `worker_id`, `handoff_from_worker_id`, and Handoff Package;
7. new task independently passes deduplication, selection, policy, confirmation, Workspace Lease, and budgets.

The Handoff Package includes verified partial work and uncertainty. It must not tell the next Agent to repeat side effects whose outcome is unknown. If the original workspace may still be mutated, the new task cannot receive a conflicting writable lease until fencing/reconciliation resolves it.

This is migration, not fallback retry. Both task records remain visible and causal.

## No implicit fan-out or race-to-first

Fallback candidates are sequential alternatives before start, not parallel candidates.

- Supervisor never starts primary and fallback simultaneously to take the first result.
- A health probe does not create an Agent task or modify a workspace.
- Speculative multi-Agent execution requires a distinct explicit fan-out plan under ADR-0052, separate worker IDs, isolated Workspace Leases, and user-visible budget.
- Duplicate callbacks or dispatch retries use the same selected candidate/idempotency token.
- Load balancing among equivalent replicas inside one Driver/backend service is allowed only when it preserves the same declared Agent/model/security semantics and backend idempotency identity; it is not cross-Agent fallback.

## Model and configuration fallback

Agent fallback and model fallback follow the same no-surprise principle.

- A Driver cannot silently replace `gpt-5.6-sol` with `gpt-5.4-mini`, Claude Opus with Sonnet, or a configured Hermes provider with another one unless Agent Selection Plan explicitly allows that candidate/model constraint.
- Provider-native automatic model routing must be disabled when exact model identity is a task requirement or surfaced as an observed reroute event and checked against policy.
- Version, reasoning effort, tools, permission mode, sandbox, cwd/workspace, and plugin/skill configuration are part of the selected execution digest.
- A local smoke may deliberately select a known compatible model; production selection must declare that choice rather than rely on fallback behavior.

## Retry policy

Retries are distinct from fallback:

- before Backend Commit Point, selection/probe operations may retry without spawning;
- after commit, transport retry targets the same backend locator/idempotency token;
- model/API retry inside the same Driver is allowed only if Driver reports it as the same logical run and budgets permit;
- non-idempotent or UNKNOWN start cannot retry blindly;
- a new Agent/model is always a new explicitly authorized task/Handoff after commit.

Retries consume recorded attempt/time/cost budgets and cannot reset counters by changing adapters.

## Observability

Record without raw prompts/secrets:

- plan ID/version and candidate count;
- primary selected versus fallback selected;
- candidate rejection reason codes;
- health/capability snapshot age and version;
- confirmation requested/approved/denied;
- Backend Commit Point timestamp;
- selected Driver/model/workspace/sandbox digest;
- post-commit failure/UNKNOWN and reconciliation duration;
- Handoff creation and source/target worker IDs;
- invariant violation if more than one target is associated with a `worker_id`.

Alerts fire for silent candidate changes, selection after commit, fallback not present in plan, weaker workspace/security configuration, or two backend execution identities under one worker.

## Acceptance checks

1. Unavailable primary plus an explicitly allowed compatible fallback selects only the fallback and emits one truthful Ack.
2. Unavailable primary with no allowed fallback starts nothing and returns an actionable status.
3. Healthy but capability-incompatible candidate is rejected before dispatch.
4. Read-only pre-authorized fallback notifies without unnecessary confirmation.
5. Writable/sensitive/provider-changing fallback cannot start without newly bound confirmation.
6. Backend target becomes immutable at the first start side effect, even when no start callback arrives.
7. Post-commit timeout/UNKNOWN never starts a fallback under the same `worker_id`.
8. Explicit post-failure Handoff creates a new request/worker and preserves causal link/partial artifacts.
9. Fallback cannot weaken sandbox, broaden workspace, permissions, or data visibility.
10. Concurrent selectors for one task atomically persist one selected candidate and one commit owner.
11. Duplicate delivery/retry uses the same target and idempotency token.
12. Agent/model/config rerouting outside the plan is detected and fails or becomes explicit policy input.

## Consequences

- Users know which Agent actually performs work and under which constraints.
- Backend outages do not cause duplicate tasks or invisible quality/security changes.
- Agent availability can be handled automatically for pre-authorized low-risk work without sacrificing auditability.
- Post-start migration is more deliberate and may be slower, but preserves workspace and side-effect correctness.
- DelegationPolicy, BackendCatalog, Agent Task Record, confirmation, and observability gain richer selection types.
- Existing single-Agent policies continue through a no-fallback compatibility adapter.

## References

- [ADR-0031](0031-backend-catalog-and-delegation-policy-agent-selection.md)
- [ADR-0045](0045-multiple-concurrent-delegated-tasks-across-named-agents.md)
- [ADR-0051](0051-server-authoritative-tool-policy-gateway-and-bound-confirmation.md)
- [ADR-0052](0052-durable-agent-task-supervisor-deduplication-and-result-delivery.md)
- [ADR-0053](0053-isolated-agent-execution-sessions-and-codex-first-driver.md)
