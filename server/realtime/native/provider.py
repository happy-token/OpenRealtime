"""Low-level JSON session seam for end-to-end Realtime model providers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect

from server.core.interaction_context import InteractionContext
from server.tools.registry import ToolRegistry


class NativeRealtimeProviderSession(Protocol):
    async def send(self, message: Mapping[str, Any]) -> None: ...

    def events(self) -> AsyncIterator[Mapping[str, Any]]: ...

    async def close(self) -> None: ...


class NativeRealtimeProvider(Protocol):
    async def open(
        self,
        *,
        context: InteractionContext,
        profile: object,
    ) -> NativeRealtimeProviderSession: ...


class OpenAiRealtimeProvider:
    """Official Realtime WebSocket transport; protocol mapping lives above it."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "wss://api.openai.com/v1/realtime",
        session: Mapping[str, Any] | None = None,
        tools: ToolRegistry | None = None,
        open_timeout_s: float = 10,
    ) -> None:
        if not api_key or not model or not base_url:
            raise ValueError("OpenAI Realtime credentials and endpoint must be non-empty")
        if open_timeout_s <= 0:
            raise ValueError("OpenAI Realtime open timeout must be positive")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("?")
        configured_session = dict(session or {})
        if tools is not None:
            if "tools" in configured_session:
                raise ValueError(
                    "native realtime tools must be configured through ToolRegistry"
                )
            configured_session["tools"] = [
                {
                    "type": "function",
                    "name": descriptor.name,
                    "description": descriptor.description,
                    "parameters": descriptor.input_schema,
                }
                for descriptor in tools.descriptors()
            ]
        self._session = _controlled_session_configuration(configured_session)
        self._open_timeout_s = open_timeout_s

    async def open(
        self,
        *,
        context: InteractionContext,
        profile: object,
    ) -> JsonNativeRealtimeProviderSession:
        del context, profile
        separator = "&" if "?" in self._base_url else "?"
        url = f"{self._base_url}{separator}{urlencode({'model': self._model})}"
        connection = await connect(
            url,
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
            open_timeout=self._open_timeout_s,
        )
        opened = JsonNativeRealtimeProviderSession(connection)
        await opened.send({"type": "session.update", "session": self._session})
        return opened


class JsonNativeRealtimeProviderSession:
    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection

    async def send(self, message: Mapping[str, Any]) -> None:
        await self._connection.send(
            json.dumps(dict(message), ensure_ascii=False, separators=(",", ":"))
        )

    async def events(self) -> AsyncIterator[Mapping[str, Any]]:
        async for raw in self._connection:
            if not isinstance(raw, str):
                continue
            decoded = json.loads(raw)
            if isinstance(decoded, dict):
                yield decoded

    async def close(self) -> None:
        await self._connection.close()


def _controlled_session_configuration(
    session: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Keep endpoint detection provider-side but response ownership server-side."""

    configured = dict(session or {})
    configured.setdefault("type", "realtime")
    audio_value = configured.get("audio")
    if audio_value is not None and not isinstance(audio_value, Mapping):
        raise TypeError("native realtime session audio configuration must be an object")
    audio = dict(audio_value or {})
    input_value = audio.get("input")
    if input_value is not None and not isinstance(input_value, Mapping):
        raise TypeError("native realtime input audio configuration must be an object")
    audio_input = dict(input_value or {})

    transcription_value = audio_input.get("transcription")
    if transcription_value is not None and not isinstance(
        transcription_value, Mapping
    ):
        raise TypeError("native realtime transcription configuration must be an object")
    transcription = dict(transcription_value or {})
    transcription.setdefault("model", "gpt-4o-mini-transcribe")
    audio_input["transcription"] = transcription

    detection_value = audio_input.get("turn_detection")
    if detection_value is not None and not isinstance(detection_value, Mapping):
        raise TypeError("native realtime turn detection configuration must be an object")
    turn_detection = dict(detection_value or {})
    turn_detection.setdefault("type", "server_vad")
    turn_detection["create_response"] = False
    turn_detection["interrupt_response"] = False
    audio_input["turn_detection"] = turn_detection
    audio["input"] = audio_input
    configured["audio"] = audio
    return configured
