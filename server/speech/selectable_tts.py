"""Session-scoped TTS provider selection behind one speech interface."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Protocol

from server.speech.tts import SynthesizedAudio, SynthesizedAudioChunk, TtsSessionConfig


class SelectableTtsProvider(Protocol):
    async def synthesize(self, text: str) -> SynthesizedAudio: ...

    def synthesize_stream(self, text: str) -> AsyncIterator[SynthesizedAudioChunk]: ...

    def synthesize_duplex(
        self,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]: ...


TtsProviderFactory = Callable[[TtsSessionConfig], SelectableTtsProvider]


class SelectableTtsEngine:
    """Route each synthesis call through the provider selected for this session."""

    def __init__(
        self,
        *,
        factories: Mapping[str, TtsProviderFactory],
        provider: str,
        config: TtsSessionConfig,
    ) -> None:
        if provider not in factories:
            raise ValueError(f"TTS provider is not configured: {provider}")
        self._factories = dict(factories)
        self._provider = provider
        self._config = config
        self._engine = self._factories[provider](config)
        self._lock = asyncio.Lock()

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def available_providers(self) -> tuple[str, ...]:
        return tuple(self._factories)

    async def select(self, provider: str, config: TtsSessionConfig) -> None:
        factory = self._factories.get(provider)
        if factory is None:
            raise ValueError(f"TTS provider is not configured: {provider}")
        async with self._lock:
            if provider == self._provider and config == self._config:
                return
            replacement = factory(config)
            previous = self._engine
            self._engine = replacement
            self._provider = provider
            self._config = config
            await _close_engine(previous)

    async def warmup(self) -> None:
        async with self._lock:
            warmup = getattr(self._engine, "warmup", None)
            if warmup is not None:
                await warmup()

    async def synthesize(self, text: str) -> SynthesizedAudio:
        async with self._lock:
            return await self._engine.synthesize(text)

    async def synthesize_stream(self, text: str) -> AsyncIterator[SynthesizedAudioChunk]:
        async with self._lock:
            async for chunk in self._engine.synthesize_stream(text):
                yield chunk

    async def synthesize_duplex(
        self,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        async with self._lock:
            async for chunk in self._engine.synthesize_duplex(text_stream):
                yield chunk

    async def close(self) -> None:
        async with self._lock:
            await _close_engine(self._engine)


async def _close_engine(engine: SelectableTtsProvider) -> None:
    close = getattr(engine, "close", None)
    if close is not None:
        await close()
