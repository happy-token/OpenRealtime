---
status: accepted
---

# Two coexisting hook mechanisms: Observer and Hook Point

Extensibility below the level of whole-Seam replacement is split into two mechanisms rather than one. **Observer**: async fan-out over the Event Ledger, read-only, cannot affect the pipeline — for logging, analytics, and other side effects. **Hook Point**: named, synchronous, in-line interception points inside a Seam's default implementation (e.g. `asr.before_turn_policy`, `tts.before_synthesis`) where user middleware may transform or veto the value in flight; default behavior is a no-op passthrough.

We considered exposing only the Observer (Event-Ledger-based) mechanism, since it already exists as Event Ledger infrastructure and is simpler to reason about. We rejected relying on it alone: the PRD asks for users to "customize" behavior at defined points, not just observe it, and a read-only bus cannot satisfy that without forcing a full Seam reimplementation for even small in-flight adjustments. Keeping the two mechanisms separate — rather than giving Observer the ability to mutate — is deliberate: it keeps "did a listener change this value" from ever being ambiguous, since only Hook Points can mutate and they are explicitly named per interception site. This shapes the public extension surface of every Seam going forward, so it is recorded here.
