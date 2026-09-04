---
status: accepted
---

# Put every tool request behind a server-authoritative Tool Policy Gateway

**Implemented foundation:** versioned Tool Descriptors and exact registry
bindings now feed a fail-closed Policy Gateway with schema/scope checks,
argument digests, bound confirmations, single-use execution grants, and durable
PostgreSQL authorization records. The bounded Fast Tool Loop journals requests
and outcomes and enforces call/time budgets. The live Pipeline Engine path now
normalizes `ToolCallingBrain` requests into `CallToolAction`, executes them only
through the application Policy Gateway, and resumes from correlated feedback.
The direct `ToolCallingBrain.respond` method remains a legacy compatibility API
for isolated callers and must not be used as a production authorization path.

Current limit: a protected action is stopped, persisted as a bound confirmation,
and converted to safe spoken/model feedback without invoking its handler. The
authenticated client decision frame and exact-confirmation resume flow are not
yet connected, and the current adapter permits one tool round-trip per turn.

Every tool invocation in OpenRealtime is an untrusted Tool Request until the Application Control Plane authorizes it. Conversation Engines, OpenAI Realtime, MCP servers, local Brains, Skills, clients, and external Agents may propose work; none may grant themselves permission. One replaceable Tool Policy Gateway validates the request and returns exactly one decision: allow with a scoped Execution Grant, require Bound Confirmation, route to background delegation, or deny.

This decision replaces `AcpDriver`'s legacy auto-approve default from ADR-0017 and extends ADR-0044's Fast Tool Loop. It also follows OpenAI's published boundary: Realtime function tools leave business logic and approval checks to the application, while Realtime MCP exposes allowed-tool filtering and explicit approval request/response items. OpenRealtime generalizes that observable pattern across every tool source and Agent backend.

## Trust model

The following inputs are always untrusted:

- tool name and arguments emitted by any model;
- function/MCP events emitted by a realtime provider;
- tool declarations dynamically imported from a remote MCP server;
- permission requests emitted by Claude, Codex, Hermes, ACP, or another Agent backend;
- client-provided tool lists, confirmation text, or claimed capabilities;
- URLs, files, commands, identifiers, and structured content returned by tools.

Schema-valid is not authorized. Model-selected is not user-approved. Provider-executed is not policy-approved. Tool output is not trusted merely because execution succeeded.

## Split public description from private execution

The current `CanonicalTool` combines model-visible schema with a Python handler. The target Canonical Tool Schema separates them:

```python
@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    version: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema | None
    effects: frozenset[ToolEffect]
    risk: RiskLevel
    idempotency: IdempotencyClass
    latency: LatencyClass
    confirmation: ConfirmationRequirement
    required_scopes: frozenset[str]
    data_classes: frozenset[DataClass]
    default_timeout_ms: int

@dataclass(frozen=True)
class ToolBinding:
    descriptor: ToolDescriptor
    executor: ToolExecutor
    credential_profile: str | None
    sandbox_profile: str | None
```

`ToolDescriptor` may be projected to models after policy filtering. `ToolBinding`, handlers, credential references, sandbox configuration, and server endpoints stay private inside Tool Registry/Application Control Plane.

All descriptors are versioned. A Tool Request resolves an exact version before authorization. Updating a tool's implementation or risk metadata cannot silently change a pending confirmation or retry.

## Required metadata

Every registered tool declares at least:

### Effects

`effects` is a set because one operation may both read sensitive data and send an external message:

- `NONE`: pure computation with no external observation or mutation;
- `READ_PUBLIC`: read public/non-sensitive information;
- `READ_SENSITIVE`: read tenant, user, private, or regulated information;
- `WRITE_REVERSIBLE`: change external state with a documented rollback path;
- `WRITE_IRREVERSIBLE`: delete, overwrite, publish, or otherwise make recovery difficult;
- `EXECUTE_CODE`: run shell, code, build, or automation;
- `COMMUNICATE_EXTERNAL`: send email/message, publish, create ticket, or contact another person/system;
- `SPEND_OR_TRANSFER`: purchase, payment, transfer, resource commitment, or billable provisioning;
- `CONTROL_DEVICE`: act on physical or safety-relevant equipment.

