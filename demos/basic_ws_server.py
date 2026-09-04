"""Minimal v2 Voice Session WebSocket launcher.

This example deliberately shares the production Cascaded composition root
with ``voice_web_server.py`` so it cannot drift back to the removed Kernel
runtime. With no provider credentials it uses the repository's deterministic
ASR/TTS/LLM conformers.

Run:
    uv run python demos/basic_ws_server.py [dev|start]
"""

from __future__ import annotations

from demos.voice_web_server import (
    WS_HOST,
    _build_endpoint_security,
    _build_session_runtime,
    _start_application_runtime,
    _stop_application_runtime,
)
from server.cli.harness import run_app

_session_registry, _websocket_serve = _build_endpoint_security()


if __name__ == "__main__":
    run_app(
        _build_session_runtime,
        serve=_websocket_serve,
        session_registry=_session_registry,
        host=WS_HOST,
        on_startup=_start_application_runtime,
        on_shutdown=_stop_application_runtime,
    )
