"""Run harness: `run_app(...)` replaces a demo/deployer script's own
`logging.basicConfig()` + `asyncio.run(main())` tail with one call, modeled
on livekit-agents' `cli.run_app` — there is no separate installed CLI
binary; the *script* calls `run_app(...)`, which reads its own mode off
`sys.argv`.

Modes (first CLI arg, default "start"):
    console  No network transport at all — stdin lines become UserTextFrame
             turns, printed responses go to stdout. No control plane. Fast
             local iteration without a socket.
    dev      Runs the real `serve()` loop plus the control plane (if a
             session_registry was given), DEBUG logging.
    start    Same as dev, INFO logging, no extra demo scaffolding.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from server.cli.lifecycle import LifecycleHook, invoke_lifecycle_hook
from server.control_plane import http as control_plane_http
from server.control_plane.http import (
    AvatarAssetHandler,
    SessionConversationPageReader,
    SessionInputEvidenceReader,
    SessionRecordingAudioReader,
    SessionRecordingPageReader,
)
from server.endpoint_session.registry import EndpointSessionRegistry
from server.observability.log_context import VoiceSessionLogFilter
from server.observability.telemetry import DebugLogQuery, DiagnosticsQuery
from server.transport.frames import InboundFrame, OutboundFrame, UserTextFrame

logger = logging.getLogger(__name__)

_MODES = ("console", "dev", "start")
_DEFAULT_MODE = "start"
_DEFAULT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "[session=%(voice_session_id)s gen=%(generation)s] %(message)s"
)
_DEFAULT_CONTROL_PLANE_PORT = 8766
_DEFAULT_LOG_DIR = ".openrealtime/logs"
_LOG_FILE_MAX_BYTES = 20 * 1024 * 1024
_LOG_FILE_BACKUP_COUNT = 5


def _resolve_log_file_path() -> Path | None:
    """`OPENREALTIME_LOG_FILE=""` opts out of file logging entirely;
    otherwise defaults under `.openrealtime/logs/` alongside this
    project's other runtime-data directories (tool-catalog, memory, etc.)."""
    override = os.environ.get("OPENREALTIME_LOG_FILE")
    if override == "":
        return None
    if override:
        return Path(override)
    return Path(_DEFAULT_LOG_DIR) / "voice-session.log"


class _SessionRuntime(Protocol):
    async def run(self) -> None: ...


BuildSessionRuntime = Callable[[Any], _SessionRuntime]
ServeFn = Callable[..., Awaitable[None]]
DiagnosticsQueryFactory = Callable[[object], DiagnosticsQuery | None]
DebugLogQueryFactory = Callable[[object], DebugLogQuery | None]
VoicePreviewer = Callable[[str, str, int, str], Awaitable[tuple[bytes, str]]]
SessionConversationReader = Callable[[str], Awaitable[list[dict]]]
SessionHistoryDeleter = Callable[[list[str]], Awaitable[dict[str, int]]]


class _ConsoleTransport:
    """Fake transport for `console` mode: stdin lines in, printed frames
    out. Structurally a TransportAdapter (see transport/base.py) but never
    touches the network."""

    async def receive(self) -> AsyncIterator[InboundFrame]:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return
            text = line.rstrip("\n")
            if text:
                yield UserTextFrame(text=text)

    async def send(self, frame: OutboundFrame) -> None:
        text = getattr(frame, "text", None)
        print(f"assistant> {text}" if text is not None else f"assistant> [{frame.type} frame]")

    async def close(self) -> None:
        pass


def _parse_mode(argv: list[str]) -> str:
    if not argv:
        return _DEFAULT_MODE
    mode = argv[0]
    if mode not in _MODES:
        raise SystemExit(f"unknown mode {mode!r} — expected one of {_MODES}")
    return mode


async def _dispatch(
    build_runtime: BuildSessionRuntime,
    session_registry: EndpointSessionRegistry | None,
    transport: Any,
) -> None:
    if session_registry is not None:
        await session_registry.handle_connection(transport, build_runtime=build_runtime)
        return
    runtime = build_runtime(transport)
    await runtime.run()


async def _run(
    mode: str,
    build_runtime: BuildSessionRuntime,
    *,
    serve: ServeFn,
    session_registry: EndpointSessionRegistry | None,
    host: str,
    port: int,
    control_plane_port: int | None,
    on_startup: LifecycleHook | None,
    on_shutdown: LifecycleHook | None,
    diagnostics_query_factory: DiagnosticsQueryFactory | None = None,
    debug_log_query_factory: DebugLogQueryFactory | None = None,
    diagnostics_health_reader: Callable[[], dict[str, Any]] | None = None,
    voice_previewer: VoicePreviewer | None = None,
    session_conversation_reader: SessionConversationReader | None = None,
    session_input_evidence_reader: SessionInputEvidenceReader | None = None,
    session_conversation_page_reader: SessionConversationPageReader | None = None,
    session_recording_page_reader: SessionRecordingPageReader | None = None,
    session_recording_audio_reader: SessionRecordingAudioReader | None = None,
    session_history_deleter: SessionHistoryDeleter | None = None,
    avatar_asset_handler: AvatarAssetHandler | None = None,
) -> None:
    startup_state = await invoke_lifecycle_hook(on_startup)
    control_plane_server: control_plane_http.ControlPlaneServer | None = None
    try:
        if mode == "console":
            logger.info("console mode — type a message and press enter; Ctrl-D to quit")
            await _dispatch(build_runtime, session_registry, _ConsoleTransport())
            return
        if control_plane_port is not None and session_registry is not None:
            diagnostics = (
                diagnostics_query_factory(startup_state)
                if diagnostics_query_factory is not None
                else None
            )
            debug_log_query = (
                debug_log_query_factory(startup_state)
                if debug_log_query_factory is not None
                else None
            )
            control_plane_server = control_plane_http.start(
                session_registry,
                diagnostics=diagnostics,
                voice_previewer=voice_previewer,
                session_conversation_reader=session_conversation_reader,
                session_input_evidence_reader=session_input_evidence_reader,
                session_conversation_page_reader=session_conversation_page_reader,
                session_recording_page_reader=session_recording_page_reader,
                session_recording_audio_reader=session_recording_audio_reader,
                session_history_deleter=session_history_deleter,
                avatar_asset_handler=avatar_asset_handler,
                debug_log_query=debug_log_query,
                diagnostics_health_reader=diagnostics_health_reader,
                port=control_plane_port,
            )

        async def _handle_connection(transport: Any) -> None:
            await _dispatch(build_runtime, session_registry, transport)

        logger.info("listening on %s:%d", host, port)
        await serve(_handle_connection, host=host, port=port)
    finally:
        try:
            if control_plane_server is not None:
                control_plane_server.stop_accepting_avatar_requests()
        finally:
            try:
                if session_registry is not None:
                    degraded_sessions = await session_registry.drain(deadline_s=15.0)
                    if degraded_sessions:
                        logger.error(
                            "Voice Runtime drain exceeded deadline: sessions=%s",
                            degraded_sessions,
                        )
            finally:
                try:
                    if control_plane_server is not None:
                        await _shutdown_control_plane(control_plane_server)
                finally:
                    if on_shutdown is not None:
                        await invoke_lifecycle_hook(on_shutdown, startup_state)


