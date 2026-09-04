---
status: accepted
---

# Supervise Agent tasks durably, prevent duplicate spawn, and schedule result delivery

**Storage decision — ADR-0055:** Agent Task Store, dispatch outbox, leases,
delivery state, and task/Journal coordination use PostgreSQL transactions in
production. Large results and artifacts use opaque references to an S3-compatible
Artifact Store. In-memory conformers are test-only; SQLite is not a production
path.

**Implemented foundation:** `AgentTaskSupervisor.submit()` resolves the immutable
selection plan, then commits task creation, selected candidate, Backend Commit
Point/dispatch token, and one `agent.dispatch.requested.v1` Outbox message in a
single Persistence Unit of Work. The dispatcher claims only its own message type,
fences every external start by durably incrementing `dispatch_attempt_count`, and
attaches the returned backend handle before acknowledging delivery. A Driver that
declares durable `IDEMPOTENT_START` may retry the same dispatch token; otherwise an
ambiguous or recovered prior attempt becomes `UNKNOWN` and is never automatically
spawned again. Real PostgreSQL tests cover concurrent submit/claim and transactional
rollback; deterministic contract tests cover lost acknowledgement, lease recovery,
and non-idempotent crash windows. Canonical Agent events are now durably sequenced
and deduplicated before state application; terminal ingestion atomically commits
the task result, Conversation Journal item, and one result-delivery Outbox message.
The continuous Supervisor runtime recovers before dispatch, uses bounded error
backoff, and stops cleanly. Drivers without durable resume/status capability are
marked `UNKNOWN` for reconciliation and are never respawned automatically.

All Claude, Codex, Hermes, ACP, and future Agent executions are created and managed by one Agent Task Supervisor in Application Control Plane. The Supervisor owns durable lifecycle, idempotent creation, duplicate suppression, concurrency/fan-out budgets, backend leases, progress ingestion, cancellation, restart recovery, and terminal result delivery. No Router, Conversation Engine, provider callback, Work Registry, or Agent Driver may spawn execution directly.

This expands ADR-0045's multi-Agent concurrency and changes two earlier assumptions: Work Registry becomes a fast live projection rather than durable task authority, and a stale Generation no longer causes a completed Agent result to be discarded. Generation controls immediate speech eligibility; Agent Task Store and Conversation Journal preserve the work and Result Delivery Policy decides when it becomes user-visible.

## Public-alignment boundary

GPT Voice/OpenAI's observable architecture separates realtime conversation from longer-running application/Agent work and correlates results back into the conversation. OpenAI does not publish an internal task supervisor with the exact states, leases, or deduplication rules below. Those are OpenRealtime's necessary reliability layer for multiple replaceable Agent backends and must not be described as private OpenAI implementation details.

## Single spawn authority

Only Agent Task Supervisor may call `Driver.create_session()`, launch an Agent process, submit a remote run, or enqueue a task. Every other module submits a typed `DelegationRequest`:

```python
@dataclass(frozen=True)
class DelegationRequest:
    delegation_request_id: str
    selection_plan: AgentSelectionPlan
    instruction: str
    context: InteractionContext
    workspace_ref: str | None
    input_refs: tuple[str, ...]
    budget: TaskBudget
    parent_worker_id: str | None = None
    force_new: bool = False
```

The request is not execution authority. Supervisor validates identity, Agent Selection Plan, workspace, policy grant, task depth/fan-out, concurrency, and budget before accepting it. It resolves one target before Backend Commit Point according to ADR-0054; a fallback is never interpreted as parallel fan-out.

`AgentSession`/`Driver` remains the backend contract. Driver owns backend-specific launch/auth/session translation; Supervisor owns when and how often it may be invoked.

## Durable Agent Task Record

Agent Task Store persists one revisioned record per accepted task:

- `worker_id` and stable `delegation_request_id`;
- tenant/user/device, `thread_id`, `voice_session_id`, `turn_id`, and originating Generation;
- target Agent name plus Driver/config version;
- canonical instruction/input/workspace digest and optional duplicate fingerprint;
- `parent_worker_id`, root task ID, delegation depth, and fan-out counters;
- policy/grant reference, sandbox/credential profile, and resource budget;
- lifecycle phase, revision, state sequence, timestamps, and blocker reason;
- attempt number, dispatch idempotency token, lease owner/expiry, and fencing token;
- namespaced backend session/run/process identifiers;
- monotonic progress version and latest user-safe progress summary;
- cancellation request/effect status;
- terminal result/error reference and delivery state;
- Conversation Journal item IDs for request, material updates, and terminal result.

