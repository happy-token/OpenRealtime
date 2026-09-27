from __future__ import annotations

import pytest

from server.core.interaction_context import InteractionContext
from server.realtime.capabilities.asr import AsrTranscriptDelta, AsrTranscriptFinal
from server.realtime.capabilities.brain import BrainTextDelta
from server.realtime.capabilities.tts import AppendTtsText, CommitTts, TtsAudioFrame
from server.realtime.profile.models import (
    AudioFormat,
    DataGrant,
    FailurePolicy,
    PluginKind,
    PluginManifest,
    PluginPlacement,
)
from server.realtime.protocol.audio import AudioEncoding, AudioFrame
from server.realtime.provider_bridge import (
    ProviderBridgeContractError,
    validate_user_provider_bridge,
    verify_asr_probe,
    verify_llm_probe,
    verify_tts_probe,
)


def manifest(
    kind: PluginKind,
    capabilities: set[str],
    *,
    placement: PluginPlacement = PluginPlacement.SIDECAR,
    contract_version: int = 1,
) -> PluginManifest:
    return PluginManifest(
        plugin_id=f"test.{kind.value}",
        plugin_version="1.0.0",
        plugin_kind=kind,
        contract_version=contract_version,
        placement=placement,
        capabilities=frozenset(capabilities),
        audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
        latency_budget_ms=1_000,
        approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
        allowed_failure_policies=frozenset({FailurePolicy.FAIL}),
        default_failure_policy=FailurePolicy.FAIL,
    )


@pytest.mark.parametrize(
    ("kind", "capabilities"),
    [
        (PluginKind.ASR, {"streaming_transcription", "partial_transcript", "final_transcript"}),
        (PluginKind.TTS, {"duplex_speech_synthesis", "streaming_audio"}),
        (PluginKind.BRAIN, {"streaming_reasoning", "streaming_text"}),
    ],
)
def test_required_realtime_bridge_manifest_is_admitted(kind, capabilities) -> None:
    validate_user_provider_bridge(manifest(kind, capabilities))


@pytest.mark.parametrize(
    ("kind", "capabilities", "missing"),
    [
        (PluginKind.ASR, {"streaming_transcription", "final_transcript"}, "partial_transcript"),
        (PluginKind.ASR, {"streaming_transcription", "partial_transcript"}, "final_transcript"),
        (PluginKind.TTS, {"streaming_audio"}, "duplex_speech_synthesis"),
        (PluginKind.BRAIN, {"streaming_reasoning"}, "streaming_text"),
    ],
)
def test_missing_required_capability_is_rejected(kind, capabilities, missing) -> None:
    with pytest.raises(ProviderBridgeContractError, match=missing):
        validate_user_provider_bridge(manifest(kind, capabilities))


def test_user_bridge_cannot_be_loaded_in_main_process() -> None:
    with pytest.raises(ProviderBridgeContractError, match="outside the main process"):
        validate_user_provider_bridge(
            manifest(
                PluginKind.BRAIN,
                {"streaming_reasoning", "streaming_text"},
                placement=PluginPlacement.IN_PROCESS,
            )
        )


def test_unknown_contract_version_is_rejected() -> None:
    with pytest.raises(ProviderBridgeContractError, match="contract version"):
        validate_user_provider_bridge(
            manifest(
                PluginKind.BRAIN,
                {"streaming_reasoning", "streaming_text"},
                contract_version=2,
            )
        )


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant", user_id="user", device_id="device",
        voice_session_id="voice", thread_id="thread", turn_id="turn", generation=1,
    )


def test_asr_probe_requires_partial_then_final() -> None:
    partial = AsrTranscriptDelta(
        context=context(), revision=1, delta="你", accumulated_text="你",
    )
    final = AsrTranscriptFinal(
        context=context(), revision=1, text="你好", reason="end_of_turn",
    )
    verify_asr_probe([partial, final])
    with pytest.raises(ProviderBridgeContractError, match="preceding partial"):
        verify_asr_probe([final])
    with pytest.raises(ProviderBridgeContractError, match="final text is missing"):
        verify_asr_probe([partial])
    other_turn = AsrTranscriptFinal(
        context=InteractionContext(
            tenant_id="tenant", user_id="user", device_id="device",
            voice_session_id="voice", thread_id="thread", turn_id="other", generation=1,
        ),
        revision=1, text="你好", reason="end_of_turn",
    )
    with pytest.raises(ProviderBridgeContractError, match="mixed turn identities"):
        verify_asr_probe([partial, other_turn])


def test_tts_probe_requires_audio_before_text_commit() -> None:
    first = AppendTtsText(speech_id="speech", text_sequence=1, delta="你")
    second = AppendTtsText(speech_id="speech", text_sequence=2, delta="好")
    audio = TtsAudioFrame(
        context=context(), speech_id="speech",
        frame=AudioFrame(
            stream_id="speech", sequence=0, timestamp_us=0, duration_us=20_000,
            encoding=AudioEncoding.PCM_S16LE, sample_rate_hz=16_000,
            channels=1, data=b"\x00\x00",
        ),
        is_final_for_segment=False,
    )
    commit = CommitTts(speech_id="speech")
    verify_tts_probe([first, second, audio, commit])
    with pytest.raises(ProviderBridgeContractError, match="before a multi-chunk"):
        verify_tts_probe([first, second, commit, audio])


def test_llm_probe_requires_more_than_one_ordered_text_chunk() -> None:
    first = BrainTextDelta(
        context=context(), response_id="response", response_sequence=2, delta="你",
    )
    second = BrainTextDelta(
        context=context(), response_id="response", response_sequence=3, delta="好",
    )
    verify_llm_probe([first, second])
    with pytest.raises(ProviderBridgeContractError, match="incremental"):
        verify_llm_probe([first])
