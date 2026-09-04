# ESP32 reference client

A demo-grade ESP32 client for the OpenRealtime WebSocket wire protocol
(`server/transport/frames.py`), matching the same "Xiaozhi-style
hardware" framing the Device Fleet Seam already uses (see
[CONTEXT.md](../../CONTEXT.md) — Device Fleet).

**Status: reference/demo-grade, unbuilt and untested in this environment**
(no ESP-IDF toolchain available here) — the same caveat every `InMemory*`
default in this repo carries. Treat this as a starting point to adapt for
real hardware, not a shippable firmware.

## What it does

1. Connects to a OpenRealtime WebSocket server (`demos/basic_ws_server.py` or
   `demos/voice_web_server.py`, run via `server/cli/harness.py`'s
   `run_app()`).
2. Sends a `session_hello` frame and logs the server's `session_ack`.
3. Sends one scripted `user_text` frame ("hello from esp32") and logs the
   `assistant_text` reply.
4. Logs (without decoding) any `assistant_audio_chunk` frames it receives.

## What it deliberately stubs out

Real audio capture (I2S mic → `audio_chunk` frames, matching
`clients/web/pcm-worklet.js`'s browser-side equivalent) and playback
(`assistant_audio_chunk` → I2S DAC/amp) are hardware/board-specific and out
of scope for a reference client — see `handle_frame()` and
`send_demo_user_text()` in `main/main.c` for exactly where those seams would
plug in.

## Weak-network reconnect (deliberately not implemented)

`send_session_hello()` in `main/main.c` always sends a fresh
`{"type": "session_hello"}` with no `resume_session_id`, and there is no
reconnect-on-disconnect loop — a dropped Wi-Fi link ends the session for
good. This is a known gap for real device deployments, but it stays
undocumented-in-code on purpose: this client is reference/demo-grade (see
"Status" above), and adding real reconnect logic would blur that line.

If/when this gets built for real hardware, the target shape already exists
elsewhere in this repo and should be ported rather than reinvented:

- **Wire mechanism**: [ADR-0019](../../docs/adr/0019-endpoint-session-reconnect-resume.md)'s
  `SessionHelloFrame.resume_session_id` / `SessionAckFrame` — the server side
  of resume is already implemented and is transport-agnostic.
- **Client-side pattern to port**: `src/hooks/use-conversation-engine.ts`'s
  reconnect loop — on disconnect, retry with exponential backoff
  (`reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, ...)`),
  and on reconnect send `session_hello` with `resume_session_id` set to the
  previously-assigned session id instead of a fresh one.
- **ESP32-specific translation**: `esp_websocket_client`'s disconnect event
  (`WEBSOCKET_EVENT_DISCONNECTED`) is the natural trigger for the retry loop
  in place of a browser `onclose` handler; the session id would need to be
  held in a static/global rather than component state.

## Build (once you have an ESP-IDF toolchain)

```sh
cd clients/esp32
idf.py set-target esp32
idf.py menuconfig   # under "OpenRealtime ESP32 Client Configuration": set
                     # Wi-Fi SSID/password and the server's ws:// URI
idf.py build flash monitor
```

`main/idf_component.yml` pulls in the `espressif/esp_websocket_client`
managed component automatically on first build.

## Configuration

Set via `idf.py menuconfig` (persisted to `sdkconfig`, not committed):

| Option | Example |
|---|---|
| `VOICEAGENT_WIFI_SSID` | your Wi-Fi network name |
| `VOICEAGENT_WIFI_PASSWORD` | your Wi-Fi password |
| `VOICEAGENT_SERVER_URI` | `ws://192.168.1.100:8765` — same host:port `run_app()` binds to |
