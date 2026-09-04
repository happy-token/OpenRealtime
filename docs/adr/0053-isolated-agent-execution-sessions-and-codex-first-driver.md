---
status: accepted
---

# Isolate every Agent execution session and use Codex App Server as the first conformance backend

**Implemented foundation:** Codex App Server, Claude stream-json, and Hermes ACP
are constructible from one declarative backend catalog and conform to the same
v2 `AgentDriver` interface. Claude and Hermes expose only capabilities they can
actually guarantee; neither claims durable resume or idempotent start. Exact
worker-to-process/session cancellation is tested, and ACP permissions now reject
by default unless an explicit policy grants them.

Each Delegated Task owns one isolated logical Agent Execution Session correlated to exactly one `worker_id`. Backend processes, daemons, network connections, and model clients may be pooled, but task history, permissions, workspace access, backend session IDs, event streams, and cancellation must remain isolated. Cross-task or cross-Agent continuation occurs only through an explicit resume or Handoff Package.

OpenRealtime will replace the current minimal Agent Session Protocol with a universal Agent Driver Protocol suitable for Agent Task Supervisor. `CodexAppServerDriver` is selected as the first full-conformance real backend because the locally installed Codex App Server exposes thread/turn lifecycle, streaming item events, explicit resume, status, steering, interruption, approval requests, sandbox configuration, and structured terminal outcomes. ACP/Hermes and Claude stream-json remain additional Drivers behind the same contract.

This is a OpenRealtime modularity decision. OpenAI publishes Codex App Server interfaces, but the cross-vendor Agent Driver Protocol, workspace leases, and conformance suite are ours rather than GPT Voice private internals.

## Runtime isolation versus logical isolation

One operating-system process per task is not required. One logical session per task is required.

```text
Agent Task Supervisor
  ├── worker A -> Agent Execution Session A -> Codex thread A
  ├── worker B -> Agent Execution Session B -> Codex thread B
  └── worker C -> Agent Execution Session C -> Hermes ACP session C

Codex app-server process may be shared by A and B
but thread/history/workspace/events/permissions remain disjoint.
```

Invariants:

1. one live `worker_id` maps to at most one logical Agent Execution Session;
2. one backend session/thread/run cannot be owned by two unrelated workers;
3. process reuse never implies history or authorization reuse;
4. native backend IDs are namespaced by Driver and stored as opaque locators;
5. every event is checked against the mapped `worker_id` and backend locator;
6. cancellation, input, steering, permission responses, and results target an exact session/run—not "latest";
7. terminal task state remains immutable even if a backend thread can technically accept more turns.

## Universal Agent Driver Protocol

The target contract is lifecycle- and event-oriented:

```python
class AgentDriver(Protocol):
    async def capabilities(self) -> AgentCapabilityDescriptor: ...
    async def start(self, request: AgentStartRequest) -> AgentRunHandle: ...
    async def resume(self, locator: AgentRunLocator) -> AgentRunHandle: ...
    async def status(self, handle: AgentRunHandle) -> AgentRunSnapshot: ...
    def events(self, handle: AgentRunHandle, *, after: EventCursor | None = None) \
        -> AsyncIterator[AgentEvent]: ...
    async def send_input(self, handle: AgentRunHandle, input: AgentInput) -> None: ...
    async def cancel(self, handle: AgentRunHandle, reason: str) -> CancelResult: ...
    async def close(self, handle: AgentRunHandle) -> None: ...
```

The concrete Python types may evolve, but these semantics are fixed:

- `start` receives Supervisor's `worker_id`, dispatch idempotency token, Workspace Lease, policy grant, budget, and Handoff Package/Conversation Projection;
- `start` either creates/reattaches the same backend execution for that token or reports that idempotent start is unsupported before any side effect;
- `AgentRunHandle` contains opaque backend locators and capability/version snapshot, not credentials;
- `events` emits ordered typed events and exactly one terminal outcome per backend run attempt;
- `status` is authoritative backend reconciliation, not cached progress text;
- `resume` reattaches an existing backend locator and never creates a new task implicitly;
- `send_input` is allowed only for a nonterminal task waiting for input/steering;
- `cancel` is idempotent and reports requested versus actually stopped;
- `close` releases client resources but does not claim the backend work was cancelled.

