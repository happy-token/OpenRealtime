---
status: accepted
---

# Split Voice Runtime tools into inline and deferred response paths

## Context

An async Python handler alone does not make a tool interaction responsive. The
old path kept microphone intake cancellable, but the assistant stayed silent
through `LLM plan → tool → second LLM`. That is appropriate for a local clock
read and poor for network search. Sending every slow operation to Agent Runtime
would also be too heavy for bounded, read-only daily tasks such as weather.

The local GPT Voice reference separates the live media loop from slow work and
uses an acknowledgement before delegated results. We adopt that interaction
shape without claiming GPT Voice private implementation details.

## Decision

Canonical `LatencyClass` drives three policies:

| Class | Owner | User-visible flow |
|---|---|---|
| `FAST` | Voice Runtime | plan → execute → second LLM → one final reply |
| `VARIABLE` | Voice Runtime | plan → start bounded cancellable execution; emit one spoken acknowledgement only when the configured latency gate expires; result → second LLM → final reply |
| `BACKGROUND` | Agent Runtime | return a background/delegation decision; never execute inside the bounded Voice Tool Loop |

`get_current_datetime` is `FAST`. `search_web` is `VARIABLE`. Search remains a
low-risk read protected by Tool Policy Gateway, Execution Grant, timeout,
Generation cancellation, Journal records, and correlated `call_id` feedback.

The Conversation Engine emits latency on `CallToolAction`. For `VARIABLE`, its
Brain adapter starts the tool path immediately and races it against the
configured acknowledgement delay. A result available inside that window skips
the acknowledgement; a slower path emits exactly one runtime-owned,
intent-specific acknowledgement before continuing to wait. The
Application Coordinator starts tool execution as a child task and continues
draining text/audio actions, so TTS can speak while the tool is running. The
same response waits for correlated feedback and then makes exactly one second
LLM call. Barge-in or Generation supersession cancels the child task and drops
stale output.

The stateful Realtime implementation preserves the same policy through
`ToolRequested` and `RealtimeToolController`. The controller keeps event
forwarding independent from execution, reuses one budgeted handler per logical
response, and injects the correlated result Journal-first. A `FastToolLoop`
result that is already durable is projected directly instead of being appended
again. Native providers receive tool declarations and latency/version metadata
from the same `ToolRegistry`, then continue the original logical response only
after both the provider tool turn and the durable tool result are complete.

## Consequences

- Slow network search no longer creates a silent gap before the user hears
  progress.
- Audio frame intake remains independent from tool execution.
- Voice Runtime does not become a general Agent Runtime: only bounded tools run
  here, and `BACKGROUND` work still requires durable delegation infrastructure.
- The current model supports up to three sequential calls per realtime turn,
  matching ADR-0044's bounded Fast Tool Loop. Planning requests set
  `parallel_tool_calls=false`; providers that return parallel calls are rejected
  instead of silently dropping work. This also lets a provider recover when a
  first grounding call must be followed by `search_web`, without exposing its
  private tool protocol as speech.
- The acknowledgement catalogue is runtime-owned and pre-authored, so it adds
  no planning LLM call and cannot invent a completion result before the tool
  finishes. Per-intent rotation avoids repeating the same sentence in
  consecutive lookups.
- Fast successful and fast failing tools do not emit a redundant
  acknowledgement. `VOICEAGENT_SLOW_TOOL_ACK_DELAY_MS` configures the gate and
  defaults to 500ms.
