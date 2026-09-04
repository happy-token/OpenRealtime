from __future__ import annotations

import array
import asyncio

import pytest

from server.core.interaction_context import InteractionContext
from server.realtime import AudioEncoding, AudioFrame
from server.realtime.plugins import (
    AudioAnalysisProduced,
    AudioPluginDegraded,
    AudioPluginFailed,
    AudioPluginFailure,
    AudioPluginGap,
    AudioPluginGraph,
    AudioPluginLatencyExceeded,
    CapabilityContext,
    SpeakerDecision,
    SpeakerEvidence,
)
from server.realtime.profile import (
    AudioFormat,
    DataGrant,
    EngineKind,
    FailurePolicy,
    PluginKind,
    PluginManifest,
    PluginPlacement,
    PluginRegistry,
    PluginSelection,
    ProfileResolver,
    RealtimeProfile,
)


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-secret",
        user_id="user-secret",
        device_id="device-secret",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )


def frame(amplitude: int = 10, *, sequence: int = 0) -> AudioFrame:
    return AudioFrame(
        stream_id="input-1",
        sequence=sequence,
        timestamp_us=sequence * 32_000,
        duration_us=32_000,
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate_hz=16_000,
        channels=1,
        data=array.array("h", [amplitude] * 512).tobytes(),
    )


class ArithmeticProcessorBinding:
    def __init__(self, operation: str) -> None:
        self.operation = operation
        self.contexts: list[CapabilityContext] = []

    async def open(self, *, context: CapabilityContext, config: dict[str, object]):
        self.contexts.append(context)
        return ArithmeticProcessorSession(self.operation, int(config["value"]))


class ArithmeticProcessorSession:
    def __init__(self, operation: str, value: int) -> None:
        self.operation = operation
        self.value = value

    async def process(self, audio: AudioFrame) -> AudioFrame:
        samples = array.array("h")
        samples.frombytes(audio.data)
        if self.operation == "multiply":
            samples = array.array("h", (sample * self.value for sample in samples))
        else:
            samples = array.array("h", (sample + self.value for sample in samples))
        return AudioFrame(
            stream_id=audio.stream_id,
            sequence=audio.sequence,
            timestamp_us=audio.timestamp_us,
            duration_us=audio.duration_us,
            encoding=audio.encoding,
            sample_rate_hz=audio.sample_rate_hz,
            channels=audio.channels,
            data=samples.tobytes(),
        )

    async def close(self) -> None:
        return None


class TrackedProcessorBinding:
    def __init__(self) -> None:
        self.session = TrackedProcessorSession()

    async def open(self, *, context: CapabilityContext, config: dict[str, object]):
        del context, config
        return self.session


class TrackedProcessorSession:
    def __init__(self) -> None:
        self.closed = False

    async def process(self, audio: AudioFrame) -> AudioFrame:
        return audio

    async def close(self) -> None:
        self.closed = True


class OpenFailureBinding:
    async def open(self, *, context: CapabilityContext, config: dict[str, object]):
        del context, config
        raise RuntimeError("plugin refused to open")


def processor_manifest(
    plugin_id: str,
    *,
    failure_policy: FailurePolicy = FailurePolicy.FAIL,
    bypass_safe: bool = False,
) -> PluginManifest:
    return PluginManifest(
        plugin_id=plugin_id,
        plugin_version="1.0.0",
        plugin_kind=PluginKind.AUDIO_PROCESSOR,
        contract_version=1,
        placement=PluginPlacement.IN_PROCESS,
        capabilities=frozenset({plugin_id}),
        audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
        latency_budget_ms=20,
        approved_data_grants=frozenset(
            {DataGrant.INPUT_AUDIO_RAW, DataGrant.INPUT_AUDIO_PROCESSED}
        ),
        allowed_failure_policies=frozenset({failure_policy}),
        default_failure_policy=failure_policy,
        bypass_safe=bypass_safe,
    )


