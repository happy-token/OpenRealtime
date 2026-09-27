"""Admission rules for untrusted realtime provider bridge manifests.

The bridge process is deliberately not launched here. A manifest only declares
what an isolated bridge claims; behavioral conformance is checked separately.
"""

from __future__ import annotations

from collections.abc import Iterable

from server.realtime.capabilities.asr import AsrTranscriptDelta, AsrTranscriptFinal
from server.realtime.capabilities.brain import BrainTextDelta
from server.realtime.capabilities.tts import AppendTtsText, CommitTts, TtsAudioFrame
from server.realtime.profile.models import (
    PluginKind,
    PluginManifest,
    PluginPlacement,
)


class ProviderBridgeContractError(ValueError):
    """A bridge cannot be used as the advertised realtime capability."""


_REQUIRED_CAPABILITIES = {
    PluginKind.ASR: frozenset(
        {"streaming_transcription", "partial_transcript", "final_transcript"}
    ),
    PluginKind.TTS: frozenset({"duplex_speech_synthesis", "streaming_audio"}),
    PluginKind.BRAIN: frozenset({"streaming_reasoning", "streaming_text"}),
}


def validate_user_provider_bridge(manifest: PluginManifest) -> None:
    """Reject unsupported or in-process user bridge declarations before selection.

    A passing manifest is necessary but not sufficient: the sidecar/remote
    implementation must also pass the capability contract suite and health test.
    """

    if manifest.plugin_kind not in _REQUIRED_CAPABILITIES:
        raise ProviderBridgeContractError("only ASR, TTS, and LLM bridges are supported")
    if manifest.contract_version != 1:
        raise ProviderBridgeContractError("unsupported provider bridge contract version")
    if manifest.placement not in {PluginPlacement.SIDECAR, PluginPlacement.REMOTE}:
        raise ProviderBridgeContractError("user bridge must run outside the main process")
    missing = _REQUIRED_CAPABILITIES[manifest.plugin_kind] - manifest.capabilities
    if missing:
        raise ProviderBridgeContractError(
            "missing required realtime capabilities: " + ", ".join(sorted(missing))
        )
    if manifest.plugin_kind is PluginKind.ASR and not manifest.audio_formats:
        raise ProviderBridgeContractError("ASR bridge must declare an input audio format")
    if manifest.plugin_kind is PluginKind.TTS and not manifest.audio_formats:
        raise ProviderBridgeContractError("TTS bridge must declare an output audio format")


def verify_asr_probe(events: Iterable[AsrTranscriptDelta | AsrTranscriptFinal]) -> None:
    """Validate the observable partial/final sequence of one speech test turn."""

    partial_revision = 0
    final_seen = False
    turn_id: str | None = None
    for event in events:
        if final_seen:
            raise ProviderBridgeContractError("ASR emitted text after final text")
        if turn_id is None:
            turn_id = event.context.turn_id
        elif event.context.turn_id != turn_id:
            raise ProviderBridgeContractError("ASR probe mixed turn identities")
        if isinstance(event, AsrTranscriptDelta):
            if event.revision <= partial_revision:
                raise ProviderBridgeContractError("ASR partial revisions must increase")
            if not event.accumulated_text.strip():
                raise ProviderBridgeContractError("ASR partial text must be non-empty")
            partial_revision = event.revision
        elif isinstance(event, AsrTranscriptFinal):
            if not partial_revision or event.revision < partial_revision:
                raise ProviderBridgeContractError("ASR final requires a preceding partial text")
            if not event.text.strip():
                raise ProviderBridgeContractError("ASR final text must be non-empty")
            final_seen = True
        else:
            raise ProviderBridgeContractError("unexpected ASR probe event")
    if not final_seen:
        raise ProviderBridgeContractError("ASR final text is missing")


def verify_tts_probe(events: Iterable[AppendTtsText | CommitTts | TtsAudioFrame]) -> None:
    """Require audio while the text stream remains open in one test speech."""

    first_speech: str | None = None
    last_text_sequence = 0
    text_chunks = 0
    first_audio_before_commit = False
    committed = False
    for event in events:
        if first_speech is None:
            first_speech = event.speech_id
        elif event.speech_id != first_speech:
            raise ProviderBridgeContractError("TTS probe mixed speech identities")
        if isinstance(event, AppendTtsText):
            if committed or event.text_sequence != last_text_sequence + 1:
                raise ProviderBridgeContractError("TTS text chunks must be ordered before commit")
            last_text_sequence = event.text_sequence
            text_chunks += 1
        elif isinstance(event, CommitTts):
            if committed:
                raise ProviderBridgeContractError("TTS text stream committed twice")
            committed = True
        elif isinstance(event, TtsAudioFrame):
            if text_chunks and not committed and event.frame.data:
                first_audio_before_commit = True
        else:
            raise ProviderBridgeContractError("unexpected TTS probe event")
    if text_chunks < 2 or not committed or not first_audio_before_commit:
        raise ProviderBridgeContractError(
            "TTS must emit audio before a multi-chunk text stream is committed"
        )


def verify_llm_probe(events: Iterable[BrainTextDelta]) -> None:
    """Require observable incremental text for the standard streaming probe."""

    response_id: str | None = None
    last_sequence = 0
    chunks = 0
    for event in events:
        if not isinstance(event, BrainTextDelta):
            raise ProviderBridgeContractError("unexpected LLM probe event")
        if response_id is None:
            response_id = event.response_id
        elif response_id != event.response_id:
            raise ProviderBridgeContractError("LLM probe mixed response identities")
        if event.response_sequence <= last_sequence:
            raise ProviderBridgeContractError("LLM text chunks must be ordered")
        if not event.delta.strip():
            raise ProviderBridgeContractError("LLM text chunks must be non-empty")
        last_sequence = event.response_sequence
        chunks += 1
    if chunks < 2:
        raise ProviderBridgeContractError("LLM probe requires incremental text output")