Raw secrets, full credentials, and arbitrary backend payloads are not stored in the record. Large output belongs behind authorized content references.

## Lifecycle

The canonical task phases are:

```text
ACCEPTED -> QUEUED -> STARTING -> RUNNING -> SUCCEEDED
                         │          ├──────> FAILED
                         │          ├──────> TIMED_OUT
                         │          └──────> CANCELLING -> CANCELLED
                         └──────────────────> UNKNOWN -> RECOVERING -> ...
```

`WAITING` is a nonterminal running phase with a typed blocker such as permission, user input, rate limit, or external dependency. It does not create a new task.

Rules:

1. transitions are compare-and-swap against record revision;
2. terminal phases are immutable except for delivery/audit metadata;
3. only one current lease/fencing token may cause backend side effects;
4. callbacks carry backend identity plus monotonic event/version keys and are idempotent;
5. out-of-order progress cannot overwrite a newer progress/result;
6. cancellation is idempotent and cannot transition a terminal task back to running;
7. `UNKNOWN` means reconcile before deciding; it never means "spawn another one";
8. an Agent asking for permission moves the existing task to `WAITING`, passes through Tool Policy Gateway, then resumes the same `worker_id`.

## Strong idempotency: never spawn twice for one request

The primary duplicate barrier is `delegation_request_id`, generated before task acceptance and preserved through every retry/reconnect/provider event.

Agent Task Store provides one atomic operation:

```text
create_or_get(scope, delegation_request_id, canonical_request_digest)
```

- no record: atomically create `ACCEPTED`, assign one `worker_id`, return `created=true`;
- same ID and same digest: return the existing record and `created=false`;
- same ID and different digest: return an idempotency conflict;
- terminal existing task: return its result/status; never rerun implicitly.

The uniqueness scope is at least `(tenant_id, thread_id, delegation_request_id)`. A provider retry, duplicated Realtime event, duplicated queue delivery, reconnect replay, HTTP retry, or process retry must carry the same ID and receive the same `worker_id`.

Only the transaction that receives `created=true` may enqueue dispatch. A duplicate path may attach another waiter or return current status, but cannot produce a second Delegation Ack or Agent session.

## Conservative semantic duplicate suppression

Strong idempotency cannot catch a model that invents a new request ID for work already in progress. Supervisor therefore computes a secondary task fingerprint from:

- target Agent/config version;
- normalized instruction and canonical input references;
- workspace/sandbox identity;
- tenant/thread scope and relevant policy version.

Before creating a new task, it checks nonterminal records in a bounded deduplication window:

- exact fingerprint match defaults to reuse the existing `worker_id`;
- likely match may require disambiguation rather than automatic spawn;
- terminal historical matches are not automatically reused unless caller requested cached behavior;
- `force_new=true` permits an intentional duplicate only after policy validates that the user explicitly requested another independent run and budgets allow it.

Semantic fingerprinting is a safety net, not correctness identity. It must prefer asking/reusing over speculative duplication but cannot merge tasks solely on vague text similarity.

Status inquiries, cancellation requests, "is Codex done?", and reconnect restoration resolve existing tasks and are structurally forbidden from entering the create path.

## Dispatch, leases, and crash windows

Task commitment and backend start are separate durable steps:

1. append Delegation Request to Conversation Journal;
2. in one PostgreSQL transaction, `create_or_get` the Agent Task, persist the
   selected candidate and Backend Commit Point, transition to `STARTING`, and write
   one dispatch Outbox row keyed by `worker_id` plus dispatch token;
3. dispatcher claims the Outbox row with a time-bounded lease and monotonically
   increasing Outbox fencing token;
4. atomically increment the task's `dispatch_attempt_count` immediately before the
   external start call;
5. start backend with `worker_id`/dispatch token as its idempotency key where
   supported;
6. persist backend run/session identity before `RUNNING`;
7. acknowledge Outbox delivery only after handle persistence;
8. renew runtime lease/heartbeat while supervising the task.

Lease expiry never directly causes a replacement spawn. A recovery owner first queries the backend using stored identifiers/idempotency token:

- backend still running: adopt/reattach and continue with a new fencing token;
- backend terminal: ingest terminal outcome idempotently;
- backend confirms never started: dispatch within the same task attempt rules;
- backend status unknowable: mark `UNKNOWN`, retry reconciliation, and require policy/manual resolution before any potentially duplicate start.