async def test_partial_audio_plugin_open_closes_already_opened_sessions() -> None:
    registry = PluginRegistry()
    tracked = TrackedProcessorBinding()
    registry.register(processor_manifest("test.tracked"), binding=tracked)
    registry.register(processor_manifest("test.open-failure"), binding=OpenFailureBinding())
    resolved = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.AUDIO_PROCESSOR,
                    plugin_id="test.tracked",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
                ),
                PluginSelection(
                    slot=PluginKind.AUDIO_PROCESSOR,
                    plugin_id="test.open-failure",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
                ),
            ),
        )
    )

    with pytest.raises(RuntimeError, match="plugin refused to open"):
        await AudioPluginGraph.open(
            profile=resolved,
            interaction_context=context(),
            pseudonymization_key="test-only-key",
        )

    assert tracked.session.closed is True


async def test_audio_processors_run_in_profile_order_with_minimized_context() -> None:
    registry = PluginRegistry()
    multiply = ArithmeticProcessorBinding("multiply")
    add = ArithmeticProcessorBinding("add")
    registry.register(processor_manifest("test.multiply"), binding=multiply)
    registry.register(processor_manifest("test.add"), binding=add)
    resolved = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.AUDIO_PROCESSOR,
                    plugin_id="test.multiply",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
                    config={"value": 2},
                ),
                PluginSelection(
                    slot=PluginKind.AUDIO_PROCESSOR,
                    plugin_id="test.add",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
                    config={"value": 1},
                ),
            ),
        )
    )
    graph = await AudioPluginGraph.open(
        profile=resolved,
        interaction_context=context(),
        pseudonymization_key="test-only-key",
    )

    processed = await graph.process(frame())

    samples = array.array("h")
    samples.frombytes(processed.data)
    assert samples[0] == 21
    assert processed.timestamp_us == 0
    assert processed.duration_us == 32_000
    assert multiply.contexts[0].tenant_pseudonymous_id is None
    assert not hasattr(multiply.contexts[0], "user_id")

    await graph.close()


class FailingProcessorBinding:
    async def open(self, *, context: CapabilityContext, config: dict[str, object]):
        del context, config
        return FailingProcessorSession()


class FailingProcessorSession:
    async def process(self, audio: AudioFrame) -> AudioFrame:
        del audio
        raise RuntimeError("noise model crashed")

    async def close(self) -> None:
        return None


async def test_bypass_safe_processor_failure_is_observable_and_preserves_audio() -> None:
    registry = PluginRegistry()
    registry.register(
        processor_manifest(
            "test.failing",
            failure_policy=FailurePolicy.BYPASS,
            bypass_safe=True,
        ),
        binding=FailingProcessorBinding(),
    )
    resolved = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.AUDIO_PROCESSOR,
                    plugin_id="test.failing",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
                ),
            ),
        )
    )
    graph = await AudioPluginGraph.open(
        profile=resolved,
        interaction_context=context(),
        pseudonymization_key="test-only-key",
    )
    events = graph.events()
    original = frame()

    processed = await graph.process(original)
    degraded = await anext(events)

    assert processed is original
    assert isinstance(degraded, AudioPluginDegraded)
    assert degraded.plugin_id == "test.failing"
    assert degraded.policy is FailurePolicy.BYPASS
    assert degraded.error == "noise model crashed"

    await graph.close()


class VoiceprintAnalyzerBinding:
    def __init__(self) -> None:
        self.samples_seen: list[int] = []

    async def open(self, *, context: CapabilityContext, config: dict[str, object]):
        assert DataGrant.INPUT_AUDIO_PROCESSED in context.effective_data_grants
        return VoiceprintAnalyzerSession(self.samples_seen, float(config["confidence"]))


