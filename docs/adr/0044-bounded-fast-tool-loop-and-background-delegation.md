---
status: accepted
---

# Replace the single-tool rule with a bounded Fast Tool Loop

A Conversation Engine may request multiple sequential Canonical Tool calls while resolving one turn, provided the loop is bounded by call count, total elapsed time, cost, permissions, and cancellation. Slow, unpredictable, or genuinely multi-step work is delegated through the Agent Session Protocol instead of extending the inline loop. This supersedes ADR-0009's exactly-one-tool rule: that rule made latency predictable but was too restrictive for GPT Voice-style function-calling conversations and forced ordinary dependent lookups into whole-Agent delegation.

## Consequences

- The action loop terminates on speak, background delegation, confirmation, session end, or an exhausted budget.
- Every call carries a `call_id`; results and errors are reinjected as correlated conversation items.
- Exhausting a limit produces a structured, explainable result rather than silently continuing or crashing.
- Implementations must support per-call timeout and cancellation, plus per-turn aggregate budgets.
