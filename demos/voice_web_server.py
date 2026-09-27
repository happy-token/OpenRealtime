"""Browser voice demo: the WebSocket voice-agent server — real ASR, real
TTS, real LLM, talking directly to the official Doubao/DeepSeek APIs by
default. The frontend at the repo root (Next.js) serves itself
independently; this script only owns the WS/control-plane ports.

ASR and TTS both default to the direct Volcengine endpoints
(DoubaoAsrEngine/DoubaoDirectTtsEngine, `DOUBAO_API_KEY`). Set
`VOICEAGENT_TTS_BACKEND=bailian` to use Alibaba Cloud Bailian's direct duplex
CosyVoice/Qwen-Audio-TTS WebSocket (`DASHSCOPE_API_KEY`), or select `bella`
for the company-internal Bella OpenAPI gateway (`API_KEY`).

Falls back to the deterministic no-network defaults (PreloadedAsrEngine,
SilentTtsEngine, EchoLlmClient) when credentials are unset, so the demo
still runs with zero configuration — mirrors demos/basic_ws_server.py's
convention.

With VOICEAGENT_DEMO_TOOLS set, the Brain is a ToolCallingBrain wired to
ClockToolSource and WebSearchToolSource instead of plain ChatBrain — a real
OpenAiCompatibleToolCallingLlmClient (Bella if API_KEY is set, else the
generic VOICEAGENT_LLM_* vars, else EchoToolCallingLlmClient) and ByteWebSearch
(gated on BYTE_WEB_SEARCH_API_KEY or its deprecated WEB_SEARCH_API_KEY alias)
when those credentials are set, otherwise
their deterministic no-network stand-ins — same convention as
demos/basic_ws_server.py.

Without that opt-in, the ordinary ChatBrain keeps the latency-friendly
speculative stream and uses a read-only per-turn grounder: DeepSeek plans
respond/clock/lookup, the clock is frozen once, and Byte search is available
only when a real search key is configured. Search evidence is injected
as untrusted user context, never as authoritative system instructions.

Run:
    uv run python demos/voice_web_server.py [console|dev|start]

Normally launched via `pnpm dev` at the repo root, which starts this
alongside the Next.js frontend.

Endpoint authentication defaults to an explicit loopback development identity.
Production deployments select ``VOICEAGENT_ENDPOINT_AUTH_MODE=static_bearer``
or replace the WebSocket authenticator with their login/session authority;
Client Hello identity fields are never trusted.
"""

from __future__ import annotations

import asyncio
import functools
import io
import json
import logging
import os
import wave
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.voice_session.public_admission import VoiceAdmissionBinding