Unknown or missing effects are treated as the most restrictive category, never `NONE`.

### Risk

`risk` is the maximum declared baseline risk before contextual policy raises it:

| Level | Typical examples | Default disposition |
|---|---|---|
| `LOW` | clock, public search, deterministic formatting | Auto-allow within limits |
| `MEDIUM` | private read, reversible workspace edit | Policy allow or voice confirmation |
| `HIGH` | shell/code execution, external communication, deletion, account changes | Bound Confirmation plus sandbox/scopes |
| `CRITICAL` | credential export, broad destructive command, money transfer, unsafe device control | Stronger authorization or deny |

Tool metadata can raise the floor but cannot lower tenant policy. Argument values, target scope, user role, environment, and accumulated turn cost may raise the effective risk dynamically.

### Idempotency

- `IDEMPOTENT`: retrying the same canonical request is safe;
- `KEYED`: safe only with a server-issued idempotency key honored by the backend;
- `NON_IDEMPOTENT`: automatic retry forbidden;
- `UNKNOWN`: treated as non-idempotent.

`call_id` is correlation, not automatically an idempotency key. Tool Executor receives an explicit server-issued key through Execution Grant when the binding supports it.

### Latency

- `FAST`: expected to finish inside the Fast Tool Loop budget;
- `VARIABLE`: may run inline only when current deadline and historical latency allow;
- `BACKGROUND`: always becomes a Delegated Task/background job.

Descriptor latency is a routing hint, not a promise. Tool Policy Gateway may route any request to background based on arguments, load, remaining turn deadline, or observed p95. Crossing the inline deadline yields a structured deferred/timeout outcome; it does not hold the voice loop indefinitely.

### Confirmation

- `POLICY`: default policy decides from effective risk and context;
- `ALWAYS`: every invocation requires Bound Confirmation;
- `STRONG`: requires an authenticated non-voice or otherwise stronger channel;
- `FORBIDDEN`: the tool cannot be invoked from voice sessions.

There is deliberately no tool-level `NEVER_CONFIRM` override. Low-risk policy may auto-allow, but a descriptor cannot prevent tenant or contextual policy from requiring confirmation.

## Policy decisions

Tool Policy Gateway returns a typed decision:

```text
Allow(ExecutionGrant)
RequireConfirmation(PendingConfirmation)
DelegateBackground(DelegationRequest)
Deny(reason_code, safe_message)
```

Policy evaluation includes:

- authenticated tenant/user/device and Voice Session policy;
- exact tool name/version and validated canonical arguments;
- effects, effective risk, data classification, and required scopes;
- origin: Native Engine, Pipeline Brain, MCP, Agent, client, or application;
- per-call and per-turn time/cost budgets;
- sandbox/workspace boundary and target resource;
- rate limits and concurrent-work limits;
- pending confirmation and prior decision state;
- idempotency/retry status;
- current Voice Session Phase, Generation, and cancellation state.

Policy is deterministic for the same versioned inputs. The decision records a policy version and reason code so audits can explain why two superficially similar requests differed.

## Execution Grant

An allow decision produces a short-lived Execution Grant containing at least:

- `decision_id`, `call_id`, and policy version;
- subject (`tenant_id`, `user_id`, optional device/workspace identity);
- `voice_session_id`, `thread_id`, `turn_id`, and originating Generation;
- exact tool name and version;
- digest of canonical validated arguments;
- allowed scopes, target restrictions, sandbox profile, and credential-profile reference;
- timeout, cost ceiling, attempt limit, expiry, and idempotency key/class;
- linked `confirmation_id` when confirmation was required.

Tool Executor rejects absent, expired, already-consumed, mismatched, or over-budget grants. A grant is not a bearer API key exposed to the model or client; it is an internal capability reference resolved server-side. Credential Broker/Tool Binding injects actual credentials only at execution time.