class VoiceprintAnalyzerSession:
    def __init__(self, samples_seen: list[int], confidence: float) -> None:
        self.samples_seen = samples_seen
        self.confidence = confidence

    async def analyze(self, audio: AudioFrame) -> tuple[SpeakerEvidence, ...]:
        samples = array.array("h")
        samples.frombytes(audio.data)
        self.samples_seen.append(samples[0])
        return (
            SpeakerEvidence(
                speaker_profile_id="speaker-1",
                confidence=self.confidence,
                audio_start_us=audio.timestamp_us,
                audio_end_us=audio.end_timestamp_us,
                model_version="voiceprint-2",
                enrollment_version="enrollment-3",
                decision=SpeakerDecision.MATCH,
            ),
        )

    async def close(self) -> None:
        return None


async def test_analyzer_observes_processed_branch_and_emits_non_authoritative_evidence() -> None:
    registry = PluginRegistry()
    multiply = ArithmeticProcessorBinding("multiply")
    analyzer = VoiceprintAnalyzerBinding()
    registry.register(processor_manifest("test.multiply"), binding=multiply)
    registry.register(
        PluginManifest(
            plugin_id="test.voiceprint",
            plugin_version="1.0.0",
            plugin_kind=PluginKind.AUDIO_ANALYZER,
            contract_version=1,
            placement=PluginPlacement.SIDECAR,
            capabilities=frozenset({"speaker_evidence"}),
            audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
            latency_budget_ms=80,
            approved_data_grants=frozenset(
                {
                    DataGrant.INPUT_AUDIO_PROCESSED,
                    DataGrant.SPEAKER_PROFILE_REFERENCE,
                }
            ),
            allowed_failure_policies=frozenset({FailurePolicy.DEGRADE}),
            default_failure_policy=FailurePolicy.DEGRADE,
        ),
        binding=analyzer,
    )
    resolved = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.AUDIO_PROCESSOR,
                    plugin_id="test.multiply",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
                    config={"value": 2},
                ),
                PluginSelection(
                    slot=PluginKind.AUDIO_ANALYZER,
                    plugin_id="test.voiceprint",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset(
                        {
                            DataGrant.INPUT_AUDIO_PROCESSED,
                            DataGrant.SPEAKER_PROFILE_REFERENCE,
                        }
                    ),
                    config={"confidence": 0.91},
                ),
            ),
        )
    )
    graph = await AudioPluginGraph.open(
        profile=resolved,
        interaction_context=context(),
        pseudonymization_key="test-only-key",
    )
    events = graph.events()

    await graph.process(frame())
    produced = await anext(events)

    assert analyzer.samples_seen == [20]
    assert isinstance(produced, AudioAnalysisProduced)
    assert produced.plugin_id == "test.voiceprint"
    assert produced.evidence.decision is SpeakerDecision.MATCH
    assert produced.evidence.confidence == 0.91
    assert not hasattr(produced.evidence, "user_id")

    await graph.close()


class RecordingSinkBinding:
    def __init__(self) -> None:
        self.samples: list[int] = []
        self.contexts: list[CapabilityContext] = []

    async def open(self, *, context: CapabilityContext, config: dict[str, object]):
        del config
        self.contexts.append(context)
        return RecordingSinkSession(self.samples)


class RecordingSinkSession:
    def __init__(self, samples: list[int]) -> None:
        self.samples = samples

    async def consume(self, audio: AudioFrame) -> None:
        values = array.array("h")
        values.frombytes(audio.data)
        self.samples.append(values[0])

    async def close(self) -> None:
        return None


