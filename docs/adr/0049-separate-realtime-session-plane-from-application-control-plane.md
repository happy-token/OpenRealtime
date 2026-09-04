---
status: accepted
---

# Separate the Realtime Session Plane from the Application Control Plane

OpenRealtime permanently separates its latency-critical Realtime Session Plane from its trusted Application Control Plane. The Session Plane carries live audio and realtime events; the Control Plane owns identity, policy, tools, confirmation, budgets, and named-Agent delegation. They communicate only through canonical Voice Events and Conversation Actions correlated by Interaction Context.

The separation is logical before it is physical. The first production iteration may run both planes in one Python process over the current WebSocket transport. That is acceptable only if module dependencies respect the boundary. Future RTC/WebRTC support replaces or extends Session Plane adapters; it must not require moving business orchestration or rewriting Conversation Kernel.

This follows OpenAI Realtime's published Sideband pattern at the observable architecture level: a client connection and an application-server connection can attach to the same Realtime session, while tool use and business logic remain server-side. OpenRealtime generalizes that pattern to both Native Realtime Engine and Pipeline Engine without claiming OpenAI's private service topology.

## Plane responsibilities

| Responsibility | Realtime Session Plane | Application Control Plane |
|---|---:|---:|
| Capture/deliver live audio | Owns | Observes metadata only when needed |
| Client connection and reconnect | Owns through Endpoint Session | Binds identity and policy on attach |
| Provider realtime session I/O | Owns through Engine adapter | Controls through canonical commands or Sideband |
| Dialogue timing and Barge-in signals | Produces/acts on latency-critical signals | Supplies policy; audits outcomes |
| User/tenant authorization | Never decides | Owns |
| Tool schema exposure | Carries approved declarations | Selects, filters, versions, and authorizes |
| Fast tool execution | Never executes | Owns |
| Confirmation gates | Renders/prompts and transports answer | Owns decision and correlation |
| Background Agent delegation | Never launches Agents | Owns through BackendCatalog and Agent Session Protocol |
| Secrets and durable credentials | Ephemeral session material only | Owns |
| Audit, budgets, rate/cost limits | Emits measurements | Owns enforcement and durable records |

## Canonical boundary

No provider SDK object, WebSocket frame, WebRTC callback, or raw dictionary crosses from Session Plane into Control Plane. Boundary adapters normalize inbound stimuli into typed Voice Events. Control decisions and user-visible output return as typed Conversation Actions.

The minimum correlation envelope includes:

- `tenant_id`, `user_id`, and `device_id`;
- `voice_session_id`, `thread_id`, stable `turn_id`, and Generation;
- `response_id` plus per-stream sequence;
- `call_id`, `worker_id`, `confirmation_id`, or `handoff_id` when applicable;
- event/action identity, schema version, and monotonic timestamp.

The boundary is asynchronous and streaming. It must not turn `AudioDelta`, `TextDelta`, tool progress, or cancellation into a blocking request/response RPC. Control actions are allowed to interrupt queued media and therefore have priority over future audio delivery.

## Current WebSocket deployment

The immediate architecture remains server-terminated:

```text
Client
  │ audio + typed transport frames
  ▼
WebSocket Transport Adapter ── Endpoint Session
  │ normalized Voice Events / Conversation Actions
  ▼
Conversation Kernel
  ├── Conversation Engine (Pipeline first; Native conformer later)
  ├── Turn Policy / Output Scheduler
  └── Application Control Plane
        ├── Tool Registry + Fast Tool Loop
        ├── Confirmation Policy
        ├── Work Registry
        └── BackendCatalog + Agent Session Protocol
```

Both planes may share one event loop during the migration. The following dependency rules still apply:

1. Transport and speech adapters may depend on canonical event/action types, never tool implementations or Agent Drivers.
2. Tool and Agent modules may depend on Interaction Context, never client sockets, audio codecs, or provider session objects.
3. Conversation Kernel coordinates the two planes but contains neither implementation.
4. A slow tool, audit sink, or Agent must never block the transport receive loop or audio send loop.
5. Session Plane delivers only tools that Control Plane has approved for this tenant, user, Engine, and session policy.

This gives the project the GPT Voice-style control boundary now, without making RTC a prerequisite for streaming, tool orchestration, or multi-Agent work.

## Future Native Realtime and RTC deployment

RTC remains a later Session Plane adapter. Two deployment shapes are valid behind the same contracts:

### Server-terminated media

The client connects to OpenRealtime; OpenRealtime connects to the realtime provider. Application Control Plane is already adjacent to the provider adapter. No external Sideband Connection is required, but the logical separation remains.

### Client-direct media with server Sideband

The client establishes WebRTC media directly with a realtime provider using short-lived session material. OpenRealtime's Application Control Plane attaches to that same provider session over its supported Sideband mechanism. The server connection receives tool calls and policy-relevant events and returns tool output/session updates without relaying the media stream.

For client-direct media:

- the bootstrap endpoint authenticates the user and creates/binds `voice_session_id` before issuing ephemeral session material;
- long-lived provider API keys never reach the client;
- the provider session ID is mapped to Interaction Context server-side;
- the client cannot self-authorize tools by altering data-channel declarations;
- loss of Sideband control is explicit session degradation, not silent client authority;
- reconnect or transport replacement does not create a second logical Voice Session unless policy says so.

