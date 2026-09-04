---
status: accepted
---

# `voiceagent`→`server` rename, `examples`→`demos`, and `clients/web` promoted to a root Next.js app

Starting the demo required `set -a; source .env; set +a; uv run python examples/voice_web_server.py dev`
— too much ceremony for what the user wanted to be a one-line `pnpm dev`-style
workflow, the same way most of their other projects start. Asked whether to
just fix the startup command or go further, the user explicitly chose the
full restructure after being told it reverses three previously recorded
decisions:

- **ADR-0018**: `clients/web` is deliberately plain HTML/JS, no framework, no
  build step — "too heavy for just a demo."
- **ADR-0025**: `examples/` (server launchers) vs. `clients/` (reference
  client code) split.
- **ADR-0026**: explicitly declined a Node rewrite; the only npm-distributed
  artifact was meant to be a coding-agent skill package, not a client SDK.

None of those ADRs were wrong when written — the product just changed shape
underneath them. `clients/web` stopped being "just a demo" once it became the
one URL the user actually opens to talk to the agent day-to-day, and a
oklch-token dark-theme UI with reconnect/barge-in/config-drawer logic already
outgrew what a single `ui.js` closure could keep readable.

## Decision

### 1. `voiceagent/` → `server/`

Mechanical package rename across `pyproject.toml` (`name = "server"`) and
every `from voiceagent...`/`import voiceagent` in the codebase. Vendor-facing
*string literals* that happen to read `"voiceagent"` (Bella ASR `appkey`,
ACP `clientInfo.name`, Doubao `user.uid`) were deliberately left untouched —
those are external protocol identifiers, not the Python package name.
At the time, `skills/voiceagent/` kept its name because it was the coding-agent
skill's product identity (ADR-0026), unrelated to this import path. The later
OpenRealtime product rebrand moved that skill to `skills/openrealtime/`.

### 2. `examples/` → `demos/`, static-file serving dropped

`examples/voice_web_server.py` (now `demos/voice_web_server.py`) no longer
serves the frontend — the Next.js app (decision 3) owns that now, so
`_serve_static_files`/`WEB_ROOT`/`HTTP_PORT` and their `run_app(...)` wiring
were deleted. The script goes back to just the WS (8765) + control-plane
(8766) launcher.

One collision surfaced during this rename: `examples/server.py` (a raw-WS
demo launcher, pre-dating the package rename) initially became
`servers/server.py` after the directory rename — a name that shadows the
top-level `server/` package. Running `python servers/server.py` directly
puts `servers/` first on `sys.path`, so `import server...` inside that
process resolves to the sibling file instead of the package, crashing with
`ModuleNotFoundError: No module named 'server.agent_session'; 'server' is
not a package`. This only reproduces via direct script invocation
(`python path/to/script.py`), not via `pytest`'s import machinery, so it
wasn't caught until the `pnpm dev` live smoke test actually ran the script.
Renamed to `basic_ws_server.py`, with the collision explained in its own
docstring so it doesn't quietly reappear.

The directory name itself carried the same one-letter-apart confusion at a
coarser grain — `servers/` vs. `server/`, easy to misread or mistype in
prose and `cd`. Renamed the whole directory to `demos/`, which also matches
how this README already talks about these scripts ("console demo", "web
demo").

### 3. `clients/web/` promoted to a root-level Next.js app

Ported `index.html`/`ui.js`/`app.js`/`pcm-worklet.js` into a TypeScript
Next.js App Router project at the repo root — `src/app/`, `src/components/`,
`src/hooks/use-conversation-engine.ts` (a React port of `app.js`'s
`createConversationEngine()` closure: same WS reconnect/backoff, mic
capture, and playback-with-barge-in logic), `src/lib/` (frame types + pure
audio helpers, unit-tested), `src/styles/` (the same oklch design tokens,
ported verbatim). `public/pcm-worklet.js` is unchanged — an
`AudioWorkletProcessor` must be a plain static-served script.

These five directories initially landed flat at the repo root
(`app/`, `components/`, `hooks/`, `lib/`, `styles/`), which within a day made
the root feel noisier than before the restructure — going from ~7 tracked
top-level directories to 14. The instinct was to name a home for them after
what they are, matching `server/`/`clients/`/`demos/` (e.g. a `web/` folder).
That collides with a Next.js constraint: the App Router only auto-detects
`<root>/app` or `<root>/src/app` for file-system routing — there's no config
option for an arbitrary directory name. Given that constraint, consolidated
under `src/` instead: still one directory instead of five at the root, and
it's the name Next.js itself expects, so no `next.config.ts` change was
needed. Only `tsconfig.json`'s `@/*` path alias and `vitest.config.ts`'s
`include` globs needed updating — every frontend import already used the
`@/...` alias rather than relative paths, so no import statement had to
change.

The WebSocket URL logic and raw JSON frame protocol are unchanged — the
browser still talks directly to `demos/voice_web_server.py`'s WS server, no
Next.js API route or proxy in between (ADR-0018's "no CORS hardening,
local-only" stance still holds; WS connections aren't subject to fetch CORS
preflight anyway).

`clients/web/` is deleted now that the port is verified working (browser
check against a live backend, Playwright smoke test, `next build`).
`clients/` keeps `websocket/`, `udp/`, `esp32/` as the remaining
transport/device reference clients — ADR-0025's demo-vs-service distinction
still holds for those; only `web/` graduated from "demo" to "the product
frontend."

### 4. Root orchestration

Root `package.json` gets `dev`/`build`/`start`/`lint`/`test`/`test:e2e`
scripts; `scripts/dev_server.sh` loads `.env` and launches
`demos/voice_web_server.py`, invoked via a new `dev:server` script run
concurrently alongside `next dev`. This — not the rename or the rewrite — is
the actual fix for the original complaint: `pnpm install && pnpm dev` now
starts both the Next.js frontend (port 3000, the one URL the user opens) and
the Python WS/control-plane server (8765/8766, internal wiring the browser
talks to, never typed manually) with one command.

## Scope not implemented

- Full multi-breakpoint visual-regression coverage (per the web-testing
  checklist) is deferred — one Playwright smoke spec (page load, view
  toggle, mic-button connecting/disabled state) covers the golden path for
  now. A follow-up if this app keeps growing.
- No auth, CORS, or TLS hardening — same local-only stance as ADR-0018,
  unchanged by this move.