async def test_audio_sink_consumes_processed_branch_without_changing_main_output() -> None:
    registry = PluginRegistry()
    multiply = ArithmeticProcessorBinding("multiply")
    sink = RecordingSinkBinding()
    registry.register(processor_manifest("test.multiply"), binding=multiply)
    registry.register(
        PluginManifest(
            plugin_id="test.recorder",
            plugin_version="1.0.0",
            plugin_kind=PluginKind.AUDIO_SINK,
            contract_version=1,
            placement=PluginPlacement.SIDECAR,
            capabilities=frozenset({"audio_recording"}),
            audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
            latency_budget_ms=100,
            approved_data_grants=frozenset(
                {DataGrant.INPUT_AUDIO_PROCESSED, DataGrant.ARTIFACT_WRITE}
            ),
            allowed_failure_policies=frozenset({FailurePolicy.DEGRADE}),
            default_failure_policy=FailurePolicy.DEGRADE,
            data_classification="voice_recording",
            retention_days=30,
        ),
        binding=sink,
    )
    resolved = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.AUDIO_PROCESSOR,
                    plugin_id="test.multiply",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
                    config={"value": 2},
                ),
                PluginSelection(
                    slot=PluginKind.AUDIO_SINK,
                    plugin_id="test.recorder",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset(
                        {DataGrant.INPUT_AUDIO_PROCESSED, DataGrant.ARTIFACT_WRITE}
                    ),
                ),
            ),
        )
    )
    graph = await AudioPluginGraph.open(
        profile=resolved,
        interaction_context=context(),
        pseudonymization_key="test-only-key",
    )

    processed = await graph.process(frame())
    await graph.flush()

    output = array.array("h")
    output.frombytes(processed.data)
    assert output[0] == 20
    assert sink.samples == [20]
    assert DataGrant.ARTIFACT_WRITE in sink.contexts[0].effective_data_grants

    await graph.close()


class SlowAnalyzerBinding:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def open(self, *, context: CapabilityContext, config: dict[str, object]):
        del context, config
        return SlowAnalyzerSession(self.started, self.release)


class SlowAnalyzerSession:
    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        self.started = started
        self.release = release

    async def analyze(self, audio: AudioFrame) -> tuple[SpeakerEvidence, ...]:
        self.started.set()
        await self.release.wait()
        return ()

    async def close(self) -> None:
        return None


async def test_optional_branch_overflow_emits_audio_gap_instead_of_silent_drop() -> None:
    registry = PluginRegistry()
    analyzer = SlowAnalyzerBinding()
    registry.register(
        PluginManifest(
            plugin_id="test.slow-analyzer",
            plugin_version="1.0.0",
            plugin_kind=PluginKind.AUDIO_ANALYZER,
            contract_version=1,
            placement=PluginPlacement.IN_PROCESS,
            capabilities=frozenset({"audio_quality"}),
            audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
            latency_budget_ms=100,
            approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
            allowed_failure_policies=frozenset({FailurePolicy.DEGRADE}),
            default_failure_policy=FailurePolicy.DEGRADE,
        ),
        binding=analyzer,
    )
    resolved = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.AUDIO_ANALYZER,
                    plugin_id="test.slow-analyzer",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
                ),
            ),
        )
    )
    graph = await AudioPluginGraph.open(
        profile=resolved,
        interaction_context=context(),
        pseudonymization_key="test-only-key",
        branch_queue_size=1,
    )
    events = graph.events()
    await graph.process(frame(sequence=0))
    await analyzer.started.wait()
    await graph.process(frame(sequence=1))

    await graph.process(frame(sequence=2))

    gap = await anext(events)
    assert isinstance(gap, AudioPluginGap)
    assert gap.plugin_id == "test.slow-analyzer"
    assert gap.dropped_sequence == 1
    assert gap.resumed_sequence == 2

    analyzer.release.set()
    await graph.close()


class FailingAnalyzerBinding:
    async def open(self, *, context: CapabilityContext, config: dict[str, object]):
        del context, config
        return FailingAnalyzerSession()


class FailingAnalyzerSession:
    async def analyze(self, audio: AudioFrame) -> tuple[SpeakerEvidence, ...]:
        del audio
        raise RuntimeError("analyzer transport failed")

    async def close(self) -> None:
        return None