For a backend that cannot provide idempotent start or run lookup, Supervisor must wrap it in a locally durable single-owner process/queue boundary or classify restart recovery as unsafe. It may not blindly create another remote task after a crash between spawn and ID persistence.

## Concurrency and fan-out control

Multiple tasks are supported, but unbounded spawn is not:

- per Voice Session, user, tenant, target Agent, and workspace concurrency limits;
- queue depth and rate limits;
- per-task wall-clock, token, cost, filesystem, and tool budgets;
- root-task maximum delegation depth and total descendant count;
- maximum sibling fan-out per Agent action;
- circuit breakers for repeated backend failures or permission loops;
- fair scheduling so one session cannot starve others.

An Agent cannot directly spawn another Agent. It may emit a nested Delegation Request, which returns to Supervisor with `parent_worker_id`, consumes root fan-out/depth budget, passes policy, and receives its own deduplicated `worker_id`. Default policy may forbid nested delegation entirely.

One model response must not implicitly broadcast the same task to Claude, Codex, and Hermes. Multi-Agent fan-out requires an explicit orchestration plan that names each target and gives each child a distinct request ID/purpose.

## Work Registry and restart recovery

Work Registry is the live projection used by Conversation Kernel for fast questions such as "which tasks affect this Voice Session?" It is populated from Agent Task Store events and can be rebuilt.

On process/session recovery:

1. query nonterminal tasks for the tenant/thread/Voice Session;
2. load records into Work Registry without calling any Driver create/start method;
3. reconcile leases and backend handles through Supervisor;
4. resume progress subscriptions where supported;
5. restore pending result notifications and confirmations;
6. create a new Agent execution only for a genuinely new accepted Delegation Request.

Conversation Journal replay never spawns tasks. Journal records explain semantic history; Agent Task Store/outbox controls execution.

## Progress and status inquiries

Backend progress is normalized as monotonic `AgentTaskProgress` with `worker_id`, progress version, phase, optional percent/stage, and user-safe summary.

- high-frequency backend logs remain operational and need not enter Conversation Journal;
- material milestones may be journaled;
- latest safe progress is cached in Agent Task Record/Work Registry;
- stale or duplicate progress versions are ignored;
- StatusInquiryClassifier detects progress intent, then a resolver identifies the task by explicit `worker_id`, Agent name, ordinal/reference, or recent context;
- if multiple tasks match, the system asks which task instead of guessing or spawning;
- status replies read existing records and never call `send_turn` again.

## Terminal outcome and Result Delivery Policy

Terminal callbacks never speak directly. Supervisor performs:

1. validate callback identity/version and atomically enter one terminal phase;
2. persist result/error reference in Agent Task Store;
3. append one correlated terminal Conversation Item to Conversation Journal;
4. emit `AgentTaskCompleted`/`Failed`/`Cancelled` Voice Event;
5. let Result Delivery Policy choose presentation;
6. mark delivery outcome idempotently so reconnect cannot announce it twice.

Delivery decisions are:

| Decision | When | Behavior |
|---|---|---|
| `ANNOUNCE_WHEN_IDLE` | User is explicitly awaiting it and no newer dialogue owns the floor | Queue one concise result for the next safe boundary |
| `QUEUE_NOTIFICATION` | User changed topic, session is busy/disconnected, or several tasks finish | Preserve notification; optionally group results |
| `SILENT_UNTIL_ASKED` | Low-value/internal completion or policy preference | Available through status/history, no unsolicited speech |
| `URGENT_PREEMPT` | Server policy marks a genuinely time/safety-critical outcome | May interrupt at a safe boundary using normal cancellation rules |

Urgency is assigned by trusted server policy, never by Agent-produced text or callback flags. Normal success and failure do not preempt user speech or active assistant output. Multiple non-urgent completions may be summarized together, but each retains its own `worker_id` and result.

Originating Generation affects only immediate-announcement eligibility. A stale result remains durable and is normally queued rather than discarded. Result delivery creates a fresh correlated response turn/generation when it is eventually announced.

## Delegation Ack deduplication

Exactly one Delegation Ack is emitted only when a new task is accepted (`created=true`). If a request resolves to an existing task:

- running/waiting: report the existing status only when conversationally useful;
- terminal: return or schedule the existing result;
- cancelled/failed: do not restart unless a new explicit request passes retry policy;
- ambiguous semantic duplicate: ask whether the user wants to reuse or intentionally create another run.

Ack delivery itself has a durable delivery key so transport retry/reconnect cannot replay it as a second "I started" announcement.

