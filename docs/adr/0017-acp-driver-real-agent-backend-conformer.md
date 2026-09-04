---
status: accepted
---

# AcpDriver: a real `Driver` conformer speaking Agent Client Protocol

ISSUE-0003 tracked having no real `Driver` for a named external Agent
backend — `InMemoryDriver` (ADR-0001) is deliberately network-free, so
every delegation in every demo/test resolves itself in-process. This ADR
closes that gap with `AcpDriver` (`agent_session/acp_driver.py`), a
conformer that spawns and talks to any agent CLI speaking Agent Client
Protocol (ACP) — the JSON-RPC-over-stdio protocol Zed's
`@agentclientprotocol/sdk` defines and that `opencode acp` (confirmed live
against `opencode` 1.18.5), and reportedly Claude Code/Gemini CLI/others,
implement.

This was prompted directly by running the user's own `qwen-audio-agent`
instance live: it delegates to OpenCode over ACP too, and its frontend
narrated "task complete" (with a fabricated feature list) roughly 8 seconds
into a delegation whose backend task store showed `running` five-plus
minutes later, with no output file ever produced. `AcpDriver` is built so
that failure mode is structurally impossible on OpenRealtime's side:
`AcpAgentSession.result()` only ever resolves once the ACP `session/prompt`
response has actually arrived, and `ConversationKernel._await_delegation`
(ADR-0006) never speaks a result before `result()` resolves. There is no
narration path that can run ahead of the backend.

## Wire protocol and transport

JSON-RPC 2.0, one JSON object per line on the child process's stdin/stdout
(NDJSON — not Content-Length-framed like LSP). `SubprocessAcpTransport`
wraps `asyncio.create_subprocess_exec`; `_AcpJsonRpcClient` owns a
background read loop that correlates responses to requests by numeric id,
dispatches `method`+no-`id` messages as notifications (`session/update`),
and answers `method`+`id` messages (`session/request_permission` is the
only one implemented) by writing a JSON-RPC response back on the same
transport.

Only stdlib (`asyncio`, `json`) is used — no new dependency, following the
pattern already established for `OpenAiCompatibleLlmClient` and
`ByteWebSearch`: prefer the stdlib-only shape already proven in this
codebase over adding a JSON-RPC/subprocess library for what is, at its
core, "write a line, read a line."

## One subprocess per `Driver`, not per session or per turn

`AcpDriver` lazily spawns a single ACP subprocess on first use (guarded by
an `asyncio.Lock`) and reuses it across every `AcpAgentSession` it creates
and every turn sent to each of those sessions — mirroring how OpenCode's
own ACP mode and qwen-audio-agent's Gateway both keep one long-lived
backend process rather than respawning per request. `create_session()`
stays synchronous and I/O-free (required by the `Driver` Protocol); the
subprocess only starts inside the first `send_turn()`'s background task.

## Auto-approve `session/request_permission` by default

> **Amendment — ADR-0051:** this default is superseded for the target
> architecture. ACP permission requests must be normalized as Tool Requests and
> evaluated by Tool Policy Gateway. Missing policy fails closed. Unattended
> auto-approval may exist only as an explicitly named unsafe local-development
> profile, never as the framework or production default.

ACP backends emit `session/request_permission` (agent→client, itself a
JSON-RPC request) before file-writing or shell tool calls, and block
indefinitely until it is answered. The live qwen-audio-agent test almost
certainly hung on exactly this — OpenCode auto-approves under
qwen-audio-agent's own default configuration, and any backend correctly
awaiting a permission decision with nothing answering it will simply never
finish the turn.

`AcpDriver`'s default `permission_policy` is `lambda _: True` — approve
everything, matching qwen-audio-agent's own default. This is a genuine
security tradeoff, not a neutral default: it means any ACP backend spawned
through `AcpDriver` is trusted with unattended file/shell access in
whatever `cwd` it's given, with no human in the loop. The constructor
accepts a different `permission_policy: Callable[[dict], bool]` for
callers who want to inspect `params["toolCall"]`/`params["options"]` and
decide per-request instead — auto-approve is the default because it's
required for any file-writing task to ever complete, not because it's
safe in every deployment. Callers running `AcpDriver` against untrusted
prompts or in a shared/multi-tenant `cwd` should supply a stricter policy.

## Scope not implemented

- No `fs/*`/`terminal/*` request handling — only `session/request_permission`
  is answered. A backend that needs client-side file or terminal access
  (rather than doing it itself inside its own sandboxed tool calls) will
  hang the same way the live test did. Documented, not silently patched
  around.
- No session persistence across OpenRealtime process restarts.
- No backend-specific profiles. `command` is a plain argv sequence
  (default `("opencode", "acp")`); pointing it at Hermes/CodeBuddy/Codex's
  own ACP entry point is the caller's responsibility, not something
  `AcpDriver` special-cases.