Current `Driver.create_session()` plus `AgentSession.send_turn/latest_update/cancel/result` remains behind a legacy adapter during migration. It cannot claim full conformance because it has no capabilities, status lookup, idempotent start, durable locator, event cursor, or explicit resume.

## Agent Capability Descriptor

Every Driver reports versioned capabilities before Supervisor dispatches:

| Capability | Meaning |
|---|---|
| `idempotent_start` | Backend accepts a stable dispatch token or Driver provides an equivalent durable wrapper |
| `status_lookup` | Existing run can be queried after lost connection/process restart |
| `resume` | Existing logical session can be reattached by stored locator |
| `event_stream` | Ordered progress/output/terminal events are available |
| `event_replay` | Events can resume after a durable cursor |
| `steering` | Input can be sent to an active run without starting another task |
| `cancel` | Backend supports an explicit cancellation request |
| `permission_bridge` | Tool/file/command approvals arrive as structured requests |
| `workspace_isolation` | Backend can enforce supplied Workspace Lease/sandbox boundaries |
| `structured_result` | Terminal result can conform to a requested output schema |
| `artifact_manifest` | Changed/created artifacts can be reported explicitly |
| `usage_reporting` | Tokens/cost/time are available for budget reconciliation |

Capability absence is not simulated with a no-op. Supervisor either selects a safe fallback policy, wraps the Driver with a real enforcement layer, or rejects a task whose requirements cannot be met. BackendCatalog may state required capabilities; startup health fails when actual capability negotiation does not satisfy them.

## Canonical Agent events

Drivers normalize native callbacks into an ordered union:

- `AgentRunStarted`;
- `AgentProgressUpdated`;
- `AgentMessageDelta` and optional completed message;
- `AgentPlanUpdated`;
- `AgentPermissionRequested`;
- `AgentInputRequested`;
- `AgentArtifactPublished`;
- `AgentUsageUpdated`;
- `AgentRunWaiting`;
- `AgentRunSucceeded`, `AgentRunFailed`, `AgentRunCancelled`, or `AgentRunTimedOut`.

Every event carries `worker_id`, backend kind/version, backend locator, event identity/cursor, attempt, timestamp, and task-record revision/fencing token where relevant. Permission requests are routed to Tool Policy Gateway. Native reasoning text is not automatically user-visible and must follow provider and application policy.

## Workspace Lease

Every task receives one explicit Workspace Lease rather than a bare ambient `cwd`:

| Mode | Intended use | Default concurrency |
|---|---|---|
| `READ_ONLY` | analysis, review, explanation | Multiple readers allowed |
| `PRIVATE_WRITABLE` | code/document changes in isolated copy or git worktree | One worker owns its private workspace |
| `EXCLUSIVE_SHARED` | deliberately modify the canonical workspace | One fenced writer; explicit policy/confirmation |

Rules:

- writable coding tasks default to `PRIVATE_WRITABLE`;
- two Agents never write the same canonical workspace concurrently by default;
- lease contains canonical path/reference, mode, allowed roots, expiry, owner `worker_id`, and fencing token;
- Driver receives only paths permitted by the lease;
- sandbox/tool permission cannot broaden the lease;
- lease loss fences further writes and moves the task to recovery/cancellation;
- Supervisor reconciles or releases leases on terminal state and restart;
- uncommitted user changes in a shared workspace are preserved and never reset/reverted by Agent setup.

Task artifacts are published as an explicit manifest: path/content reference, media type, digest, source `worker_id`, and disposition. Another Agent consumes them through a Handoff Package rather than discovering mutable files by sharing an undocumented cwd.

## Resume and continuation

"Resume" has two precise forms:

### Reattach a nonterminal task

Supervisor uses the same `worker_id` and stored backend locator after connection/process loss. This does not append a new Delegation Request, emit another Ack, or call backend start.

### Continue a terminal task

Terminal state is immutable. A user may explicitly continue from an old `worker_id`; Supervisor creates a new Delegated Task/new `worker_id` with `resume_from_worker_id`, a new Delegation Request ID, refreshed policy/budget/Workspace Lease, and—when safe—asks Driver to fork/resume the old backend context. The causal link is explicit and deduplicated.