## Cancellation

- Cancel targets an existing `worker_id`; task resolution must be unambiguous.
- Repeated cancel requests return the same cancellation state and invoke backend cancellation at most once per attempt/fencing token.
- Barge-in cancels speech output, not Agent tasks.
- New user topics do not implicitly cancel unrelated tasks.
- Cancellation may be pending/ineffective if the backend cannot stop; the system reports actual state rather than declaring success early.
- A late success racing with cancel is resolved by atomic lifecycle transition and backend evidence; result is retained even if delivery policy suppresses it.
- Restarting a cancelled/failed task requires a new Delegation Request ID and explicit retry policy; it never reuses the old task as if it were running.

## Failure behavior

- Store unavailable before `create_or_get`: no spawn occurs.
- Journal unavailable in durable mode before request acceptance: no spawn occurs.
- Dispatch message duplicated: unique outbox key and lease return the same task.
- Provider/Agent callback duplicated: event version/idempotency key makes it a no-op.
- Lease lost: old owner is fenced; new owner reconciles before acting.
- Backend unreachable: task remains running/unknown with bounded recovery, not automatically failed-and-respawned.
- Result persistence fails: keep terminal backend evidence in reconciliation queue; do not announce an uncommitted authoritative result.
- Delivery fails/disconnects: notification remains pending and can be delivered once after reconnect.
- Driver crashes repeatedly: circuit breaker stops new dispatches to that Agent and queued tasks remain explicit.

## Observability

Metrics and traces include:

- create attempts vs. new/reused/conflicted/semantic-deduped decisions;
- spawn count per `worker_id` and backend dispatch token;
- queue/start/run/wait/cancel/terminal durations;
- lease takeovers, reconciliation outcomes, and unknown-state age;
- progress callback duplicate/out-of-order counts;
- concurrency, queue depth, fan-out, budget exhaustion, and circuit-breaker state;
- result delivery decision, queue age, attempts, and duplicate suppression;
- Agent/backend/version tags without raw instructions, secrets, or task result content.

An invariant alert fires if more than one backend execution is observed for the same `worker_id`/dispatch token or two live tasks share a strong Delegation Request ID.

## Acceptance checks

1. One hundred concurrent retries of the same Delegation Request create one `worker_id`, one outbox entry, and at most one backend execution.
2. Duplicate Realtime/provider/queue callbacks cannot create or complete a task twice.
3. Reconnect and Conversation Journal replay rebuild Work Registry without invoking Agent start.
4. Crash at every point between task acceptance and backend ID persistence either reattaches/reconciles or stays `UNKNOWN`; it never blind-spawns.
5. Status and cancellation utterances cannot enter the creation path.
6. Exact active semantic duplicate reuses the task unless a policy-approved explicit `force_new` is present.
7. Nested Agent delegation respects depth, fan-out, concurrency, and budget limits.
8. One task completion cannot speak over active user/assistant audio unless server policy returns `URGENT_PREEMPT`.
9. Stale-Generation results remain durable and deliverable without affecting stale output leases.
10. Ack and result notification are each delivered at most once across transport retry/reconnect.
11. Terminal/cancel state cannot transition back to running.
12. Claude, Codex, Hermes, and deterministic fake Drivers pass the same supervisor contract suite.

## Consequences

- Multi-Agent concurrency becomes bounded and recoverable instead of "one coroutine per request."
- Duplicate spawn is prevented at storage, dispatch, lease, backend, and delivery boundaries.
- Agent state survives process/session reconnect independently from provider conversation state.
- Results are not lost when the user changes topic and do not interrupt conversation by default.
- Work Registry and Agent Session implementations become simpler projections/adapters behind one supervisor.
- Durable Task Store, dispatch outbox, reconciliation, fencing, and delivery state add implementation cost but are required before safe production multi-Agent execution.

## References

- [ADR-0006](0006-delegation-latency-ack-pull-status-error-gating.md)
- [ADR-0008](0008-status-inquiry-classifier-and-single-inflight-delegation.md)
- [ADR-0045](0045-multiple-concurrent-delegated-tasks-across-named-agents.md)
- [ADR-0046](0046-first-class-identity-and-correlation-context.md)
- [ADR-0049](0049-separate-realtime-session-plane-from-application-control-plane.md)
- [ADR-0050](0050-server-owned-conversation-journal-as-authoritative-history.md)
- [ADR-0051](0051-server-authoritative-tool-policy-gateway-and-bound-confirmation.md)
