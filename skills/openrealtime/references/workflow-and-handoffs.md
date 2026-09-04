# Workflow and handoffs

How a turn gets delegated to an external Agent instead of answered by the
built-in Chat Brain, and the shared contract every backend delegates through.

## Router / DelegationPolicy

`server/brain/router.py`'s `Router.decide()` is the Kernel's entry point
for a committed turn. With no `DelegationPolicy`/`Driver` registered it
always returns `ChatReply` — identical to pre-delegation behavior, so
registering nothing is always safe.

```python
class Router:
    async def decide(self, content: TurnContent) -> RouterDecision:
        target = await self._delegation_policy.choose_agent(content)
        if target is None:
            return ChatReply(response=await self.route(content))
        driver = self._drivers.get(target)
        if driver is None:
            raise ValueError(f"DelegationPolicy chose unregistered agent {target!r}")
        session = driver.create_session()
        await session.send_turn(content)
        return DelegateToAgent(session=session, ack_text=self._delegation_policy.ack_text(content))
```

`DelegationPolicy` (`server/brain/delegation_policy.py`) is the plugin
interface: `choose_agent(content) -> str | None` (the target agent's name,
or `None` to stay on Chat Brain) and `ack_text(content) -> str`. Default is
`NeverDelegatePolicy`. `KeywordDelegationPolicy`
(`brain/plugins/keyword_delegation_policy.py`) is a demo-grade trigger-phrase
reference, not a production intent classifier — write your own for real use.

Router holds a `dict[str, Driver]` (constructor kwarg `drivers`), typically
built via `server/agent_session/backend_catalog.py`'s `build_drivers` from a
declarative name→launch-config `BackendCatalog` — see ADR-0031.

## Agent Session Protocol

`server/agent_session/protocol.py` defines the contract every backend
speaks, regardless of vendor:

```python
class AgentSession(Protocol):
    async def send_turn(self, content: TurnContent) -> None: ...
    async def latest_update(self) -> SessionUpdate | None: ...
    async def cancel(self) -> None: ...
    async def result(self) -> DelegationOutcome: ...

class Driver(Protocol):
    def create_session(self) -> AgentSession: ...
```

A **Driver** supplies only launch/auth/workspace details for one backend —
never session, streaming, or cancellation logic; that lives once, in the
shared protocol implementation (`agent_session/in_memory_session.py`'s
`InMemoryAgentSession`/`InMemoryDriver`). Writing a new backend means
implementing `Driver.create_session()` to return something satisfying
`AgentSession` — see `agent_session/plugins/acp_driver.py`'s `AcpDriver` for
a real conformer.

`InMemoryDriver`/`InMemoryAgentSession` are the reference implementation for
tests and local iteration: deterministic, test/demo-controllable
(`sent_content`, `cancelled` properties; `resolve()`/`fail()`/`push_update()`
to script a fake backend's behavior), not a real integration.

## Delegation Ack and status pull

When `Router.decide()` returns `DelegateToAgent`, the Response Scheduler
speaks `ack_text` **once**, then stays silent until:

- the delegation completes (`AgentSession.result()` resolves), or
- the user asks about progress — `StatusInquiryClassifier`
  (`brain/status_inquiry.py`) tells a progress check ("怎么样了？") apart
  from a genuinely new topic. A progress check reads from
  `latest_update()` under the existing Generation Lease (no re-dispatch); a
  new topic supersedes and calls `session.cancel()`.

There is no tiered/periodic filler — this was a deliberate rejection, not an
oversight (ADR-0006).

## Generation Lease and supersession

Every user turn increments the **Generation** counter. A `DelegationOutcome`
(success or error) is only spoken if its originating generation still
matches the current one when it resolves — a superseded delegation's result
is discarded/logged, never spoken mid-way through a newer turn. This check
happens in the Response Scheduler, not in `Router` or the `Driver` — a
`Driver` author never needs to reason about supersession directly.

## Writing a new Driver

1. Implement `AgentSession` for your backend: `send_turn` starts/streams the
   turn, `latest_update` returns the most recent cached progress (for
   status-pull), `cancel` tears down the in-flight call, `result` awaits and
   returns the final `DelegationOutcome`.
2. Implement `Driver.create_session()` returning a fresh session per turn.
3. Compare against `AcpDriver` (`agent_session/plugins/acp_driver.py`) — a
   real backend integration, not just the in-memory test double — for how
   launch/auth/workspace concerns are kept out of the shared protocol logic.
4. Register your `Driver` (and a `DelegationPolicy` deciding when to use it)
   on the `Router` your kernel-building code constructs.