Drivers may never implement either form as "resume the latest session in this cwd." Exact stored IDs are mandatory. If a backend cannot safely resume, Conversation Journal/Handoff Package builds a fresh projection and the new task starts without hidden continuity.

## Cross-Agent handoff

A task moving from Claude to Codex, Codex to Hermes, or another pair receives a Handoff Package containing:

- objective and explicit reason for handoff;
- constraints, acceptance criteria, and remaining budget/deadline;
- source `worker_id` and relevant Conversation Item IDs;
- selected user/assistant/tool result excerpts or references;
- artifact manifest references and digests;
- workspace lease proposal;
- completed work, unresolved questions, known risks, and requested next action;
- policy/visibility labels without credentials.

The receiving Agent does not gain access to the source Agent's private session history, credentials, scratch reasoning, or workspace simply because a handoff occurred. Conversation Projector creates a provider-specific input from the canonical package.

## Codex App Server mapping

`CodexAppServerDriver` maps the universal contract as follows:

| Agent Driver Protocol | Codex App Server |
|---|---|
| start logical session | `thread/start` with explicit cwd/model/approval/sandbox/permissions |
| start Agent run/input | `turn/start` with stable `clientUserMessageId`/Supervisor correlation |
| stream events | `turn/*`, `item/*`, token usage, warning/error notifications |
| active steering/input | `turn/steer` with exact expected turn ID |
| cancel | `turn/interrupt` with exact thread/turn ID |
| status/history | thread status notifications plus `thread/read`/turn reads |
| reattach | `thread/resume` with exact thread ID/path/history policy |
| permission boundary | command/file/permissions and dynamic-tool server requests are normalized; the initial conformer denies them fail-closed until Tool Policy Gateway can return a bound decision |
| artifacts | target: turn diff/file-change items projected to an artifact manifest; not claimed by the initial capability descriptor |
| terminal | `turn/completed` status and completed Agent message/result items |

One OpenRealtime `worker_id` owns one Codex thread for the duration of a logical task. A shared App Server daemon/process may host many such threads. Server requests are correlated to thread/turn/item and routed through Tool Policy Gateway; no automatic approval is allowed.

App Server is currently marked experimental as a top-level CLI command and its local schema may evolve. Driver therefore pins a minimum/maximum tested protocol/binary version, performs initialize/capability probing, and uses generated schemas as test fixtures. Unknown required notifications/requests fail explicitly; additive unknown notifications may be recorded and ignored only when safe.

## Local backend evaluation on 2026-08-08

Three requested backend families were inspected without changing account or provider configuration:

| Candidate | Installed evidence | Real smoke outcome | Decision |
|---|---|---|---|
| Hermes | `hermes` exists; `hermes acp --check` succeeds; current `AcpDriver` completes ACP initialize/session negotiation | Inference returns `No LLM provider configured` | Keep as second ACP conformance backend after user configures provider |
| Claude Code | `claude 2.1.222`; supports print/stream-json, session IDs/resume, tools and permission modes | Returns `Not logged in` | Driver candidate, not currently runnable |
| Codex PATH CLI | `/opt/homebrew/bin/codex`, `0.139.0` | default `gpt-5.6-sol` rejected as requiring newer CLI; explicit `gpt-5.4-mini` read-only ephemeral JSONL run completed with `CODEX_AGENT_OK` | Runnable but older binary and noisy startup |
| Codex App binary | `/Applications/ChatGPT.app/Contents/Resources/codex`, `0.147.0-alpha.6.5` | App Server initialize, ephemeral read-only `thread/start`, `turn/start`, message delta `CODEX_APP_SERVER_OK`, and terminal `completed` all succeeded | Selected first formal Driver target |

The successful App Server smoke observed independent thread and turn IDs plus notifications including `thread/started`, `turn/started`, `item/started`, `item/completed`, `item/agentMessage/delta`, token usage, and `turn/completed`. The client denied any reverse server request; none was needed. No project file was modified.

That original exploratory smoke proved local availability and the minimum event path
only. The checked-in conformer tests below extend the evidence; durable resume,
bound permission approval, artifact projection, and workspace fencing still require
their persistence/policy implementation slices.

## Initial conformer implementation status

The first checked-in `CodexAppServerDriver` now passes deterministic tests for
independent worker threads, in-process dispatch-token reuse, ordered message/plan/
usage/terminal translation, interruption, status lookup, and operation behind the
universal Supervisor. A gated live read-only test against the installed App Server
also completed with `CODEX_APP_SERVER_DRIVER_OK`.

