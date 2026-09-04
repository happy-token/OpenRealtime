---
status: accepted
---

# ChatBrain datetime grounding, for the demo that's actually deployed

`demos/voice_web_server.py` — the server `pnpm dev` actually launches (via
`scripts/dev_server.sh`) — wires `Router(ChatBrain(_build_llm_client()))`.
Plain `ChatBrain`, never `ToolCallingBrain`. `ChatBrain.respond()` sent a
static system prompt with zero date/time information, so the real Bella LLM
had no way to answer "今天几号"/"现在几点" except by guessing from stale
training data — exactly the reported symptom.

`ClockToolSource` (ADR-0014) and, since ADR-0029,
`OpenAiCompatibleToolCallingLlmClient` give `ToolCallingBrain` a real path to
a real `get_current_datetime` tool call — but that pairing is wired into
`demos/basic_ws_server.py`, a separate demo entrypoint, not into
`voice_web_server.py`. This ADR does not move `voice_web_server.py` onto
`ToolCallingBrain`. Two reasons:

1. `ToolCallingBrain` supports at most one tool call per turn (ADR-0009).
   Whether the model reaches for `get_current_datetime` at all is a choice
   the model makes per turn — a date/time question phrased without an
   obvious trigger word, or a turn that also wants some other tool, can
   silently skip it. Always-grounded, every turn, has no such gap.
2. It would still leave the same rewiring work on `voice_web_server.py`
   that's actually the direct cause of the bug — the LLM client swap,
   `ToolRegistry` construction, and `ToolCallingBrain` wiring — for a
   question ("what time is it") that resolving locally, deterministically,
   with zero network round-trip cost is strictly simpler and strictly more
   reliable than routing through a model decision and a second `complete()`
   call.

Instead, `ChatBrain` grounds every turn directly, porting the pattern the
sibling reference project uses for the same
problem (`server/fillers/combined_client.py`): compute the current date/time
authoritatively, server-side, and inject it into the LLM's context as a
non-negotiable fact rather than something to compute or fetch. Unlike
realtime, this doesn't need a triage/action-selector protocol (`respond`/
`clock`/`lookup`) — ADR-0014 already rejected porting that, for reasons that
still hold — it's just an unconditional text block appended to the system
prompt on every `respond()` call:

```
当前时间：{iso}（{tz_name}，{weekday}）。回答日期/时间相关问题以此为准，不要凭训练数据猜测当前日期或年份。
```

`ChatBrain` takes the same `tz_name`/`now` constructor shape as
`ClockToolSource`, and both now share one `localize()` helper
(`tools/clock_source.py`) for resolving the effective IANA timezone
(explicit arg → `VOICEAGENT_CLOCK_TIMEZONE` → `Asia/Shanghai`), so the two
paths can never disagree about what "now" resolves to. This is always on —
no new env var or opt-in flag — there's no case where a live voice
assistant should answer date/time questions without knowing the real date.

`demos/voice_web_server.py` needed no wiring change: `ChatBrain`'s new
constructor parameters default identically to `ClockToolSource`'s, so the
existing `ChatBrain(_build_llm_client())` call picks up correct grounding
automatically.

This also surfaced a stale claim in `brain/llm_clients.py`'s docstring
("no tool-calling equivalent shipped yet") — no longer true since ADR-0029
added `OpenAiCompatibleToolCallingLlmClient`; corrected in passing.