async def _shutdown_control_plane(server: control_plane_http.ControlPlaneServer) -> None:
    try:
        await asyncio.to_thread(server.shutdown)
    finally:
        try:
            remaining = await server.drain_avatar_requests(deadline_s=15.0)
            if remaining:
                logger.error(
                    "Avatar asset drain exceeded deadline: requests=%d",
                    remaining,
                )
        finally:
            server.server_close()


def run_app(
    build_runtime: BuildSessionRuntime,
    *,
    serve: ServeFn,
    session_registry: EndpointSessionRegistry | None = None,
    host: str = "0.0.0.0",
    port: int = 8765,
    control_plane_port: int | None = _DEFAULT_CONTROL_PLANE_PORT,
    on_startup: LifecycleHook | None = None,
    on_shutdown: LifecycleHook | None = None,
    diagnostics_query_factory: DiagnosticsQueryFactory | None = None,
    debug_log_query_factory: DebugLogQueryFactory | None = None,
    diagnostics_health_reader: Callable[[], dict[str, Any]] | None = None,
    voice_previewer: VoicePreviewer | None = None,
    session_conversation_reader: SessionConversationReader | None = None,
    session_input_evidence_reader: SessionInputEvidenceReader | None = None,
    session_conversation_page_reader: SessionConversationPageReader | None = None,
    session_recording_page_reader: SessionRecordingPageReader | None = None,
    session_recording_audio_reader: SessionRecordingAudioReader | None = None,
    session_history_deleter: SessionHistoryDeleter | None = None,
    avatar_asset_handler: AvatarAssetHandler | None = None,
    log_format: str = _DEFAULT_LOG_FORMAT,
) -> None:
    """Entry point a demo/deployer script calls in place of
    `asyncio.run(main())`. See module docstring for the three modes.

    `build_runtime` takes an `InMemoryEndpointSession` when `session_registry`
    is given (the resumable, WebSocket-style shape), or the raw transport
    directly when it's `None` (the non-resumable, UDP-style shape) — matching
    whatever `handle_connection`/`runtime.run()` split the demo uses.
    """
    mode = _parse_mode(sys.argv[1:])
    level = logging.DEBUG if mode == "dev" else logging.INFO
    log_filter = VoiceSessionLogFilter()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file_path = _resolve_log_file_path()
    if log_file_path is not None:
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_file_path,
                maxBytes=_LOG_FILE_MAX_BYTES,
                backupCount=_LOG_FILE_BACKUP_COUNT,
                encoding="utf-8",
            )
        )
    for handler in handlers:
        handler.addFilter(log_filter)
    logging.basicConfig(level=level, format=log_format, handlers=handlers)
    # websockets DEBUG includes complete HTTP upgrade headers. Those headers
    # carry ASR/TTS API credentials and browser cookies, so keep wire logging
    # at INFO even when the application itself runs in dev mode.
    logging.getLogger("websockets.client").setLevel(logging.INFO)
    logging.getLogger("websockets.server").setLevel(logging.INFO)
    # SDK DEBUG logs may include signed object-store request headers.  Keep
    # credentials out of the development terminal while application logs stay
    # verbose.
    logging.getLogger("boto3").setLevel(logging.INFO)
    logging.getLogger("botocore").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.INFO)
    try:
        asyncio.run(
            _run(
                mode,
                build_runtime,
                serve=serve,
                session_registry=session_registry,
                host=host,
                port=port,
                control_plane_port=control_plane_port,
                on_startup=on_startup,
                on_shutdown=on_shutdown,
                diagnostics_query_factory=diagnostics_query_factory,
                debug_log_query_factory=debug_log_query_factory,
                diagnostics_health_reader=diagnostics_health_reader,
                voice_previewer=voice_previewer,
                session_conversation_reader=session_conversation_reader,
                session_input_evidence_reader=session_input_evidence_reader,
                session_conversation_page_reader=session_conversation_page_reader,
                session_recording_page_reader=session_recording_page_reader,
                session_recording_audio_reader=session_recording_audio_reader,
                session_history_deleter=session_history_deleter,
                avatar_asset_handler=avatar_asset_handler,
            )
        )
    except KeyboardInterrupt:
        logger.info("shutdown requested")
