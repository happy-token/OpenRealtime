"""One assembly entry point for the replaceable, event-driven voice pipeline.

Bindings are providers, never already-open sessions. Per-conversation state is
created by open(); Profile overrides are validated before any media starts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from server.realtime.capabilities.asr import AsrCapabilityProvider
from server.realtime.capabilities.brain import BrainCapabilityProvider
from server.realtime.capabilities.speech_renderer import SpeechRenderer
from server.realtime.capabilities.tts import TtsCapabilityProvider
from server.realtime.capabilities.turn_manager import TurnManagerCapabilityProvider
from server.realtime.capabilities.vad import VadCapabilityProvider
from server.realtime.cascaded.engine import CascadedRealtimeEngine
from server.realtime.profile.builtin import BuiltinCascadedBindings, resolve_builtin_profile
from server.realtime.profile.models import EngineKind, PluginKind, ResolvedRealtimeProfile
from server.realtime.profile.registry import RegisteredPlugin
from server.realtime.provider_latency import ProviderLatencyObserver
from server.realtime.speech.delivery import SpeechDeliveryStore
from server.voice_session.context import ModelContextProjector


@dataclass(frozen=True, slots=True, kw_only=True)
class CascadedPipelineBindings:
    vad: VadCapabilityProvider
    asr: AsrCapabilityProvider
    turn_manager: TurnManagerCapabilityProvider
    brain: BrainCapabilityProvider
    speech_renderer: SpeechRenderer
    tts: TtsCapabilityProvider


@dataclass(frozen=True, slots=True, kw_only=True)
class CascadedPipelineOptions:
    event_queue_size: int = 64
    response_timeout_s: float = 30
    response_first_text_timeout_s: float = 5
    response_cancel_timeout_s: float = 0.8
    pseudonymization_key: str | None = None
    speech_deliveries: SpeechDeliveryStore | None = None
    context_projector_factory: Callable[[], ModelContextProjector] | None = None
    provider_timing: ProviderLatencyObserver | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CascadedPipeline:
    engine: CascadedRealtimeEngine
    profile: ResolvedRealtimeProfile

    @classmethod
    def assemble(
        cls,
        bindings: CascadedPipelineBindings,
        *,
        options: CascadedPipelineOptions | None = None,
        profile_path: str | Path | None = None,
        plugins: tuple[RegisteredPlugin, ...] = (),
    ) -> CascadedPipeline:
        options = options or CascadedPipelineOptions()
        profile = resolve_builtin_profile(
            BuiltinCascadedBindings(
                vad=bindings.vad,
                asr=bindings.asr,
                turn_manager=bindings.turn_manager,
                brain=bindings.brain,
                speech_renderer=bindings.speech_renderer,
                tts=bindings.tts,
            ),
            profile_path=profile_path,
            plugins=plugins,
        )
        if profile.engine_kind is not EngineKind.CASCADED:
            raise ValueError("CascadedPipeline requires a cascaded profile")
        for kind, fallback in (
            (PluginKind.VAD, bindings.vad),
            (PluginKind.ASR, bindings.asr),
            (PluginKind.TURN_MANAGER, bindings.turn_manager),
            (PluginKind.BRAIN, bindings.brain),
            (PluginKind.SPEECH_RENDERER, bindings.speech_renderer),
            (PluginKind.TTS, bindings.tts),
        ):
            selected = [plugin for plugin in profile.plugins if plugin.selection.slot is kind]
            if len(selected) > 1:
                raise ValueError(f"pipeline selects more than one {kind.value} plugin")
            binding = selected[0].binding if selected else fallback
            method = "render" if kind is PluginKind.SPEECH_RENDERER else "open"
            if not callable(getattr(binding, method, None)):
                raise TypeError(f"{kind.value} binding must expose {method}()")
        engine = CascadedRealtimeEngine(
            vad=bindings.vad,
            asr=bindings.asr,
            turn_manager=bindings.turn_manager,
            brain=bindings.brain,
            speech_renderer=bindings.speech_renderer,
            tts=bindings.tts,
            event_queue_size=options.event_queue_size,
            response_timeout_s=options.response_timeout_s,
            response_first_text_timeout_s=options.response_first_text_timeout_s,
            response_cancel_timeout_s=options.response_cancel_timeout_s,
            pseudonymization_key=options.pseudonymization_key,
            speech_deliveries=options.speech_deliveries,
            context_projector_factory=options.context_projector_factory,
            provider_timing=options.provider_timing,
        )
        return cls(engine=engine, profile=profile)