async def test_fail_policy_branch_error_becomes_event_and_stops_future_audio() -> None:
    registry = PluginRegistry()
    registry.register(
        PluginManifest(
            plugin_id="test.required-analyzer",
            plugin_version="1.0.0",
            plugin_kind=PluginKind.AUDIO_ANALYZER,
            contract_version=1,
            placement=PluginPlacement.REMOTE,
            capabilities=frozenset({"required_audio_analysis"}),
            audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
            latency_budget_ms=100,
            approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
            allowed_failure_policies=frozenset({FailurePolicy.FAIL}),
            default_failure_policy=FailurePolicy.FAIL,
        ),
        binding=FailingAnalyzerBinding(),
    )
    resolved = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.AUDIO_ANALYZER,
                    plugin_id="test.required-analyzer",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
                ),
            ),
        )
    )
    graph = await AudioPluginGraph.open(
        profile=resolved,
        interaction_context=context(),
        pseudonymization_key="test-only-key",
    )
    events = graph.events()
    await graph.process(frame())

    failed = await anext(events)
    assert isinstance(failed, AudioPluginFailed)
    assert failed.plugin_id == "test.required-analyzer"
    assert failed.error == "analyzer transport failed"

    with pytest.raises(AudioPluginFailure, match="required-analyzer"):
        await graph.process(frame(sequence=1))

    await graph.close()


async def test_degraded_optional_branch_is_disabled_without_blocking_flush() -> None:
    registry = PluginRegistry()
    registry.register(
        PluginManifest(
            plugin_id="test.optional-analyzer",
            plugin_version="1.0.0",
            plugin_kind=PluginKind.AUDIO_ANALYZER,
            contract_version=1,
            placement=PluginPlacement.REMOTE,
            capabilities=frozenset({"optional_audio_analysis"}),
            audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
            latency_budget_ms=100,
            approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
            allowed_failure_policies=frozenset({FailurePolicy.DEGRADE}),
            default_failure_policy=FailurePolicy.DEGRADE,
        ),
        binding=FailingAnalyzerBinding(),
    )
    resolved = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.AUDIO_ANALYZER,
                    plugin_id="test.optional-analyzer",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
                ),
            ),
        )
    )
    graph = await AudioPluginGraph.open(
        profile=resolved,
        interaction_context=context(),
        pseudonymization_key="test-only-key",
    )
    events = graph.events()
    await graph.process(frame())
    degraded = await anext(events)
    assert isinstance(degraded, AudioPluginDegraded)

    await graph.process(frame(sequence=1))
    await asyncio.wait_for(graph.flush(), timeout=0.1)

    await graph.close()


class SlowProcessorBinding:
    async def open(self, *, context: CapabilityContext, config: dict[str, object]):
        del context, config
        return SlowProcessorSession()


class SlowProcessorSession:
    async def process(self, audio: AudioFrame) -> AudioFrame:
        await asyncio.sleep(0.01)
        return audio

    async def close(self) -> None:
        return None


async def test_plugin_latency_budget_overrun_is_observable() -> None:
    registry = PluginRegistry()
    manifest = PluginManifest(
        plugin_id="test.slow-processor",
        plugin_version="1.0.0",
        plugin_kind=PluginKind.AUDIO_PROCESSOR,
        contract_version=1,
        placement=PluginPlacement.IN_PROCESS,
        capabilities=frozenset({"slow_processing"}),
        audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
        latency_budget_ms=1,
        approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
        allowed_failure_policies=frozenset({FailurePolicy.FAIL}),
        default_failure_policy=FailurePolicy.FAIL,
    )
    registry.register(manifest, binding=SlowProcessorBinding())
    resolved = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.AUDIO_PROCESSOR,
                    plugin_id=manifest.plugin_id,
                    plugin_version=manifest.plugin_version,
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
                ),
            ),
        )
    )
    graph = await AudioPluginGraph.open(
        profile=resolved,
        interaction_context=context(),
        pseudonymization_key="test-only-key",
    )
    events = graph.events()

    await graph.process(frame())
    exceeded = await anext(events)

    assert isinstance(exceeded, AudioPluginLatencyExceeded)
    assert exceeded.plugin_id == manifest.plugin_id
    assert exceeded.budget_ms == 1
    assert exceeded.elapsed_ms >= 5

    await graph.close()
