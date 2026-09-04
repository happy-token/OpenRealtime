"""Ordered audio processor chain and observable plugin branches."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

from server.core.interaction_context import InteractionContext
from server.realtime.plugins.context import capability_context_for
from server.realtime.plugins.interfaces import (
    AudioAnalysisEvidence,
    AudioAnalyzerSession,
    AudioProcessorSession,
    AudioSinkSession,
)
from server.realtime.profile import (
    AudioFormat,
    DataGrant,
    FailurePolicy,
    PluginKind,
    ResolvedPlugin,
    ResolvedRealtimeProfile,
)
from server.realtime.protocol.audio import AudioFrame


class AudioPluginContractError(RuntimeError):
    pass


class AudioPluginFailure(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioPluginDegraded:
    context: InteractionContext
    plugin_id: str
    policy: FailurePolicy
    error: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioPluginFailed:
    context: InteractionContext
    plugin_id: str
    error: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioPluginLatencyExceeded:
    context: InteractionContext
    plugin_id: str
    elapsed_ms: float
    budget_ms: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioAnalysisProduced:
    context: InteractionContext
    plugin_id: str
    evidence: AudioAnalysisEvidence


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioPluginGap:
    context: InteractionContext
    plugin_id: str
    dropped_sequence: int
    resumed_sequence: int


AudioPluginEvent = (
    AudioPluginDegraded
    | AudioPluginFailed
    | AudioPluginLatencyExceeded
    | AudioAnalysisProduced
    | AudioPluginGap
)
_CLOSED = object()
_BRANCH_END = object()


@dataclass(frozen=True, slots=True)
class _BoundProcessor:
    plugin: ResolvedPlugin
    session: AudioProcessorSession


@dataclass(slots=True)
class _BoundAnalyzer:
    plugin: ResolvedPlugin
    session: AudioAnalyzerSession
    queue: asyncio.Queue[AudioFrame | object]
    active: bool = True


@dataclass(slots=True)
class _BoundSink:
    plugin: ResolvedPlugin
    session: AudioSinkSession
    queue: asyncio.Queue[AudioFrame | object]
    active: bool = True


class AudioPluginGraph:
    def __init__(
        self,
        *,
        input_format: AudioFormat | None,
        processors: tuple[_BoundProcessor, ...],
        analyzers: tuple[_BoundAnalyzer, ...],
        sinks: tuple[_BoundSink, ...],
        interaction_context: InteractionContext,
        event_queue_size: int,
    ) -> None:
        self._interaction_context = interaction_context
        self._input_format = input_format
        self._processors = processors
        self._analyzers = analyzers
        self._sinks = sinks
        self._events: asyncio.Queue[AudioPluginEvent | object] = asyncio.Queue(
            maxsize=event_queue_size
        )
        self._closed = False
        self._fatal_error: AudioPluginFailure | None = None
        self._analyzer_tasks = tuple(
            asyncio.create_task(
                self._run_analyzer(analyzer),
                name=f"audio-analyzer-{analyzer.plugin.manifest.plugin_id}",
            )
            for analyzer in analyzers
        )
        self._sink_tasks = tuple(
            asyncio.create_task(
                self._run_sink(sink),
                name=f"audio-sink-{sink.plugin.manifest.plugin_id}",
            )
            for sink in sinks
        )

    @classmethod
    async def open(
        cls,
        *,
        profile: ResolvedRealtimeProfile,
        interaction_context: InteractionContext,
        pseudonymization_key: str,
        event_queue_size: int = 64,
        branch_queue_size: int = 8,
    ) -> AudioPluginGraph:
        if event_queue_size < 1 or branch_queue_size < 1:
            raise ValueError("event and branch queue sizes must be positive")
        processors: list[_BoundProcessor] = []
        analyzers: list[_BoundAnalyzer] = []
        sinks: list[_BoundSink] = []
        opened_sessions: list[
            AudioProcessorSession | AudioAnalyzerSession | AudioSinkSession
        ] = []
        try:
            for plugin in profile.plugins:
                if plugin.selection.slot not in {
                    PluginKind.AUDIO_PROCESSOR,
                    PluginKind.AUDIO_ANALYZER,
                    PluginKind.AUDIO_SINK,
                }:
                    continue
                open_session = getattr(plugin.binding, "open", None)
                if open_session is None:
                    raise AudioPluginContractError(
                        f"audio plugin {plugin.manifest.plugin_id} does not expose open()"
                    )
                session = await open_session(
                    context=capability_context_for(
                        plugin,
                        interaction_context=interaction_context,
                        pseudonymization_key=pseudonymization_key,
                    ),
                    config=plugin.selection.config,
                )
                opened_sessions.append(session)
                if plugin.selection.slot is PluginKind.AUDIO_PROCESSOR:
                    processors.append(_BoundProcessor(plugin=plugin, session=session))
                elif plugin.selection.slot is PluginKind.AUDIO_ANALYZER:
                    analyzers.append(
                        _BoundAnalyzer(
                            plugin=plugin,
                            session=session,
                            queue=asyncio.Queue(maxsize=branch_queue_size),
                        )
                    )
                else:
                    sinks.append(
                        _BoundSink(
                            plugin=plugin,
                            session=session,
                            queue=asyncio.Queue(maxsize=branch_queue_size),
                        )
                    )
        except Exception:
            await asyncio.gather(
                *(session.close() for session in reversed(opened_sessions)),
                return_exceptions=True,
            )
            raise
        return cls(
            interaction_context=interaction_context,
            input_format=profile.negotiated_input_format,
            processors=tuple(processors),
            analyzers=tuple(analyzers),
            sinks=tuple(sinks),
            event_queue_size=event_queue_size,
        )

    async def process(self, frame: AudioFrame) -> AudioFrame:
        if self._closed:
            raise RuntimeError("audio plugin graph is closed")
        if self._fatal_error is not None:
            raise self._fatal_error
        if self._input_format is not None and _format_of(frame) != self._input_format:
            raise ValueError("audio frame does not match the negotiated input format")
        current = frame
        for processor in self._processors:
            started_at = time.perf_counter()
            try:
                transformed = await processor.session.process(current)
            except Exception as error:
                if processor.plugin.failure_policy is FailurePolicy.BYPASS:
                    await self._events.put(
                        AudioPluginDegraded(
                            context=self._interaction_context,
                            plugin_id=processor.plugin.manifest.plugin_id,
                            policy=FailurePolicy.BYPASS,
                            error=str(error),
                        )
                    )
                    continue
                failure = AudioPluginFailure(
                    f"audio processor {processor.plugin.manifest.plugin_id} failed: {error}"
                )
                await self._events.put(
                    AudioPluginFailed(
                        context=self._interaction_context,
                        plugin_id=processor.plugin.manifest.plugin_id,
                        error=str(error),
                    )
                )
                raise failure from error
            await self._report_latency(processor.plugin, started_at)
            _validate_timeline_preserved(
                before=current,
                after=transformed,
                plugin_id=processor.plugin.manifest.plugin_id,
            )
            current = transformed
        for analyzer in self._analyzers:
            if not analyzer.active:
                continue
            selected = (
                frame
                if DataGrant.INPUT_AUDIO_RAW in analyzer.plugin.effective_data_grants
                else current
            )
            await self._enqueue_branch(analyzer, selected)
        for sink in self._sinks:
            if not sink.active:
                continue
            selected = (
                frame if DataGrant.INPUT_AUDIO_RAW in sink.plugin.effective_data_grants else current
            )
            await self._enqueue_branch(sink, selected)
        return current

    async def _enqueue_branch(
        self,
        branch: _BoundAnalyzer | _BoundSink,
        frame: AudioFrame,
    ) -> None:
        if branch.queue.full():
            dropped = branch.queue.get_nowait()
            branch.queue.task_done()
            assert isinstance(dropped, AudioFrame)
            await self._events.put(
                AudioPluginGap(
                    context=self._interaction_context,
                    plugin_id=branch.plugin.manifest.plugin_id,
                    dropped_sequence=dropped.sequence,
                    resumed_sequence=frame.sequence,
                )
            )
        branch.queue.put_nowait(frame)

    async def _run_analyzer(self, analyzer: _BoundAnalyzer) -> None:
        while True:
            item = await analyzer.queue.get()
            try:
                if item is _BRANCH_END:
                    return
                assert isinstance(item, AudioFrame)
                started_at = time.perf_counter()
                evidence_items = await analyzer.session.analyze(item)
                await self._report_latency(analyzer.plugin, started_at)
                for evidence in evidence_items:
                    await self._events.put(
                        AudioAnalysisProduced(
                            context=self._interaction_context,
                            plugin_id=analyzer.plugin.manifest.plugin_id,
                            evidence=evidence,
                        )
                    )
            except Exception as error:  # noqa: BLE001 - policy converts plugin failures
                if analyzer.plugin.failure_policy is FailurePolicy.DEGRADE:
                    _disable_branch(analyzer)
                    await self._events.put(
                        AudioPluginDegraded(
                            context=self._interaction_context,
                            plugin_id=analyzer.plugin.manifest.plugin_id,
                            policy=FailurePolicy.DEGRADE,
                            error=str(error),
                        )
                    )
                    return
                self._fatal_error = AudioPluginFailure(
                    f"audio analyzer {analyzer.plugin.manifest.plugin_id} failed: {error}"
                )
                _disable_branch(analyzer)
                await self._events.put(
                    AudioPluginFailed(
                        context=self._interaction_context,
                        plugin_id=analyzer.plugin.manifest.plugin_id,
                        error=str(error),
                    )
                )
                return
            finally:
                analyzer.queue.task_done()

    async def _run_sink(self, sink: _BoundSink) -> None:
        while True:
            item = await sink.queue.get()
            try:
                if item is _BRANCH_END:
                    return
                assert isinstance(item, AudioFrame)
                started_at = time.perf_counter()
                await sink.session.consume(item)
                await self._report_latency(sink.plugin, started_at)
            except Exception as error:  # noqa: BLE001 - policy converts plugin failures
                if sink.plugin.failure_policy is FailurePolicy.DEGRADE:
                    _disable_branch(sink)
                    await self._events.put(
                        AudioPluginDegraded(
                            context=self._interaction_context,
                            plugin_id=sink.plugin.manifest.plugin_id,
                            policy=FailurePolicy.DEGRADE,
                            error=str(error),
                        )
                    )
                    return
                self._fatal_error = AudioPluginFailure(
                    f"audio sink {sink.plugin.manifest.plugin_id} failed: {error}"
                )
                _disable_branch(sink)
                await self._events.put(
                    AudioPluginFailed(
                        context=self._interaction_context,
                        plugin_id=sink.plugin.manifest.plugin_id,
                        error=str(error),
                    )
                )
                return
            finally:
                sink.queue.task_done()

    async def _report_latency(
        self,
        plugin: ResolvedPlugin,
        started_at: float,
    ) -> None:
        elapsed_ms = (time.perf_counter() - started_at) * 1_000
        if elapsed_ms <= plugin.manifest.latency_budget_ms:
            return
        await self._events.put(
            AudioPluginLatencyExceeded(
                context=self._interaction_context,
                plugin_id=plugin.manifest.plugin_id,
                elapsed_ms=elapsed_ms,
                budget_ms=plugin.manifest.latency_budget_ms,
            )
        )

    async def events(self) -> AsyncIterator[AudioPluginEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            yield cast(AudioPluginEvent, event)

    async def flush(self) -> None:
        await asyncio.gather(
            *(analyzer.queue.join() for analyzer in self._analyzers),
            *(sink.queue.join() for sink in self._sinks),
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.flush()
        for analyzer in self._analyzers:
            if analyzer.active:
                await analyzer.queue.put(_BRANCH_END)
        for sink in self._sinks:
            if sink.active:
                await sink.queue.put(_BRANCH_END)
        if self._analyzer_tasks:
            await asyncio.gather(*self._analyzer_tasks, return_exceptions=True)
        if self._sink_tasks:
            await asyncio.gather(*self._sink_tasks, return_exceptions=True)
        for sink in reversed(self._sinks):
            await sink.session.close()
        for analyzer in reversed(self._analyzers):
            await analyzer.session.close()
        for processor in reversed(self._processors):
            await processor.session.close()
        await self._events.put(_CLOSED)


def _format_of(frame: AudioFrame) -> AudioFormat:
    return AudioFormat(
        encoding=frame.encoding,
        sample_rate_hz=frame.sample_rate_hz,
        channels=frame.channels,
    )


def _disable_branch(branch: _BoundAnalyzer | _BoundSink) -> None:
    branch.active = False
    while not branch.queue.empty():
        branch.queue.get_nowait()
        branch.queue.task_done()


def _validate_timeline_preserved(
    *,
    before: AudioFrame,
    after: AudioFrame,
    plugin_id: str,
) -> None:
    before_timeline = (
        before.stream_id,
        before.sequence,
        before.timestamp_us,
        before.duration_us,
    )
    after_timeline = (
        after.stream_id,
        after.sequence,
        after.timestamp_us,
        after.duration_us,
    )
    if before_timeline != after_timeline:
        raise AudioPluginContractError(
            f"audio processor {plugin_id} changed the shared media timeline"
        )
