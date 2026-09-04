---
status: accepted
---

# `examples/` vs. `clients/`: separating service demos from device-client code

The project's positioning is a service that exposes a voice-interaction
interface, plus reference usage code for the different device types that
consume it. `examples/` previously mixed both concerns flatly: server entry
points (`server.py`, `udp_server.py`, `voice_web_server.py`,
`acp_opencode_live_demo.py`) alongside device-facing client code
(`client.py`, `udp_client.py`, `web/`). Nothing in the directory structure
distinguished "runs the service" from "talks to the service," so the
project's own layout didn't reflect its stated positioning.

## Decision

Split the client-facing files into a new top-level `clients/` directory,
organized by device/transport type:

```
clients/
├── websocket/client.py   # was examples/client.py
├── udp/client.py         # was examples/udp_client.py
└── web/                  # was examples/web/{index.html,app.js,ui.js,pcm-worklet.js}
```

`examples/` keeps only the server-side service demos. `examples/voice_web_server.py`'s
`WEB_ROOT` now points at `clients/web/` instead of a same-directory `web/`.

This is a **directory reorganization and framing change only** — it does not
turn `clients/` into a distributable package, add a build step, or change
any behavior. `client.py`/`udp/client.py` remain the same minimal,
no-reconnect demo scripts they were; `clients/web/` remains the same plain
HTML/JS/AudioWorklet page, no framework, no npm.

## Why `clients/`, not `devices/`

`voiceagent/device_fleet/` is an existing, unrelated Seam (ADR-0003):
device activation, OTA firmware checks, and inventory for physical hardware
ecosystems (小智-style), explicitly scoped away from both the wire protocol
(Transport Adapter) and device-side tool announcement (Tool Normalization).
Naming the new directory `devices/` would collide with that established
meaning. `clients/` is unambiguous: it holds code that acts as a client of
the voice-interaction service, regardless of what "device" it happens to
run on.

## Explicitly not a reversal of ADR-0018 or ADR-0019

- ADR-0018 declined to ship a "web-sdk npm package" for the browser demo as
  too heavy for "just a demo." This split doesn't introduce packaging,
  bundling, or a published artifact — `clients/web/` is the same static
  files, just relocated.
- ADR-0019 states plainly that "no browser/device client ships in this
  repo" as a production artifact — only the wire contract
  (`SessionHelloFrame`/`SessionAckFrame`, resume semantics) does. The files
  under `clients/` remain reference/demo-grade implementations of that
  contract, not a maintained SDK with a compatibility guarantee.

## Other moves bundled into this pass

- `examples/web/architecture.html` (a standalone Mermaid diagram, never
  served by any demo server) moved to `docs/web-demo-architecture.html` —
  it's documentation, not client code.
- `examples/web/prototype-redesign.html` was deleted. Its own header
  self-described it as a throwaway UI comparison to be deleted once a
  variant was folded into the real demo; `clients/web/ui.js`'s docstring
  already documents itself as that fold-in (`renderVariantD`), so the
  prototype had no remaining purpose.