Choosing LiveKit, a provider-native WebRTC path, or another RTC stack is intentionally deferred. That choice must conform to Endpoint Session and Transport Adapter rather than change the canonical protocol.

## Tool-call flow

```text
Native/Pipeline Engine emits CallTool(call_id)
                 │
                 ▼
Conversation Kernel validates current Interaction Context
                 │
                 ▼
Control Plane checks schema, permission, confirmation, and budget
          ┌──────┴────────┐
          │               │
     fast/bounded     slow/unbounded
          │               │
   Fast Tool Loop     DelegateTask(worker_id)
          │               │
 ToolCompleted/Failed   progress/result events
          └──────┬────────┘
                 ▼
correlated Voice Event returns to Engine / next Response Stream
```

Session Plane is a carrier in this flow, never the authority. Even when a native provider emits the original function call, provider output is a request to Control Plane, not permission to execute.

## Cancellation and priority

Cancellation flows in both directions:

- Session Plane produces Barge-in, disconnect, provider failure, and playback state events.
- Conversation Kernel advances Generation and tells both planes to stop affected work.
- Session Plane clears or truncates unplayed output and cancels active provider generation.
- Control Plane cancels the Fast Tool Loop when safe; background Delegated Tasks continue unless their `worker_id` is explicitly cancelled or policy couples them to the turn.
- All late output remains lease-checked even after cooperative cancellation.

The cancellation path cannot wait behind ordinary tool requests, logging, transcript persistence, or queued audio. Implementations use separate bounded queues or an equivalent priority mechanism for control signals.

## Failure and degradation rules

- If Session Plane fails, Control Plane records the session transition and preserves only resumable state; it does not pretend audio was delivered.
- If Control Plane is unavailable, state-changing tools, sensitive reads, confirmations, and Agent delegation fail closed.
- A session may continue conversation-only during temporary Control Plane loss only when an explicit session policy allows it and no pending protected action exists.
- Tool failure becomes a correlated `ToolFailed` event. It must not be converted to empty output or an invented success.
- Sideband loss in client-direct mode is visible in Voice Session Phase/health and starts a bounded recovery deadline.
- Reconnection reuses canonical Voice Session identity; provider/session-specific IDs are rebound at the adapter boundary.

## Security rules

- Client input is untrusted even when it arrives over an authenticated media session.
- Provider tool-call arguments are untrusted and validated against Canonical Tool Schema.
- Application Control Plane is the only place allowed to resolve credentials, filesystem/workspace authority, tenant policy, or Agent launch configuration.
- Client and provider receive the minimum tool metadata required for model selection; secret implementation metadata stays server-side.
- Confirmation is bound to exact action digest, subject, expiry, and `confirmation_id`; a generic spoken "yes" cannot authorize unrelated work.
- Audit records include decision IDs and outcomes but exclude raw secrets and avoid raw audio by default.

## Explicit non-goals

- This ADR does not select an RTC vendor or require RTC in the first implementation.
- It does not require deploying two microservices.
- It does not make Event Ledger a message bus.
- It does not allow client-side tool execution merely because Realtime events arrive on a DataChannel.
- It does not duplicate Voice Session state between planes; Conversation Kernel remains the ordering authority.

## Acceptance checks

An implementation conforms only if:

1. current WebSocket transport can be replaced by a fake or future RTC adapter without changing tool, Agent, or confirmation modules;
2. ToolExecutor and Agent Drivers can be tested without a socket, codec, microphone, or provider SDK;
3. no long-lived provider/tool/Agent credentials appear in client payloads;
4. a blocked or slow tool does not stop audio receive, Barge-in processing, or cancellation;
5. forged client tool declarations cannot grant execution authority;
6. every tool and delegated result is correlated back to the original Voice Session and call/worker identity;
7. Sideband or Control Plane loss produces an explicit degraded/failed state and protected operations fail closed;
8. both Pipeline and Native Realtime Engine pass the same boundary contract tests.

## Consequences

- Low-latency voice work can proceed immediately over WebSocket while RTC stays on the roadmap.
- RTC and provider choice become replaceable Session Plane concerns.
- Tools, Claude/Codex/Hermes delegation, and policy remain reusable across transports and Engine conformers.
- The server retains authority even when future media flows directly between client and provider.
- Logical separation adds explicit event/action translation and correlation work, but avoids coupling security-critical orchestration to media callbacks.

## References

- OpenAI, [Webhooks and server-side controls](https://developers.openai.com/api/docs/guides/realtime-server-controls)
- OpenAI, [Realtime API with WebRTC](https://developers.openai.com/api/docs/guides/realtime-webrtc)
- OpenAI, [Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)
- OpenAI, [Realtime with tools](https://developers.openai.com/api/docs/guides/realtime-mcp)
- [ADR-0042](0042-thin-conversation-kernel-over-independent-capability-seams.md)
- [ADR-0046](0046-first-class-identity-and-correlation-context.md)
- [ADR-0047](0047-canonical-typed-voice-events-and-conversation-actions.md)
- [ADR-0048](0048-end-to-end-streaming-conversation-engine-and-output-contract.md)
