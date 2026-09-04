---
status: superseded by ADR-0068
---

# Endpoint Session: reconnect/resume across a dropped transport

CONTEXT.md's own **Seam** entry has named "Endpoint Session" as one of the
project's Backbone Seams from the start, and the **Transport Adapter**
entry already described itself as "a pluggable implementation of the
Endpoint Session's wire protocol" — but until now no `EndpointSession`
module or dedicated glossary entry existed. The gap was real and,
notably, undocumented anywhere in this repo's otherwise-candid
`docs/ISSUES.md`/`ROADMAP.md`:

- `ConversationKernel.run()` is `async for frame in self._transport.receive():
  ...` — when a `TransportAdapter`'s connection drops, the generator ends
  and `run()` returns for good.
- `websocket.serve()` built one `WebSocketTransportAdapter` and called the
  connection handler once per raw connection, with zero session identity.
- `examples/server.py`'s `_handle_connection` constructed a brand-new
  `ConversationKernel` per connection with no continuity.

A voice agent used over a weak network (the explicit motivating scenario
for this ADR) needs a dropped physical connection to be resumable without
losing in-flight conversational state — the whole point of a dedicated
Endpoint Session Seam.

(Cross-checking `docs/references/voiceloop-modular-runtime-review.md`
confirmed "VoiceRuntime" — the *other* unbuilt name previously listed
alongside Endpoint Session in CONTEXT.md's Seam entry — is vocabulary
inherited wholesale from the user's own abandoned `voiceloop-modular-runtime`
PRD, where it meant "demote pipecat's Frame/Processor/Pipeline model to a
replaceable adapter." Irrelevant here since OpenRealtime never had pipecat to
demote; removed from CONTEXT.md as a documentation correction, not a
design change.)

## `EndpointSession` conforms to `TransportAdapter`

`EndpointSession` (`endpoint_session/protocol.py`) exposes the same
`receive`/`send`/`close` shape as `TransportAdapter`, plus `attach`/
`detach` for moving across physical connections. Because Python's
`Protocol` typing is structural, `ConversationKernel` and both
`ResponseScheduler` conformers need **zero code changes** — they are
handed an `EndpointSession` in place of a raw transport and cannot tell
the difference.

## `InMemoryEndpointSession`: never ends `receive()` on its own

`InMemoryEndpointSession` (`endpoint_session/in_memory_session.py`) is the
framework's shipped default — single-process only, same "not
production-grade" caveat as `InMemoryDriver`/`InMemoryDeviceFleet`.

- `receive()` delegates to whatever physical transport is currently
  attached. When that transport's own `receive()` ends (a drop), the
  session does **not** end its generator — it calls `detach()` and
  suspends on an internal reattach signal, resuming iteration once
  `attach()` is next called. It only ends for real once `close()` is
  called. This is what lets `ConversationKernel.run()`'s background task
  survive across a reconnect: it is still inside the same `async for
  frame in session.receive():` the whole time, just paused.
- `send()` forwards to the attached transport if present, else appends to
  a bounded outbound buffer (plain `collections.deque`, capacity via
  constructor arg, default 256). Overflow drops the oldest buffered frame
  and logs a warning — no silent, uncapped growth, and no silent data
  loss either.
- `attach(transport, frame_iterator=None)` takes over a new physical
  transport and flushes the buffer through it, in order, before resuming
  inbound delivery. The registry passes an already-partially-consumed
  `frame_iterator` (see below) rather than letting the session call
  `transport.receive()` a second time on the same connection.

## `EndpointSessionRegistry`: hello/resume handshake and grace period

`EndpointSessionRegistry` (`endpoint_session/registry.py`) owns
per-connection bookkeeping so `transport/websocket.py` and
`transport/udp.py` stay completely untouched — the new Seam sits one layer
above any `TransportAdapter` conformer, transport-agnostic.

`handle_connection(transport, build_kernel)` reads the first inbound frame
and expects a `SessionHelloFrame`:

- `resume_session_id` matches a live entry → cancel that entry's pending
  grace-period timer, `attach()` the new transport, send
  `SessionAckFrame(resumed=True)`.
- otherwise (no match, unknown/expired id, or the first frame wasn't a
  hello at all — treated as a fresh session rather than an error, with the
  already-read frame re-delivered so it isn't silently dropped) → mint a
  new `session_id` (`uuid4`), construct an `InMemoryEndpointSession`,
  register it, send `SessionAckFrame(resumed=False)`, and run
  `build_kernel(session)` as a background task.

Either way, `handle_connection` then waits until this particular attach
cycle ends (the physical transport disconnects again, or the session is
closed for good) before returning — letting the connection handler's
coroutine end cleanly. On a detach (not a close), it starts a grace-period
timer (default 60s); if no matching resume arrives before it fires, the
session is `close()`d — ending its `receive()` generator, and therefore
its `ConversationKernel.run()` task, for good — and evicted from the
registry.

Reading the hello frame consumes it from the transport's own `receive()`
generator; the remaining, still-open iterator (not a second call to
`transport.receive()`) is what gets threaded into the session, since a
`TransportAdapter`'s `receive()` is a single-consumer generator, not a
repeatable call.

## Wire protocol additions

- `SessionHelloFrame`: `type: "session_hello"`, `resume_session_id: str |
  None = None`. First frame a client sends on any new physical connection.
  Added to `InboundFrame`.
- `SessionAckFrame`: `type: "session_ack"`, `session_id: str`, `resumed:
  bool`. Server's reply, confirming the session id to use going forward.
  Added to `OutboundFrame`.

## Scope not implemented

- Multi-process/distributed session resume (e.g. a Redis-backed registry).
  `EndpointSessionRegistry`/`InMemoryEndpointSession` are single-process
  only; a session cannot be resumed against a different server process.
- RTC/MQTT/LiveKit transports — still contract-only per ISSUE-0001,
  unaffected by this change since the new Seam is transport-agnostic.
- Client-side reconnect/backoff logic. No browser/device client ships in
  this repo; `SessionHelloFrame.resume_session_id` is the wire contract a
  real client implements its own backoff against.
- Distinguishing an explicit client goodbye from a network drop — every
  disconnect gets the same grace period today.