## Bound Confirmation

Confirmation is a protocol state, not conversational sentiment.

`PendingConfirmation` binds:

- `confirmation_id` and expiry;
- user/tenant/Voice Session/thread identity;
- exact tool/version and canonical argument digest;
- plain-language action summary including target and important effects;
- effective risk and requested scopes;
- confirmation channel strength required;
- one-time nonce/action digest.

Approval must match the pending `confirmation_id` and action digest. A later argument change invalidates it. Approval is single-use and cannot authorize a retry with changed inputs, another tool, another target, or another user.

Voice confirmation is acceptable only for policy-approved medium-risk or narrowly scoped high-risk actions in an already authenticated session. Voiceprint remains an informational signal, not authentication. Critical actions use a stronger channel or are denied. Ambiguous responses, background speech, timeouts, Barge-in during the prompt, or multiple pending candidates do not approve anything.

Barge-in cancels the current confirmation prompt output, not the `PendingConfirmation` record. A Voice Session exposes at most one foreground confirmation. A later utterance resolves it only when the decision is explicit and uniquely correlated to the same unexpired `confirmation_id`, action digest, and subject; an unrelated topic leaves it pending until expiry or a policy-controlled re-prompt. After same-session semantic resume, the Runtime must restate the exact action, target, and material consequence before accepting a voice decision. A new Voice Session continuation cannot reuse the old Voice Session-bound approval and must authorize the action again with a new confirmation when still applicable.

The user-facing prompt must say what will happen, where, and whether it is reversible. It must not ask a generic "continue?" when the action involves deletion, external communication, code execution, money, or sensitive data.

## End-to-end flow

```text
Model / Provider / Agent emits proposed tool action
                 │
                 ▼
Tool Normalization resolves ToolDescriptor + exact version
                 │
                 ▼
Strict input-schema validation and canonicalization
                 │
                 ▼
Tool Policy Gateway evaluates identity, effects, risk, budget, scopes
       ┌─────────┼─────────────┬───────────┐
       ▼         ▼             ▼           ▼
     Deny   Confirmation   Background   Execution Grant
                 │                         │
       exact bound approval                │
                 └──────────────┬──────────┘
                                ▼
               Journal call intent + policy decision
                                │
                                ▼
               Tool Executor resolves private binding/credentials
                                │
                                ▼
                  validate/sanitize structured result
                                │
                                ▼
                  Journal result, then reinject Voice Event
```

Journal ordering follows ADR-0050: call intent and authorization are accepted before side effects; authoritative result is accepted before reinjection. Event Ledger receives operational timing/decision events but cannot authorize or execute.

## Tool exposure and discovery

Models receive the minimum allowed tool surface for the current session:

1. Tool Registry aggregates local function, MCP, Skill, and application sources.
2. Tool Policy Gateway filters descriptors by tenant, user, Engine capabilities, session mode, and policy.
3. Provider adapter projects only public names/descriptions/strict input schemas.
4. Every actual call is re-evaluated; exposure is not a durable authorization grant.

For remote MCP, `allowed_tools` is kept narrow. Imported descriptions and schemas are validated and namespaced. A newly discovered or changed remote tool defaults to unknown/high risk until a trusted policy mapping approves its descriptor. Remote MCP output URLs and embedded resources are treated as untrusted content.

Input schema validation is strict where the provider supports it and repeated server-side regardless. Unknown fields are rejected by default. Output is also validated when an output schema exists; invalid or oversized results become structured failures and are not blindly injected into model context.

## External Agent integration

Claude, Codex, Hermes, ACP, or future Agent backends may execute tools internally. They conform in one of two safe ways:

1. **Interactive permission bridge:** backend permission requests are normalized into Tool Requests, evaluated by Tool Policy Gateway, and answered with the resulting scoped decision.
2. **Pre-authorized sandbox profile:** the Agent runs in an isolated workspace with a fixed, least-privilege capability set approved before launch; actions outside that set are technically blocked, not merely discouraged by prompting.