from server.application.runtime import (
    ApplicationRuntime,
    ApplicationRuntimeConfig,
    build_application_runtime,
)
from server.avatar_assets.composition import (
    AvatarAssetRuntime,
    build_avatar_asset_runtime_from_env,
)
from server.avatar_assets.http_api import AvatarAssetHttpResponse
from server.brain.avatar_persona import AvatarPersonaPromptCatalog, SessionAvatarPersona
from server.brain.base import Brain
from server.brain.chat_brain import ChatBrain
from server.brain.llm_clients import (
    EchoLlmClient,
    EchoToolCallingLlmClient,
    LlmClient,
    ToolCallingLlmClient,
)
from server.brain.plugins.openai_compatible_llm_client import OpenAiCompatibleLlmClient
from server.brain.plugins.openai_compatible_tool_calling_llm_client import (
    OpenAiCompatibleToolCallingLlmClient,
)
from server.brain.realtime_grounding import (
    LlmGroundingPlanner,
    RealtimeGroundingCoordinator,
    TurnGrounder,
)
from server.brain.role_model import role_model_id, role_tool_ids
from server.brain.session_memory import SessionMemory
from server.brain.tool_calling_brain import ToolCallingBrain
from server.cli.harness import run_app
from server.conversation_journal import (
    ConversationItemKind,
    JournalScope,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.endpoint_session.in_memory_session import InMemoryEndpointSession
from server.endpoint_session.registry import EndpointSessionRegistry
from server.knowledge_base.local_catalog import LocalCatalogKnowledgeBase
from server.ledger.event_ledger import EventLedger, LedgerEvent
from server.observability.telemetry import (
    SessionTelemetry,
    TelemetryIdentity,
    redact_attributes,
)
from server.realtime import RealtimeConfirmationController, RealtimeRuntimeFactory
from server.realtime.capabilities import (
    DeterministicSpeechRenderer,
    LegacyAsrCapabilityAdapter,
    LegacyBrainCapabilityAdapter,
    LegacyTtsCapabilityAdapter,
    LegacyTurnManagerCapabilityAdapter,
    LegacyVadCapabilityAdapter,
)
from server.realtime.capabilities.brain_streaming import (
    BrainStreamingAdapter,
    ToolCallingBrainStreamingAdapter,
    VoiceRuntimeBrainStreamingAdapter,
)
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
from server.realtime.cascaded import CascadedRealtimeEngine
from server.realtime.observability import RealtimeTelemetryObserver
from server.realtime.profile.builtin import (
    BuiltinCascadedBindings,
    resolve_builtin_profile,
)
from server.realtime.provider_latency import ProviderLatencyObserver
from server.signals.energy_vad import EnergyVadConfig
from server.signals.plugins.silero_vad import SileroVad
from server.speech.asr import AsrEngine, PreloadedAsrEngine
from server.speech.plugins.bailian_tts import (
    DEFAULT_VOICE as BAILIAN_DEFAULT_VOICE,
)
from server.speech.plugins.bailian_tts import (
    BailianTtsEngine,
)
from server.speech.plugins.doubao_asr import DoubaoAsrEngine
from server.speech.plugins.doubao_tts import DoubaoTtsEngine
from server.speech.plugins.doubao_tts_direct import (
    DEFAULT_VOICE as DOUBAO_DEFAULT_VOICE,
)
from server.speech.plugins.doubao_tts_direct import (
    DoubaoDirectTtsEngine,
)
from server.speech.selectable_tts import SelectableTtsEngine, TtsProviderFactory
from server.speech.tts import SilentTtsEngine, StreamingTtsEngine, TtsSessionConfig
from server.tools.clock_source import ClockToolSource, resolve_timezone
from server.tools.confirmation import BoundToolConfirmationHandler
from server.tools.control import DefaultToolControlHandler
from server.tools.fast_loop import FastToolLoop
from server.tools.knowledge_base_source import KnowledgeBaseToolSource
from server.tools.local_catalog_source import LocalCatalogToolSource
from server.tools.policy_gateway import (
    ConfirmationChannel,
    ConfirmationRejected,
    DefaultToolPolicyGateway,
    ToolExecutor,
    ToolPolicyContext,
)
from server.tools.registry import ToolRegistry
from server.tools.web_search_source import WebSearchToolSource
from server.transport.base import AuthenticatedTransportIdentity
from server.transport.frames import (
    AvatarPersonaConfigFrame,
    ClientConnectionQualityFrame,
    ConfirmationDecisionFrame,
    ConfirmationResolutionFrame,
    PlaybackQualityFrame,
    SessionCapabilitiesFrame,
    ToolConfigFrame,
    TtsConfigAckFrame,
    TtsConfigFrame,
)
from server.transport.plugins.websocket import (
    StaticBearerWebSocketAuthenticator,
    serve,
)
from server.turn_policy.dual_intent import DualIntentClassifier
from server.turn_policy.eot_classifier import EotClassifier
from server.turn_policy.plugins.classifier_eot_evidence_provider import (
    ClassifierEotEvidenceProvider,
)
from server.turn_policy.plugins.fast_complete_fallback_eot_classifier import (
    FastCompleteFallbackEotClassifier,
)
from server.turn_policy.plugins.fireredchat_eot_provider import (
    FireRedChatEotProvider,
    FireRedChatOnnxModel,
)
from server.turn_policy.plugins.hybrid_eot_classifier import HybridEotClassifier
from server.turn_policy.plugins.llm_dual_intent_classifier import LlmDualIntentClassifier
from server.turn_policy.plugins.llm_eot_classifier import (
    EOT_RESPONSE_SCHEMA,
    LlmEotClassifier,
)
from server.turn_policy.plugins.llm_semantic_interruption_classifier import (
    LlmSemanticInterruptionClassifier,
)
from server.turn_policy.policy import TurnPolicy
from server.turn_policy.semantic_interruption import SemanticInterruptionClassifier
from server.voice_session.context import (
    BudgetedConversationContextProjector,
    ConservativeTokenCounter,
    ContextPolicy,
    HybridContextCompressor,
    InMemorySummaryCheckpointStore,
    JsonSummaryNarrativeModel,
    SummaryCheckpointValidator,
)
from server.voice_session.endpoint_bridge import VoiceSessionWebSocketSession
from server.voice_session.models import VoiceSessionIdentity
from server.voice_session.protocol import InputCaptureDiagnostic, InputEpochStarted
from server.web_search.deterministic_web_search import DeterministicWebSearch
from server.web_search.plugins.byte_web_search import ByteWebSearch, resolve_search_api_key
from server.web_search.protocol import WebSearch

logger = logging.getLogger(__name__)

BELLA_BASE_URL = "https://bella-openapi.ke.com/v1"
BELLA_LLM_MODEL = "gpt-5.6-sol"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_LLM_MODEL = "deepseek-v4-flash"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_LLM_MODEL = "gpt-4.1-mini"

_application_runtime: ApplicationRuntime | None = None
_avatar_asset_runtime: AvatarAssetRuntime | None = None

_DEMO_TOOLS_ENV_VAR = "VOICEAGENT_DEMO_TOOLS"

WS_HOST = os.environ.get("VOICEAGENT_WS_HOST", "127.0.0.1")
WS_PORT = int(os.environ.get("VOICEAGENT_WS_PORT", "8765"))


async def _authorize_requested_thread(
    identity: AuthenticatedTransportIdentity,
    thread_id: str,
) -> bool:
    runtime = _application_runtime
    if runtime is None:
        return False
    scope = JournalScope(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        thread_id=thread_id,
    )
    return await runtime.journal.thread_version(scope) > 0


async def _authorize_continuation(
    identity: AuthenticatedTransportIdentity,
    previous_voice_session_id: str,
    thread_id: str,
) -> bool:
    runtime = _application_runtime
    if runtime is None or not await _authorize_requested_thread(identity, thread_id):
        return False
    scope = JournalScope(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        thread_id=thread_id,
    )
    after_sequence = 0
    while True:
        items = await runtime.journal.read(
            scope,
            after_sequence=after_sequence,
            limit=1000,
        )
        if not items:
            return False
        if any(
            item.context.voice_session_id == previous_voice_session_id
            for item in items
        ):
            return True
        after_sequence = items[-1].sequence


def _build_endpoint_security():
    mode = os.environ.get("VOICEAGENT_ENDPOINT_AUTH_MODE", "development").strip().lower()
    if mode == "development":
        identity = AuthenticatedTransportIdentity(
            tenant_id=os.environ.get("VOICEAGENT_TENANT_ID", "local"),
            user_id=os.environ.get("VOICEAGENT_USER_ID", "local-user"),
            device_id=os.environ.get("VOICEAGENT_DEVICE_ID", "browser"),
        )
        registry = EndpointSessionRegistry(
            supported_protocol_versions=(2,),
            development_identity=identity,
            thread_authorizer=_authorize_requested_thread,
            continuation_authorizer=_authorize_continuation,
        )
        return registry, functools.partial(serve, authenticator=None)
    if mode == "static_bearer":
        required = {
            "VOICEAGENT_ENDPOINT_AUTH_TOKEN": os.environ.get(
                "VOICEAGENT_ENDPOINT_AUTH_TOKEN"
            ),
            "VOICEAGENT_TENANT_ID": os.environ.get("VOICEAGENT_TENANT_ID"),
            "VOICEAGENT_USER_ID": os.environ.get("VOICEAGENT_USER_ID"),
            "VOICEAGENT_DEVICE_ID": os.environ.get("VOICEAGENT_DEVICE_ID"),
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise RuntimeError(
                "static_bearer endpoint authentication requires: "
                + ", ".join(missing)
            )
        identity = AuthenticatedTransportIdentity(
            tenant_id=required["VOICEAGENT_TENANT_ID"] or "",
            user_id=required["VOICEAGENT_USER_ID"] or "",
            device_id=required["VOICEAGENT_DEVICE_ID"] or "",
        )
        authenticator = StaticBearerWebSocketAuthenticator(
            token=required["VOICEAGENT_ENDPOINT_AUTH_TOKEN"] or "",
            identity=identity,
        )
        registry = EndpointSessionRegistry(
            supported_protocol_versions=(2,),
            thread_authorizer=_authorize_requested_thread,
            continuation_authorizer=_authorize_continuation,
        )
        return registry, functools.partial(serve, authenticator=authenticator)
    if mode == "public_ticket":
        from server.voice_session.public_admission import (
            PublicVoiceTicketAuthenticator,
            admit_fresh_public_session,
        )

        registry = EndpointSessionRegistry(
            supported_protocol_versions=(2,),
            thread_authorizer=_authorize_requested_thread,
            continuation_authorizer=_authorize_continuation,
            fresh_session_admitter=admit_fresh_public_session,
        )
        return registry, functools.partial(
            serve, authenticator=PublicVoiceTicketAuthenticator(),
        )
    raise RuntimeError(
        "VOICEAGENT_ENDPOINT_AUTH_MODE must be development, static_bearer, or public_ticket"
    )


_session_registry, _websocket_serve = _build_endpoint_security()


def _bella_api_key() -> str | None:
    return os.environ.get("API_KEY")


def _deepseek_api_key() -> str | None:
    return os.environ.get("DEEPSEEK_API_KEY")


def _llm_credentials_configured() -> bool:
    return bool(os.environ.get("VOICEAGENT_LLM_API_KEY") or _deepseek_api_key()
                or os.environ.get("OPENAI_API_KEY") or _bella_api_key())


def _deepseek_disable_thinking() -> bool:
    configured = os.environ.get("VOICEAGENT_LLM_DISABLE_THINKING")
    if configured is None:
        return True
    return configured.strip().lower() in ("1", "true", "yes")


def _bound_key(binding: VoiceAdmissionBinding, provider: str, source: str, capability: str) -> str:
    instance_key = binding.instance_credentials.get(capability)
    if instance_key:
        return instance_key
    env_name = {
        "doubao": "DOUBAO_API_KEY", "dashscope": "DASHSCOPE_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY", "openai": "OPENAI_API_KEY",
        "custom": "VOICEAGENT_LLM_API_KEY",
        "bella": "API_KEY",
    }[provider]
    key = binding.credentials.get(provider) if source == "personal" else os.environ.get(env_name)
    if not key:
        raise RuntimeError(f"{provider} credential is not available for this session")
    return key


def _build_asr_engine(binding: VoiceAdmissionBinding | None = None) -> AsrEngine:
    if binding is not None:
        if binding.asr_provider not in {"doubao", "dashscope"}:
            raise ValueError("unsupported ASR provider")
        key = _bound_key(binding, binding.asr_provider, binding.asr_source, "asr")
        if binding.asr_provider == "dashscope":
            from server.speech.plugins.bailian_asr import BailianAsrEngine
            return BailianAsrEngine(api_key=key,
                base_url=binding.instance_base_urls.get("asr"),
                model=binding.instance_models.get("asr") or "qwen3-asr-flash-realtime")
        return DoubaoAsrEngine(api_key=key)
    backend = os.environ.get("VOICEAGENT_ASR_BACKEND", "doubao-direct")
    if backend != "doubao-direct":
        raise ValueError("unsupported ASR backend")
    if os.environ.get("DOUBAO_API_KEY"):
        return DoubaoAsrEngine()
    logger.warning("DOUBAO_API_KEY not set — using PreloadedAsrEngine (no real ASR)")
    return PreloadedAsrEngine("")


def _build_tts_engine() -> StreamingTtsEngine:
    backend = os.environ.get("VOICEAGENT_TTS_BACKEND", "doubao-direct")
    if backend == "bailian":
        if os.environ.get("DASHSCOPE_API_KEY"):
            return BailianTtsEngine()
        logger.warning("DASHSCOPE_API_KEY not set — using SilentTtsEngine (no real TTS)")
        return SilentTtsEngine()
    if backend == "bella":
        if _bella_api_key():
            return DoubaoTtsEngine()
        logger.warning("API_KEY not set — using SilentTtsEngine (no real TTS)")
        return SilentTtsEngine()
    if os.environ.get("DOUBAO_API_KEY"):
        return DoubaoDirectTtsEngine()
    logger.warning("DOUBAO_API_KEY not set — using SilentTtsEngine (no real TTS)")
    return SilentTtsEngine()


def _bailian_tts_instruction(dialect: str) -> str | None:
    dialect_names = {
        "anhui": "安徽话",
        "cantonese": "广东话",
        "dongbei": "东北话",
        "henan": "河南话",
        "hunan": "湖南话",
        "shaanxi": "陕西话",
        "shandong": "山东话",
        "sichuan": "四川话",
    }
    return f"请用{dialect_names[dialect]}表达。" if dialect else None


def _build_doubao_session_tts(config: TtsSessionConfig) -> DoubaoDirectTtsEngine:
    tts = DoubaoDirectTtsEngine(
        voice=config.voice,
        speech_rate=config.speech_rate,
    )
    tts.configure(config)
    return tts


def _build_session_tts_engine(
    binding: VoiceAdmissionBinding | None = None,
) -> StreamingTtsEngine:
    if binding is not None:
        key = _bound_key(binding, binding.tts_provider, binding.tts_source, "tts")
        if binding.tts_provider == "dashscope":
            factories: dict[str, TtsProviderFactory] = {
                "bailian": lambda config: BailianTtsEngine(
                    api_key=key,
                    voice=(os.environ.get("BAILIAN_TTS_VOICE", BAILIAN_DEFAULT_VOICE)
                           if config.voice == "__active_bailian_clone__" else config.voice),
                    speech_rate=config.speech_rate,
                    instruction=_bailian_tts_instruction(config.dialect),
                ),
            }
            return SelectableTtsEngine(
                factories=factories, provider="bailian",
                config=TtsSessionConfig(
                    voice=os.environ.get("BAILIAN_TTS_VOICE", BAILIAN_DEFAULT_VOICE),
                ),
            )
        factories = {
            "doubao": lambda config: _build_bound_doubao_tts(config, key),
        }
        return SelectableTtsEngine(
            factories=factories, provider="doubao",
            config=TtsSessionConfig(voice=DOUBAO_DEFAULT_VOICE),
        )
    factories: dict[str, TtsProviderFactory] = {}
    if os.environ.get("DASHSCOPE_API_KEY"):
        factories["bailian"] = lambda config: BailianTtsEngine(
            voice=(
                os.environ.get("BAILIAN_TTS_VOICE", BAILIAN_DEFAULT_VOICE)
                if config.voice == "__active_bailian_clone__"
                else config.voice
            ),
            speech_rate=config.speech_rate,
            instruction=_bailian_tts_instruction(config.dialect),
        )
    if os.environ.get("DOUBAO_API_KEY"):
        factories["doubao"] = _build_doubao_session_tts
    if not factories:
        return _build_tts_engine()

    configured_backend = os.environ.get("VOICEAGENT_TTS_BACKEND", "doubao-direct")
    configured_provider = "bailian" if configured_backend == "bailian" else "doubao"
    provider = configured_provider if configured_provider in factories else next(iter(factories))
    config = TtsSessionConfig(
        voice=(
            os.environ.get("BAILIAN_TTS_VOICE", BAILIAN_DEFAULT_VOICE)
            if provider == "bailian"
            else DOUBAO_DEFAULT_VOICE
        )
    )
    return SelectableTtsEngine(factories=factories, provider=provider, config=config)


def _build_bound_doubao_tts(config: TtsSessionConfig, key: str) -> DoubaoDirectTtsEngine:
    tts = DoubaoDirectTtsEngine(
        api_key=key, voice=config.voice, speech_rate=config.speech_rate,
    )
    tts.configure(config)
    return tts


def _supports_tts_preview(tts: object) -> bool:
    return isinstance(
        tts,
        (BailianTtsEngine, DoubaoDirectTtsEngine, SelectableTtsEngine),
    )


async def _preview_voice(
    provider: str,
    voice: str,
    speech_rate: int,
    dialect: str,
) -> tuple[bytes, str]:
    if provider == "bailian":
        if not os.environ.get("DASHSCOPE_API_KEY"):
            raise RuntimeError("Bailian TTS is not configured")
        resolved_voice = (
            os.environ.get("BAILIAN_TTS_VOICE")
            if voice == "__active_bailian_clone__"
            else voice
        )
        tts = BailianTtsEngine(
            voice=resolved_voice,
            speech_rate=speech_rate,
            instruction=_bailian_tts_instruction(dialect),
        )
    elif provider == "doubao":
        if not os.environ.get("DOUBAO_API_KEY"):
            raise RuntimeError("Doubao TTS is not configured")
        tts = DoubaoDirectTtsEngine(voice=voice, speech_rate=speech_rate)
        try:
            tts.configure(
                TtsSessionConfig(voice=voice, speech_rate=speech_rate, dialect=dialect)
            )
        except ValueError as error:
            raise ValueError("unsupported voice or dialect") from error
    else:
        raise ValueError("unsupported TTS provider")
    try:
        audio = await tts.synthesize(
            "你好，这是音色预览。很高兴与你见面，希望你喜欢这个声音。"
        )
    finally:
        await tts.close()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(audio.sample_rate_hz)
        wav_file.writeframes(audio.pcm16)
    return output.getvalue(), "audio/wav"


def _build_llm_client(
    telemetry: SessionTelemetry | None = None,
    binding: VoiceAdmissionBinding | None = None,
) -> LlmClient:
    if binding is not None:
        key = _bound_key(binding, binding.llm_provider, binding.llm_source, "llm")
        if binding.llm_provider == "deepseek":
            return OpenAiCompatibleLlmClient(
                api_key=key,
                base_url=binding.instance_base_urls.get("llm") or DEEPSEEK_BASE_URL,
                model=binding.instance_models.get("llm") or ("deepseek-chat" if binding.instance_ids.get("llm")
                    else os.environ.get("DEEPSEEK_LLM_MODEL", DEEPSEEK_LLM_MODEL)),
                disable_thinking=_deepseek_disable_thinking(),
                # Instance tests exercise Chat Completions streaming; keep the
                # admitted runtime on that same protocol. Legacy env-backed
                # sessions retain their existing configurable API style.
                api_style=("chat_completions" if binding.instance_ids.get("llm")
                           else _llm_api_style(default="responses")),
                telemetry=telemetry, provider_name="deepseek",
                instance_id=binding.instance_ids.get("llm"),
                config_version=binding.instance_versions.get("llm"),
            )
        if binding.llm_provider == "openai":
            return OpenAiCompatibleLlmClient(
                api_key=key, base_url=binding.instance_base_urls.get("llm") or OPENAI_BASE_URL,
                model=binding.instance_models.get("llm") or (OPENAI_LLM_MODEL if binding.instance_ids.get("llm")
                    else os.environ.get("OPENAI_LLM_MODEL", OPENAI_LLM_MODEL)),
                api_style="chat_completions", telemetry=telemetry,
                provider_name="openai",
                instance_id=binding.instance_ids.get("llm"),
                config_version=binding.instance_versions.get("llm"),
            )
        if binding.llm_provider == "bella":
            return OpenAiCompatibleLlmClient(
                api_key=key, base_url=BELLA_BASE_URL, model=BELLA_LLM_MODEL,
                telemetry=telemetry, provider_name="bella",
            )
        return OpenAiCompatibleLlmClient(
            api_key=key, api_style=_llm_api_style(default="chat_completions"),
            telemetry=telemetry,
        )
    if os.environ.get("VOICEAGENT_LLM_API_KEY"):
        return OpenAiCompatibleLlmClient(
            api_style=_llm_api_style(default="chat_completions"),
            telemetry=telemetry,
        )
    deepseek_api_key = _deepseek_api_key()
    if deepseek_api_key:
        return OpenAiCompatibleLlmClient(
            api_key=deepseek_api_key,
            base_url=os.environ.get("VOICEAGENT_LLM_BASE_URL", DEEPSEEK_BASE_URL),
            model=os.environ.get("VOICEAGENT_LLM_MODEL", DEEPSEEK_LLM_MODEL),
            disable_thinking=_deepseek_disable_thinking(),
            api_style=_llm_api_style(default="responses"),
            telemetry=telemetry,
            provider_name="deepseek",
        )
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        return OpenAiCompatibleLlmClient(
            api_key=openai_api_key, base_url=OPENAI_BASE_URL,
            model=os.environ.get("OPENAI_LLM_MODEL", OPENAI_LLM_MODEL),
            api_style="chat_completions", telemetry=telemetry,
            provider_name="openai",
        )
    api_key = _bella_api_key()
    if api_key:
        return OpenAiCompatibleLlmClient(
            api_key=api_key,
            base_url=BELLA_BASE_URL,
            model=BELLA_LLM_MODEL,
            telemetry=telemetry,
            provider_name="bella",
        )
    logger.warning("No LLM credentials set — using EchoLlmClient (no real LLM call)")
    return EchoLlmClient()


def _llm_api_style(*, default: str) -> str:
    api_style = os.environ.get("VOICEAGENT_LLM_API_STYLE", default)
    if api_style not in {"chat_completions", "responses"}:
        raise ValueError(
            "VOICEAGENT_LLM_API_STYLE must be chat_completions or responses"
        )
    return api_style


def _build_tool_calling_llm_client(
    telemetry: SessionTelemetry | None = None,
    binding: VoiceAdmissionBinding | None = None,
) -> ToolCallingLlmClient:
    if binding is not None:
        key = _bound_key(binding, binding.llm_provider, binding.llm_source, "llm")
        if binding.llm_provider == "deepseek":
            return OpenAiCompatibleToolCallingLlmClient(
                api_key=key, base_url=binding.instance_base_urls.get("llm") or DEEPSEEK_BASE_URL,
                model=binding.instance_models.get("llm") or ("deepseek-chat" if binding.instance_ids.get("llm")
                    else os.environ.get("DEEPSEEK_LLM_MODEL", DEEPSEEK_LLM_MODEL)),
                disable_thinking=_deepseek_disable_thinking(), telemetry=telemetry,
                provider_name="deepseek",
            )
        if binding.llm_provider == "openai":
            return OpenAiCompatibleToolCallingLlmClient(
                api_key=key, base_url=binding.instance_base_urls.get("llm") or OPENAI_BASE_URL,
                model=binding.instance_models.get("llm") or (OPENAI_LLM_MODEL if binding.instance_ids.get("llm")
                    else os.environ.get("OPENAI_LLM_MODEL", OPENAI_LLM_MODEL)),
                telemetry=telemetry, provider_name="openai",
            )
        if binding.llm_provider == "bella":
            return OpenAiCompatibleToolCallingLlmClient(
                api_key=key, base_url=BELLA_BASE_URL, model=BELLA_LLM_MODEL,
                telemetry=telemetry, provider_name="bella",
            )
        return OpenAiCompatibleToolCallingLlmClient(api_key=key, telemetry=telemetry)
    if os.environ.get("VOICEAGENT_LLM_API_KEY"):
        return OpenAiCompatibleToolCallingLlmClient(telemetry=telemetry)
    deepseek_api_key = _deepseek_api_key()
    if deepseek_api_key:
        return OpenAiCompatibleToolCallingLlmClient(
            api_key=deepseek_api_key,
            base_url=os.environ.get("VOICEAGENT_LLM_BASE_URL", DEEPSEEK_BASE_URL),
            model=os.environ.get("VOICEAGENT_LLM_MODEL", DEEPSEEK_LLM_MODEL),
            disable_thinking=_deepseek_disable_thinking(),
            telemetry=telemetry,
            provider_name="deepseek",
        )
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        return OpenAiCompatibleToolCallingLlmClient(
            api_key=openai_api_key, base_url=OPENAI_BASE_URL,
            model=os.environ.get("OPENAI_LLM_MODEL", OPENAI_LLM_MODEL),
            telemetry=telemetry, provider_name="openai",
        )
    api_key = _bella_api_key()
    if api_key:
        return OpenAiCompatibleToolCallingLlmClient(
            api_key=api_key,
            base_url=BELLA_BASE_URL,
            model=BELLA_LLM_MODEL,
            telemetry=telemetry,
            provider_name="bella",
        )
    logger.warning("No LLM credentials set — using EchoToolCallingLlmClient (no real LLM call)")
    return EchoToolCallingLlmClient()


def _build_model_context_projector(llm_client: LlmClient):
    policy_version = os.environ.get("VOICEAGENT_CONTEXT_POLICY_VERSION", "phase1-v1")
    counter = ConservativeTokenCounter()
    validator = SummaryCheckpointValidator()
    return BudgetedConversationContextProjector(
        policy=ContextPolicy(
            policy_version=policy_version,
            context_window_tokens=int(
                os.environ.get("VOICEAGENT_CONTEXT_WINDOW_TOKENS", "65536")
            ),
            max_output_tokens=int(
                os.environ.get("VOICEAGENT_CONTEXT_MAX_OUTPUT_TOKENS", "2048")
            ),
            tool_schema_tokens=int(
                os.environ.get("VOICEAGENT_CONTEXT_TOOL_SCHEMA_TOKENS", "4096")
            ),
            governing_instruction_tokens=int(
                os.environ.get("VOICEAGENT_CONTEXT_INSTRUCTION_TOKENS", "2048")
            ),
            current_input_tokens=int(
                os.environ.get("VOICEAGENT_CONTEXT_CURRENT_INPUT_TOKENS", "4096")
            ),
            safety_margin_tokens=int(
                os.environ.get("VOICEAGENT_CONTEXT_SAFETY_MARGIN_TOKENS", "4096")
            ),
            compression_trigger_ratio=float(
                os.environ.get("VOICEAGENT_CONTEXT_COMPRESSION_TRIGGER", "0.7")
            ),
        ),
        token_counter=counter,
        checkpoint_store=InMemorySummaryCheckpointStore(validator),
        checkpoint_validator=validator,
        compressor=HybridContextCompressor(
            model=JsonSummaryNarrativeModel(llm_client),
            compressor_model=os.environ.get(
                "VOICEAGENT_CONTEXT_COMPRESSOR_MODEL",
                os.environ.get("VOICEAGENT_LLM_MODEL", "default-chat-model"),
            ),
            compressor_version="1",
            prompt_version="1",
            compression_policy_version=policy_version,
            token_counter=counter,
        ),
    )


def _build_web_search(telemetry: SessionTelemetry | None = None) -> WebSearch:
    search_api_key = resolve_search_api_key()
    if search_api_key:
        return ByteWebSearch(api_key=search_api_key, telemetry=telemetry)
    logger.warning(
        "BYTE_WEB_SEARCH_API_KEY not set — using DeterministicWebSearch (no real web search)"
    )
    return DeterministicWebSearch()


def _build_tool_registry(
    telemetry: SessionTelemetry | None = None,
    knowledge_base: LocalCatalogKnowledgeBase | None = None,
    custom_tools: LocalCatalogToolSource | None = None,
    *,
    include_builtins: bool = True,
) -> ToolRegistry:
    return ToolRegistry(
        ([ClockToolSource(), WebSearchToolSource(_build_web_search(telemetry))] if include_builtins else [])
        + ([KnowledgeBaseToolSource(knowledge_base)] if knowledge_base else [])
        + ([custom_tools] if custom_tools else [])
    )


def _build_realtime_grounder(
    llm_client: LlmClient,
    telemetry: SessionTelemetry | None = None,
) -> TurnGrounder | None:
    if not _llm_credentials_configured():
        return None
    search_api_key = resolve_search_api_key()
    web_search = (
        ByteWebSearch(api_key=search_api_key, telemetry=telemetry)
        if search_api_key
        else None
    )
    timezone = resolve_timezone()
    return RealtimeGroundingCoordinator(
        planner=LlmGroundingPlanner(
            llm_client,
            reference_timezone=timezone,
        ),
        web_search=web_search,
        default_timezone=timezone,
        planner_timeout_s=float(
            os.environ.get("VOICEAGENT_GROUNDING_PLANNER_TIMEOUT_S", "1.5")
        ),
        search_timeout_s=float(
            os.environ.get("VOICEAGENT_GROUNDING_SEARCH_TIMEOUT_S", "3.0")
        ),
        total_timeout_s=float(
            os.environ.get("VOICEAGENT_GROUNDING_TOTAL_TIMEOUT_S", "5.0")
        ),
    )


def _build_brain(
    llm_client: LlmClient,
    *,
    tool_registry: ToolRegistry | None = None,
    telemetry: SessionTelemetry | None = None,
    avatar_persona: SessionAvatarPersona | None = None,
    session_memory: SessionMemory | None = None,
    tool_llm_client: ToolCallingLlmClient | None = None,
    binding: VoiceAdmissionBinding | None = None,
) -> Brain:
    def prompt_transform(prompt: str) -> str:
        if avatar_persona is not None:
            prompt = avatar_persona.apply(prompt)
        return session_memory.apply(prompt) if session_memory is not None else prompt
    if tool_registry is None and not os.environ.get(_DEMO_TOOLS_ENV_VAR):
        return ChatBrain(
            llm_client,
            system_prompt_transform=prompt_transform,
            grounder=_build_realtime_grounder(llm_client, telemetry),
        )
    registry = tool_registry or _build_tool_registry(telemetry)
    return ToolCallingBrain(
        tool_llm_client or _build_tool_calling_llm_client(telemetry, binding),
        registry,
        system_prompt_transform=prompt_transform,
    )


def _build_session_avatar_persona() -> SessionAvatarPersona:
    project_root = Path(__file__).resolve().parents[1]
    persona_root = Path(
        os.environ.get(
            "VOICEAGENT_PERSONA_ROOT",
            project_root / "config" / "personas",
        )
    )
    links_path = Path(
        os.environ.get(
            "VOICEAGENT_AVATAR_PERSONA_LINKS",
            project_root / "config" / "avatar-persona-links.json",
        )
    )
    return SessionAvatarPersona(
        AvatarPersonaPromptCatalog(
            persona_root=persona_root,
            links_path=links_path,
        )
    )


def _build_vad() -> SileroVad:
    silence_ms = float(os.environ.get("VOICEAGENT_VAD_SILENCE_MS", "256"))
    onset_ms = float(os.environ.get("VOICEAGENT_VAD_ONSET_MS", "96"))
    threshold = float(os.environ.get("VOICEAGENT_VAD_THRESHOLD", "0.6"))
    return SileroVad(
        EnergyVadConfig(
            silence_duration_ms=silence_ms,
            speech_onset_duration_ms=onset_ms,
        ),
        threshold=threshold,
    )


def _build_eot_classifier(llm_client: LlmClient) -> EotClassifier | None:
    llm_classifier = None
    if _llm_credentials_configured():
        eot_llm_client = _build_eot_llm_client(llm_client)
        llm_classifier = LlmEotClassifier(
            eot_llm_client,
            source=(
                "deepseek_responses"
                if getattr(eot_llm_client, "_api_style", None) == "responses"
                else "llm"
            ),
        )
    model_dir = os.environ.get("VOICEAGENT_EOT_FIRERED_MODEL_DIR")
    if not model_dir:
        return llm_classifier

    firered_provider = _load_firered_provider(
        model_dir,
        os.environ.get("VOICEAGENT_EOT_FIRERED_LANGUAGE", "chinese"),
        int(os.environ.get("VOICEAGENT_EOT_FIRERED_INTRA_OP_THREADS", "2")),
        float(os.environ.get("VOICEAGENT_EOT_FIRERED_THRESHOLD", "0.5")),
        int(os.environ.get("VOICEAGENT_EOT_FIRERED_MAX_CONCURRENCY", "2")),
    )
    strategy = os.environ.get(
        "VOICEAGENT_EOT_FIRERED_STRATEGY",
        "fast_complete_fallback",
    )
    if strategy == "fast_complete_fallback" and llm_classifier is not None:
        return FastCompleteFallbackEotClassifier(
            fast_provider=firered_provider,
            fallback_provider=ClassifierEotEvidenceProvider(llm_classifier),
            fast_complete_threshold=float(
                os.environ.get(
                    "VOICEAGENT_EOT_FIRERED_FAST_COMPLETE_THRESHOLD",
                    "0.5",
                )
            ),
        )
    if strategy == "fast_complete_fallback":
        logger.warning(
            "FireRed fast-complete fallback requested without LLM credentials; "
            "using FireRed evidence only"
        )
        return HybridEotClassifier(providers=(firered_provider,))
    providers = (
        (ClassifierEotEvidenceProvider(llm_classifier), firered_provider)
        if llm_classifier is not None
        else (firered_provider,)
    )
    return HybridEotClassifier(
        providers=providers,
        strategy=strategy,
    )


@functools.lru_cache(maxsize=4)
def _load_firered_model(
    model_dir: str,
    language: str,
    intra_op_threads: int,
) -> FireRedChatOnnxModel:
    """Load each ONNX model once and share it across voice conversations."""

    return FireRedChatOnnxModel(
        model_dir,
        language=language,
        intra_op_threads=intra_op_threads,
    )


@functools.lru_cache(maxsize=8)
def _load_firered_provider(
    model_dir: str,
    language: str,
    intra_op_threads: int,
    threshold: float,
    max_concurrency: int,
) -> FireRedChatEotProvider:
    """Share one model and concurrency budget across all voice conversations."""

    return FireRedChatEotProvider(
        _load_firered_model(model_dir, language, intra_op_threads),
        threshold=threshold,
        max_concurrency=max_concurrency,
    )


def _build_eot_llm_client(default_client: LlmClient) -> LlmClient:
    """Select Responses only where explicitly supported; keep Brain unchanged."""

    configured_style = os.environ.get("VOICEAGENT_EOT_LLM_API_STYLE")
    api_style = configured_style or (
        "responses" if _deepseek_api_key() else "chat_completions"
    )
    if api_style not in {"chat_completions", "responses"}:
        raise ValueError(
            "VOICEAGENT_EOT_LLM_API_STYLE must be chat_completions or responses"
        )
    if api_style == "chat_completions":
        return default_client

    api_key = os.environ.get("VOICEAGENT_LLM_API_KEY") or _deepseek_api_key()
    if not api_key:
        logger.warning(
            "Responses EOT requested without a compatible API key; using the default LLM client"
        )
        return default_client
    return OpenAiCompatibleLlmClient(
        api_key=api_key,
        base_url=os.environ.get("VOICEAGENT_LLM_BASE_URL", DEEPSEEK_BASE_URL),
        model=os.environ.get("VOICEAGENT_LLM_MODEL", DEEPSEEK_LLM_MODEL),
        disable_thinking=_deepseek_disable_thinking(),
        api_style="responses",
        response_schema=EOT_RESPONSE_SCHEMA,
        response_schema_name="semantic_eot",
        timeout_s=float(os.environ.get("VOICEAGENT_EOT_LLM_TIMEOUT_MS", "5000"))
        / 1000,
        telemetry=getattr(default_client, "_telemetry", None),
        provider_name="deepseek",
    )


def _build_dual_intent_classifier(llm_client: LlmClient) -> DualIntentClassifier | None:
    if _llm_credentials_configured():
        return LlmDualIntentClassifier(llm_client)
    return None


def _build_semantic_interruption_classifier(
    llm_client: LlmClient,
) -> SemanticInterruptionClassifier | None:
    if _llm_credentials_configured():
        return LlmSemanticInterruptionClassifier(llm_client)
    return None


def _speaking_ms_per_char() -> float:
    return float(os.environ.get("VOICEAGENT_SPEAKING_MS_PER_CHAR", "180.0"))


async def _log_ledger_event(session_id: str, event: LedgerEvent) -> None:
    logger.info(
        "session=%s event=%s generation=%s payload=%s",
        session_id,
        event.name,
        event.generation,
        redact_attributes(event.payload),
    )


def _build_realtime_session(session: InMemoryEndpointSession) -> VoiceSessionWebSocketSession:
    """Assemble the new stateful runtime behind the existing browser protocol."""

    if _application_runtime is None:
        raise RuntimeError("application runtime has not started")
    identity = _build_conversation_identity_from_session(session)
    context = InteractionContext(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        device_id=identity.device_id,
        voice_session_id=identity.voice_session_id,
        thread_id=identity.thread_id,
        turn_id="turn-1",
        generation=1,
    )
    telemetry = _application_runtime.telemetry.bind(
        TelemetryIdentity(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            device_id=identity.device_id,
            voice_session_id=identity.voice_session_id,
            thread_id=identity.thread_id,
        )
    )
    ledger = EventLedger()
    ledger.subscribe(functools.partial(_log_ledger_event, session.session_id))
    ledger.subscribe(telemetry.observe_ledger)
    binding = session.authenticated_identity.admission if session.authenticated_identity else None
    if os.environ.get("VOICEAGENT_ENDPOINT_AUTH_MODE") == "public_ticket" and binding is None:
        raise RuntimeError("public voice requires a verified admission")
    tts = _build_session_tts_engine(binding)
    avatar_persona = _build_session_avatar_persona()
    session_memory = SessionMemory(identity.user_id)
    knowledge_base = LocalCatalogKnowledgeBase(identity.user_id) if os.environ.get(_DEMO_TOOLS_ENV_VAR) or binding is not None else None
    custom_tools = LocalCatalogToolSource(public_only=binding is not None, user_id=identity.user_id) if os.environ.get(_DEMO_TOOLS_ENV_VAR) or binding is not None else None
    tool_registry = (
        _build_tool_registry(telemetry, knowledge_base, custom_tools, include_builtins=binding is None)
        if (os.environ.get(_DEMO_TOOLS_ENV_VAR) and binding is None) or binding is not None
        else None
    )
    if tool_registry is not None:
        tool_registry.select_tools([])
    tool_control_handler_factory = None
    confirmation_controller = None
    confirmation_authority = None
    if tool_registry is not None:
        gateway = DefaultToolPolicyGateway(
            tool_registry,
            authorization_store=(_application_runtime.persistence.tool_authorizations),
        )

        tool_executor = ToolExecutor(tool_registry, gateway)

        def tool_control_handler_factory() -> DefaultToolControlHandler:
            return DefaultToolControlHandler(
                loop=FastToolLoop(
                    gateway=gateway,
                    executor=tool_executor,
                    journal=_application_runtime.journal,
                    telemetry=telemetry,
                ),
                policy_context=ToolPolicyContext(),
            )

        confirmation_controller = RealtimeConfirmationController(
            context=context,
            conversations=_application_runtime.active_realtime_conversations,
            handler=BoundToolConfirmationHandler(
                gateway=gateway,
                executor=tool_executor,
                journal=_application_runtime.journal,
            ),
            channel=ConfirmationChannel.VOICE,
        )
        confirmation_authority = gateway

    realtime_engine = os.environ.get("VOICEAGENT_REALTIME_ENGINE", "cascaded")
    profile = None
    if realtime_engine == "native":
        raise ValueError(
            "Phase 1 production only supports the cascaded engine; "
            "Native Realtime remains experimental"
        )
    elif realtime_engine == "cascaded":
        asr = _build_asr_engine(binding)
        llm_client = _build_llm_client(telemetry, binding)
        tool_llm_client = _build_tool_calling_llm_client(telemetry, binding) if tool_registry is not None else None
        semantic_interruption_classifier = (
            _build_semantic_interruption_classifier(llm_client)
        )
        response_prefetcher = None
        tts_capability_engine = tts
        if tool_registry is None:
            base_streaming_brain = BrainStreamingAdapter(
                _build_brain(
                    llm_client,
                    telemetry=telemetry,
                    avatar_persona=avatar_persona,
                    session_memory=session_memory,
                    binding=binding,
                )
            )
            if getattr(tts, "synthesize_duplex", None) is not None:
                speculative_speech = SpeculativeSpeechPipeline(
                    brain=base_streaming_brain,
                    tts=tts,
                )
                streaming_brain = speculative_speech
                tts_capability_engine = speculative_speech
            else:
                streaming_brain = SpeculativeStreamingBrain(base_streaming_brain)
            response_prefetcher = streaming_brain
        else:
            tool_brain = _build_brain(
                llm_client,
                tool_registry=tool_registry,
                telemetry=telemetry,
                avatar_persona=avatar_persona,
                session_memory=session_memory,
                tool_llm_client=tool_llm_client,
                binding=binding,
            )
            assert isinstance(tool_brain, ToolCallingBrain)
            speculative_chat = SpeculativeStreamingBrain(
                BrainStreamingAdapter(
                    ChatBrain(
                        llm_client,
                        system_prompt_transform=lambda prompt: session_memory.apply(avatar_persona.apply(prompt)),
                    )
                )
            )
            streaming_brain = VoiceRuntimeBrainStreamingAdapter(
                chat=speculative_chat,
                tools=ToolCallingBrainStreamingAdapter(tool_brain),
                slow_tool_ack_delay_s=float(
                    os.environ.get("VOICEAGENT_SLOW_TOOL_ACK_DELAY_MS", "500")
                )
                / 1000,
            )
            response_prefetcher = streaming_brain
        vad_provider = LegacyVadCapabilityAdapter(_build_vad)
        asr_provider = LegacyAsrCapabilityAdapter(asr)
        turn_manager_provider = LegacyTurnManagerCapabilityAdapter(
            TurnPolicy,
            dual_intent_classifier=_build_dual_intent_classifier(llm_client),
            semantic_interruption_classifier=semantic_interruption_classifier,
            semantic_interruption_partial_chars=int(
                os.environ.get("VOICEAGENT_SEMANTIC_INTERRUPTION_PARTIAL_CHARS", "24")
            ),
            semantic_interruption_idle_ms=float(
                os.environ.get("VOICEAGENT_SEMANTIC_INTERRUPTION_IDLE_MS", "320")
            ),
            semantic_interruption_threshold=float(
                os.environ.get("VOICEAGENT_SEMANTIC_INTERRUPTION_THRESHOLD", "0.8")
            ),
            semantic_interruption_timeout_ms=float(
                os.environ.get("VOICEAGENT_SEMANTIC_INTERRUPTION_TIMEOUT_MS", "800")
            ),
            eot_classifier=(None if binding is not None else _build_eot_classifier(llm_client)),
            classifier_timeout_ms=float(
                os.environ.get("VOICEAGENT_EOT_LLM_TIMEOUT_MS", "5000")
            ),
            asr_idle_stop_ms=float(
                os.environ.get("VOICEAGENT_EOT_ASR_IDLE_MS", "1000")
            ),
            late_asr_recovery_ms=float(
                os.environ.get("VOICEAGENT_LATE_ASR_RECOVERY_MS", "2000")
            ),
            incomplete_timeout_ms=float(
                os.environ.get("VOICEAGENT_EOT_INCOMPLETE_TIMEOUT_MS", "5000")
            ),
            uncertain_wait_ms=float(
                os.environ.get("VOICEAGENT_EOT_UNCERTAIN_WAIT_MS", "300")
            ),
            history_max_messages=int(
                os.environ.get("VOICEAGENT_EOT_HISTORY_MESSAGES", "8")
            ),
            history_max_chars=int(
                os.environ.get("VOICEAGENT_EOT_HISTORY_CHARS", "4000")
            ),
            response_prefetcher=response_prefetcher,
        )
        brain_provider = LegacyBrainCapabilityAdapter(streaming_brain)
        speech_renderer = DeterministicSpeechRenderer()
        tts_provider = LegacyTtsCapabilityAdapter(
            tts_capability_engine,
            cancel_timeout_s=float(
                os.environ.get("VOICEAGENT_TTS_CANCEL_TIMEOUT_MS", "300")
            )
            / 1000,
        )
        profile = resolve_builtin_profile(
            BuiltinCascadedBindings(
                vad=vad_provider,
                asr=asr_provider,
                turn_manager=turn_manager_provider,
                brain=brain_provider,
                speech_renderer=speech_renderer,
                tts=tts_provider,
            ),
            profile_path=(
                os.environ.get("VOICEAGENT_REALTIME_PROFILE_PATH") or None
            ),
        )
        engine = CascadedRealtimeEngine(
            vad=vad_provider,
            asr=asr_provider,
            turn_manager=turn_manager_provider,
            brain=brain_provider,
            speech_renderer=speech_renderer,
            tts=tts_provider,
            speech_deliveries=_application_runtime.speech_deliveries,
            response_timeout_s=float(
                os.environ.get("VOICEAGENT_TURN_RESPONSE_TIMEOUT_S", "30")
            ),
            response_first_text_timeout_s=float(
                os.environ.get("VOICEAGENT_RESPONSE_FIRST_TEXT_TIMEOUT_S", "5")
            ),
            response_cancel_timeout_s=float(
                os.environ.get("VOICEAGENT_RESPONSE_CANCEL_TIMEOUT_S", "0.8")
            ),
            context_projector_factory=lambda: _build_model_context_projector(
                llm_client
            ),
            provider_timing=ProviderLatencyObserver(
                telemetry,
                instances=binding.instance_ids if binding else None,
                versions=binding.instance_versions if binding else None,
            ),
        )
        server_asr = not isinstance(asr, PreloadedAsrEngine)
        server_tts = not isinstance(tts, SilentTtsEngine)
    else:
        raise ValueError("VOICEAGENT_REALTIME_ENGINE must be 'cascaded'")
    runtime = RealtimeRuntimeFactory(
        engine=engine,
        journal=_application_runtime.journal,
        speech_deliveries=_application_runtime.speech_deliveries,
        active_conversations=_application_runtime.active_realtime_conversations,
        tool_control_handler_factory=tool_control_handler_factory,
        observer=RealtimeTelemetryObserver(telemetry),
    )

    async def handle_auxiliary_frame(frame) -> None:
        if isinstance(frame, TtsConfigFrame):
            if isinstance(tts, SelectableTtsEngine):
                try:
                    await tts.select(
                        frame.provider,
                        TtsSessionConfig(
                            voice=frame.voice,
                            speech_rate=frame.speech_rate,
                            dialect=frame.dialect,
                        ),
                    )
                except ValueError as error:
                    await session.send(
                        TtsConfigAckFrame(
                            provider=frame.provider,
                            voice=frame.voice,
                            speech_rate=frame.speech_rate,
                            dialect=frame.dialect,
                            applied=False,
                            error=str(error),
                        )
                    )
                else:
                    await session.send(
                        TtsConfigAckFrame(
                            provider=frame.provider,
                            voice=frame.voice,
                            speech_rate=frame.speech_rate,
                            dialect=frame.dialect,
                            applied=True,
                        )
                    )
                return
            if not isinstance(tts, DoubaoDirectTtsEngine):
                await session.send(
                    TtsConfigAckFrame(
                        provider=frame.provider,
                        voice=frame.voice,
                        speech_rate=frame.speech_rate,
                        dialect=frame.dialect,
                        applied=False,
                        error="TTS configuration is not supported",
                    )
                )
                return
            try:
                tts.configure(
                    TtsSessionConfig(
                        voice=frame.voice,
                        speech_rate=frame.speech_rate,
                        dialect=frame.dialect,
                    )
                )
            except ValueError as error:
                await session.send(
                    TtsConfigAckFrame(
                        provider=frame.provider,
                        voice=frame.voice,
                        speech_rate=frame.speech_rate,
                        dialect=frame.dialect,
                        applied=False,
                        error=str(error),
                    )
                )
            else:
                await session.send(
                    TtsConfigAckFrame(
                        provider=frame.provider,
                        voice=frame.voice,
                        speech_rate=frame.speech_rate,
                        dialect=frame.dialect,
                        applied=True,
                    )
                )
        elif isinstance(frame, PlaybackQualityFrame):
            await ledger.emit(
                "client.playback_quality",
                generation=frame.generation,
                arrival_jitter_ms=frame.arrival_jitter_ms,
                max_chunk_gap_ms=frame.max_chunk_gap_ms,
                underrun_count=frame.underrun_count,
                underrun_total_ms=frame.underrun_total_ms,
                chunk_count=frame.chunk_count,
            )
        elif isinstance(frame, AvatarPersonaConfigFrame):
            try:
                avatar_persona.select(
                    avatar_id=frame.avatar_id,
                    persona_id=frame.persona_id,
                )
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                logger.exception(
                    "Role Persona selection failed: avatar_id=%r persona_id=%r",
                    frame.avatar_id,
                    frame.persona_id,
                )
        elif isinstance(frame, ToolConfigFrame):
            session_memory.select_role(frame.role_id)
            selected_model = role_model_id(identity.user_id, frame.role_id)
            allowed_tool_ids = role_tool_ids(identity.user_id, frame.role_id)
            for client in (llm_client, tool_llm_client):
                if client is not None and hasattr(client, "select_model"):
                    client.select_model(selected_model)
            if tool_registry is not None:
                try:
                    if knowledge_base is not None:
                        knowledge_base.select_role(frame.role_id)
                    allowed_custom = custom_tools.select_role(frame.role_id) if custom_tools is not None else set()
                    tool_registry.select_tools([
                        name for name in frame.tool_names
                        if (binding is None and name == "get_current_datetime" and "tool-current-time" in allowed_tool_ids)
                        or (binding is None and name == "search_web" and "tool-web-search" in allowed_tool_ids)
                        or (name == "search_knowledge_base" and knowledge_base is not None and frame.role_id is not None)
                        or name in allowed_custom
                    ])
                except ValueError:
                    logger.exception("Tool selection failed: tool_names=%r", frame.tool_names)
        elif isinstance(frame, ClientConnectionQualityFrame):
            await ledger.emit(
                "client.transport_disconnect",
                generation=1,
                duration_ms=frame.last_disconnect_ms,
                reconnect_count=frame.reconnect_count,
                max_disconnect_ms=frame.max_disconnect_ms,
            )
        elif isinstance(frame, InputCaptureDiagnostic):
            await ledger.emit(
                "client.input_capture_failed",
                generation=1,
                input_epoch=frame.input_epoch,
                outcome=frame.outcome,
                buffered_frames=frame.buffered_frames,
                buffered_duration_ms=frame.buffered_duration_ms,
                aggregate_energy=frame.aggregate_energy,
            )
        elif isinstance(frame, InputEpochStarted):
            await ledger.emit(
                "client.input_epoch_started",
                generation=1,
                input_epoch=frame.input_epoch,
                format_id=frame.format.format_id,
                timeline_origin_ms=frame.timeline_origin_ms,
                requested_profile=frame.requested_profile.model_dump(mode="json"),
                effective_profile=frame.effective_profile.model_dump(mode="json"),
                requested_constraints=frame.requested_constraints.model_dump(mode="json"),
                effective_constraints=frame.effective_constraints.model_dump(mode="json"),
                effect_owners=frame.effect_owners.model_dump(mode="json"),
            )

    async def handle_confirmation_decision(
        frame: ConfirmationDecisionFrame,
    ) -> None:
        if confirmation_controller is None:
            await session.send(
                ConfirmationResolutionFrame(
                    confirmation_id=frame.confirmation_id,
                    applied=False,
                    approved=frame.approved,
                    success=False,
                    message="当前会话未启用可确认工具。",
                    error="confirmation_unavailable",
                )
            )
            return
        try:
            resolution = await confirmation_controller.handle(frame)
        except ConfirmationRejected:
            await session.send(
                ConfirmationResolutionFrame(
                    confirmation_id=frame.confirmation_id,
                    applied=False,
                    approved=frame.approved,
                    success=False,
                    message="该确认已失效或与当前操作不匹配。",
                    error="confirmation_rejected",
                )
            )
            return
        except Exception:
            logger.exception(
                "confirmation resolution failed: confirmation_id=%s",
                frame.confirmation_id,
            )
            await session.send(
                ConfirmationResolutionFrame(
                    confirmation_id=frame.confirmation_id,
                    applied=False,
                    approved=frame.approved,
                    success=False,
                    message="确认处理失败，请重新连接后再试。",
                    error="confirmation_failed",
                )
            )
            return
        await session.send(
            ConfirmationResolutionFrame(
                confirmation_id=frame.confirmation_id,
                applied=True,
                approved=frame.approved,
                success=resolution.success,
                message=resolution.model_output,
                error=resolution.error_code,
            )
        )

    return VoiceSessionWebSocketSession(
        identity=identity,
        context=context,
        profile=profile,
        runtime_factory=runtime,
        journal=_application_runtime.journal,
        transport=session,
        admission=_application_runtime.voice_session_admission,
        fast_resume_window_s=float(
            os.environ.get("VOICEAGENT_FAST_RESUME_WINDOW_S", "5")
        ),
        recovery_deadline_s=float(
            os.environ.get("VOICEAGENT_RECOVERY_DEADLINE_S", "15")
        ),
        inbound_fallback=handle_auxiliary_frame,
        confirmation_decision_handler=handle_confirmation_decision,
        pending_confirmation_authority=confirmation_authority,
        active_conversations=_application_runtime.active_realtime_conversations,
        agent_work_registry=_application_runtime.agent_work_registry,
        provider_credential_sources=(
            {"asr": binding.asr_source, "tts": binding.tts_source,
             "brain": binding.llm_source}
            if binding is not None else None
        ),
        initial_frames=(
            SessionCapabilitiesFrame(
                server_asr=server_asr,
                server_tts=server_tts,
                assistant_text_streaming=True,
                user_transcript_streaming=server_asr,
                tts_configurable=isinstance(
                    tts,
                    (DoubaoDirectTtsEngine, SelectableTtsEngine),
                ),
                tts_preview=_supports_tts_preview(tts),
            ),
        ),
    )


def _build_conversation_identity_from_session(
    session: InMemoryEndpointSession,
) -> VoiceSessionIdentity:
    trusted = session.authenticated_identity
    if trusted is None:
        raise RuntimeError("v2 Endpoint Session is missing trusted identity")
    return VoiceSessionIdentity(
        tenant_id=trusted.tenant_id,
        user_id=trusted.user_id,
        device_id=trusted.device_id,
        voice_session_id=session.session_id,
        thread_id=session.authorized_thread_id,
        previous_voice_session_id=getattr(
            session, "previous_voice_session_id", None
        ),
    )


def _build_session_runtime(session: InMemoryEndpointSession):
    return _build_realtime_session(session)


async def _start_application_runtime() -> ApplicationRuntime:
    global _application_runtime, _avatar_asset_runtime
    if _application_runtime is None:
        _application_runtime = await build_application_runtime(ApplicationRuntimeConfig.from_env())
        try:
            _avatar_asset_runtime = await build_avatar_asset_runtime_from_env()
        except Exception:
            await _application_runtime.close()
            _application_runtime = None
            raise
        model_dir = os.environ.get("VOICEAGENT_EOT_FIRERED_MODEL_DIR")
        if model_dir:
            await asyncio.to_thread(
                _load_firered_provider,
                model_dir,
                os.environ.get("VOICEAGENT_EOT_FIRERED_LANGUAGE", "chinese"),
                int(
                    os.environ.get(
                        "VOICEAGENT_EOT_FIRERED_INTRA_OP_THREADS",
                        "2",
                    )
                ),
                float(os.environ.get("VOICEAGENT_EOT_FIRERED_THRESHOLD", "0.5")),
                int(
                    os.environ.get(
                        "VOICEAGENT_EOT_FIRERED_MAX_CONCURRENCY",
                        "2",
                    )
                ),
            )
    return _application_runtime


async def _stop_application_runtime(state: object) -> None:
    global _application_runtime, _avatar_asset_runtime
    avatar_runtime = _avatar_asset_runtime
    _avatar_asset_runtime = None
    if _application_runtime is state:
        _application_runtime = None
    try:
        if avatar_runtime is not None:
            await avatar_runtime.close()
    finally:
        if isinstance(state, ApplicationRuntime):
            await state.close()


async def _handle_avatar_asset_request(
    method: str,
    path: str,
    query: str,
    headers: dict[str, str],
    body: bytes,
) -> AvatarAssetHttpResponse:
    if _avatar_asset_runtime is None:
        return AvatarAssetHttpResponse.json(
            503,
            {"error": "avatar asset service is not configured"},
        )
    return await _avatar_asset_runtime.api.handle(method, path, query, headers, body)


async def _read_session_conversation(session_id: str) -> list[dict]:
    """Project the authoritative Conversation Journal for admin replay."""
    if _application_runtime is None:
        return []
    scope = JournalScope(
        tenant_id=os.environ.get("VOICEAGENT_TENANT_ID", "local"),
        user_id=os.environ.get("VOICEAGENT_USER_ID", "local-user"),
        thread_id=session_id,
    )
    items = await _application_runtime.journal.read(scope, limit=1000)
    projected: list[dict] = []
    for item in items:
        if item.kind not in {
            ConversationItemKind.USER_INPUT,
            ConversationItemKind.ASSISTANT_OUTPUT,
        }:
            continue
        text = "".join(
            part.text for part in item.content if isinstance(part, TextContent)
        )
        if not text:
            continue
        projected.append(
            {
                "item_id": item.item_id,
                "role": (
                    "user"
                    if item.kind is ConversationItemKind.USER_INPUT
                    else "assistant"
                ),
                "text": text,
                "generation": item.context.generation,
                "status": item.status.value,
                "occurred_at": item.occurred_at.isoformat(),
            }
        )
    return projected


async def _delete_session_history(session_ids: list[str]) -> dict[str, int]:
    """Delete completed session telemetry and its scoped conversation thread."""
    if _application_runtime is None:
        raise RuntimeError("application runtime is not started")
    return await _application_runtime.delete_session_history(
        session_ids,
        tenant_id=os.environ.get("VOICEAGENT_TENANT_ID", "local"),
        user_id=os.environ.get("VOICEAGENT_USER_ID", "local-user"),
    )


if __name__ == "__main__":
    run_app(
        _build_session_runtime,
        serve=_websocket_serve,
        session_registry=_session_registry,
        host=WS_HOST,
        port=WS_PORT,
        on_startup=_start_application_runtime,
        on_shutdown=_stop_application_runtime,
        diagnostics_query_factory=(
            lambda state: state.diagnostics
            if isinstance(state, ApplicationRuntime)
            else None
        ),
        voice_previewer=_preview_voice,
        session_conversation_reader=_read_session_conversation,
        session_history_deleter=_delete_session_history,
        avatar_asset_handler=_handle_avatar_asset_request,
    )