Its capability descriptor deliberately does **not** claim durable idempotent start,
permission bridging, or artifact manifests. Reverse server requests are surfaced as
typed events and immediately denied; approval will be added only through Tool Policy
Gateway. Cross-process duplicate prevention and recovery depend on the PostgreSQL
Task Store/outbox/reconciler from ADR-0052/0055, not the Driver's in-memory dispatch
map.

## BackendCatalog and binary selection

BackendCatalog entries become typed and versioned, for example conceptually:

```yaml
codex:
  driver: codex-app-server
  command: /Applications/ChatGPT.app/Contents/Resources/codex
  tested_version: 0.147.0-alpha.6.5
  model: gpt-5.4-mini
  required_capabilities: [resume, status_lookup, event_stream, steering, cancel, permission_bridge]
  workspace_policy: private-writable
```

The concrete configuration must not hard-code this user's machine path as a framework default. Startup discovery considers explicit config first, then known installations/PATH, reports all candidates and versions, and selects only one satisfying version/capability policy. It never silently switches binaries or models after a task is accepted.

Provider/model configuration is health-checked before dispatch. A missing Hermes provider, unauthenticated Claude, unsupported Codex model, or stale CLI is an unavailable backend state, not a reason to spawn repeated tasks or silently route to another Agent unless DelegationPolicy explicitly permits fallback.

## Conformance test suite

Every real Driver runs the same deterministic contract tests using a fake backend and optional gated live tests:

1. capabilities/version negotiation;
2. one start token creates one logical backend session under concurrent retries;
3. independent workers never share history/events/permissions;
4. ordered progress/message/terminal event normalization;
5. status and reattach after connection loss;
6. active steering/input targets the exact run;
7. cancellation is idempotent and reaches a terminal/reconciled outcome;
8. permission request routes through Tool Policy Gateway and denial unblocks safely;
9. Workspace Lease read/write boundaries and fencing;
10. terminal result/artifact/usage mapping;
11. crash and unknown-event/version handling;
12. close releases client resources without inventing task cancellation.

Live tests are opt-in and skip with a precise unavailable reason when the binary, login, provider, model, or network is absent. Unit/CI correctness never depends on a paid external Agent.

## Failure behavior

- Driver capability mismatch before start: task stays queued/failed-unavailable; no backend execution.
- Missing auth/provider/model: explicit backend-unavailable health, no retry storm.
- Backend connection loss: Supervisor uses stored locator/status before any new start.
- Event for unknown thread/run: quarantine/audit; never attach it to the latest task.
- Duplicate or out-of-order event: idempotency cursor/version prevents repeated progress/result.
- Permission request without Tool Policy Gateway decision: deny/fail closed.
- Workspace Lease mismatch/expiry: fence writes and reconcile/cancel.
- Binary/schema version outside tested range: fail startup or require explicit compatibility override.
- Backend terminal without result: structured failure, never empty success.
- Process pool/daemon crash: affects transport health but does not merge or recreate logical tasks.

## Consequences

- Claude, Codex, Hermes, ACP, and future Agents can share Supervisor/state/delivery behavior without pretending their native protocols are identical.
- Per-task isolation prevents hidden context, permission, and workspace leakage.
- Shared backend processes remain efficient while logical sessions stay independent.
- Explicit Handoff Packages make cross-Agent collaboration reproducible and auditable.
- Codex App Server provides a locally verified first integration target with richer lifecycle control than one-shot CLI execution.
- Existing ACP Driver remains useful but needs a v2 adapter/capability declaration and a configured Hermes/OpenCode provider for live conformance.

## References

- [Codex App Server non-Realtime interface reference](../GPT-Voice/09-Codex-App-Server非Realtime接口参考.md)
- OpenAI, [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [ADR-0031](0031-backend-catalog-and-delegation-policy-agent-selection.md)
- [ADR-0045](0045-multiple-concurrent-delegated-tasks-across-named-agents.md)
- [ADR-0051](0051-server-authoritative-tool-policy-gateway-and-bound-confirmation.md)
- [ADR-0052](0052-durable-agent-task-supervisor-deduplication-and-result-delivery.md)