A backend that exposes neither enforceable permission callbacks nor an adequate sandbox cannot receive write/code-execution authority in a production or multi-tenant profile. `AcpDriver(permission_policy=lambda _: True)` is therefore no longer a valid default. An explicitly named unsafe local-development profile may preserve it for disposable workspaces only.

Agent selection does not imply permission inheritance. Selecting Codex to work on a task does not grant every Codex tool; selecting Claude or Hermes follows the same gateway and sandbox policy.

## Cancellation, retries, and late results

- Cancelling a Tool Request before grant issuance prevents execution.
- Cancelling after execution starts is best-effort and does not imply rollback.
- Generation supersession stops user-visible reinjection but does not erase a side effect that already occurred.
- Automatic retries are allowed only for `IDEMPOTENT` or correctly `KEYED` bindings within the grant's attempt limit.
- Unknown/time-out outcomes for non-idempotent tools are reported as indeterminate and reconciled before any retry.
- A completed result is correlated and journaled even if the originating Generation is stale; policy decides whether and how it may be announced later.
- Bound Confirmation expiry or session disconnect invalidates unused approval, unless an explicit durable workflow policy says otherwise.

## Failure behavior

- Missing Tool Descriptor, policy, binding, scope, or credential fails closed with a structured error.
- Policy timeout denies or defers; it never falls back to direct execution.
- Confirmation-service failure denies protected actions and keeps the pending state explainable.
- Journal failure before execution prevents the side effect in durable mode.
- Output validation/redaction failure prevents raw result reinjection.
- Tool Executor crash leaves an indeterminate work record that is reconciled using the idempotency key and backend status.
- Client, provider, or Agent attempts to bypass Tool Policy Gateway are protocol violations recorded for audit.

## Acceptance checks

1. The same Tool Request gets the same policy semantics whether emitted by Native Realtime Engine, Pipeline Engine, MCP, or an external Agent.
2. A model cannot invoke a handler directly or obtain server credentials from Tool Descriptor/Conversation Projection.
3. Unknown dynamic MCP tools fail closed until trusted metadata and policy exist.
4. Changed arguments invalidate a previously issued confirmation.
5. Replayed approval, expired grant, wrong user/session, wrong tool version, or mismatched digest cannot execute.
6. Non-idempotent tools are never automatically retried after an unknown outcome.
7. Slow/background tools do not block audio receive, Barge-in, or the Fast Tool Loop deadline.
8. Tool intent and policy decision are journaled before side effects; results are journaled before reinjection.
9. ACP/Agent permission requests no longer auto-approve under the production default.
10. Tests can replace policy, executor, credential broker, provider adapter, and Tool Registry independently.

## Consequences

- Tool authorization is consistent across GPT-style Realtime, the Pipeline Engine, MCP, Skills, and multiple Agents.
- Tool metadata becomes richer and model-visible schema separates cleanly from server authority.
- Confirmation is replay-resistant and tied to the exact action rather than free-form dialogue.
- Low-risk reads remain fast because policy may issue a grant without user interaction.
- Side-effecting tools gain explicit audit, idempotency, sandbox, and recovery semantics.
- Existing `CanonicalTool(handler=...)`, direct `ToolCallingBrain` execution, and ACP auto-approval require migration behind Tool Policy Gateway.

## References

- OpenAI, [Realtime with tools](https://developers.openai.com/api/docs/guides/realtime-mcp)
- OpenAI, [MCP and Connectors](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
- OpenAI, [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [ADR-0017](0017-acp-driver-real-agent-backend-conformer.md)
- [ADR-0044](0044-bounded-fast-tool-loop-and-background-delegation.md)
- [ADR-0049](0049-separate-realtime-session-plane-from-application-control-plane.md)
- [ADR-0050](0050-server-owned-conversation-journal-as-authoritative-history.md)
