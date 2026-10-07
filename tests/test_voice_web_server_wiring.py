"""Env-var-gated builder tests for demos/voice_web_server.py.

Guards against the exact class of bug this file fixed: VOICEAGENT_DEMO_TOOLS
being set in .env with zero effect because _build_kernel never read it. No
network calls, no real credentials — mirrors
tests/test_openai_compatible_tool_calling_llm_client.py's env-var convention.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from demos import voice_web_server
from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.brain.chat_brain import ChatBrain
from server.brain.llm_clients import EchoLlmClient, EchoToolCallingLlmClient
from server.brain.plugins.openai_compatible_llm_client import OpenAiCompatibleLlmClient
from server.brain.plugins.openai_compatible_tool_calling_llm_client import (
    OpenAiCompatibleToolCallingLlmClient,
)
from server.brain.realtime_grounding import (
    LlmGroundingPlanner,
    RealtimeGroundingCoordinator,
)
from server.brain.tool_calling_brain import ToolCallingBrain
from server.realtime.capabilities.brain_streaming import VoiceRuntimeBrainStreamingAdapter
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
from server.realtime.observability import RealtimeTelemetryObserver
from server.realtime.profile import ResolvedRealtimeProfile
from server.signals.plugins.silero_vad import SileroVad
from server.speech.asr import PreloadedAsrEngine
from server.speech.plugins.bailian_asr import BailianAsrEngine
from server.speech.plugins.bailian_tts import BailianTtsEngine
from server.speech.plugins.doubao_asr import DoubaoAsrEngine
from server.speech.selectable_tts import SelectableTtsEngine
from server.speech.tts import SilentTtsEngine, SynthesizedAudioChunk
from server.transport.base import AuthenticatedTransportIdentity
from server.transport.plugins.websocket import StaticBearerWebSocketAuthenticator
from server.turn_policy.plugins.fast_complete_fallback_eot_classifier import (
    FastCompleteFallbackEotClassifier,
)
from server.turn_policy.plugins.fireredchat_eot_provider import FireRedChatEotProvider
from server.turn_policy.plugins.hybrid_eot_classifier import HybridEotClassifier
from server.turn_policy.plugins.llm_dual_intent_classifier import LlmDualIntentClassifier
from server.turn_policy.plugins.llm_eot_classifier import LlmEotClassifier
from server.turn_policy.plugins.llm_semantic_interruption_classifier import (
    LlmSemanticInterruptionClassifier,
)
from server.voice_session.endpoint_bridge import VoiceSessionWebSocketSession
from server.web_search.deterministic_web_search import DeterministicWebSearch
from server.web_search.plugins.byte_web_search import ByteWebSearch


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        ("", None),
        ("cantonese", "请用广东话表达。"),
        ("sichuan", "请用四川话表达。"),
    ],
)
def test_bailian_dialect_instruction_uses_required_cosyvoice_format(
    dialect: str, expected: str | None,
) -> None:
    assert voice_web_server._bailian_tts_instruction(dialect) == expected


TEST_ENDPOINT_IDENTITY = AuthenticatedTransportIdentity(
    tenant_id="test-tenant",
    user_id="test-user",
    device_id="test-browser",
)


def test_explicit_local_role_providers_use_their_configured_engines(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-dashscope")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    assert isinstance(voice_web_server._build_asr_engine(provider_override="dashscope"), BailianAsrEngine)
    client = voice_web_server._build_llm_client(provider_override="openai")
    assert client._provider_name == "openai"

_ENV_VARS = (
    "API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_LLM_MODEL",
    "VOICEAGENT_LLM_API_KEY",
    "VOICEAGENT_LLM_BASE_URL",
    "VOICEAGENT_LLM_MODEL",
    "VOICEAGENT_LLM_DISABLE_THINKING",
    "VOICEAGENT_DEMO_TOOLS",
    "BYTE_WEB_SEARCH_API_KEY",
    "WEB_SEARCH_API_KEY",
    "DOUBAO_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_WORKSPACE_ID",
    "BAILIAN_API_HOST",
    "BAILIAN_TTS_WS_URL",
    "BAILIAN_TTS_MODEL",
    "BAILIAN_TTS_VOICE",
    "BAILIAN_TTS_INSTRUCTION",
    "VOICEAGENT_ASR_BACKEND",
    "VOICEAGENT_TTS_BACKEND",
    "VOICEAGENT_VAD_SILENCE_MS",
    "VOICEAGENT_VAD_ONSET_MS",
    "VOICEAGENT_VAD_THRESHOLD",
    "VOICEAGENT_LATE_ASR_RECOVERY_MS",
    "VOICEAGENT_EOT_LLM_TIMEOUT_MS",
    "VOICEAGENT_EOT_ASR_IDLE_MS",
    "VOICEAGENT_EOT_INCOMPLETE_TIMEOUT_MS",
    "VOICEAGENT_EOT_UNCERTAIN_WAIT_MS",
    "VOICEAGENT_EOT_LLM_API_STYLE",
    "VOICEAGENT_EOT_FIRERED_MODEL_DIR",
    "VOICEAGENT_EOT_FIRERED_THRESHOLD",
    "VOICEAGENT_EOT_FIRERED_FAST_COMPLETE_THRESHOLD",
    "VOICEAGENT_EOT_FIRERED_STRATEGY",
    "VOICEAGENT_TURN_RESPONSE_TIMEOUT_S",
    "VOICEAGENT_GROUNDING_PLANNER_TIMEOUT_S",
    "VOICEAGENT_GROUNDING_SEARCH_TIMEOUT_S",
    "VOICEAGENT_GROUNDING_TOTAL_TIMEOUT_S",
    "VOICEAGENT_REALTIME_RUNTIME",
    "VOICEAGENT_REALTIME_ENGINE",
    "VOICEAGENT_REALTIME_PROFILE_PATH",
    "VOICEAGENT_NATIVE_REALTIME_API_KEY",
    "VOICEAGENT_NATIVE_REALTIME_MODEL",
    "VOICEAGENT_ENDPOINT_AUTH_MODE",
    "VOICEAGENT_ENDPOINT_AUTH_TOKEN",
    "VOICEAGENT_TENANT_ID",
    "VOICEAGENT_USER_ID",
    "VOICEAGENT_DEVICE_ID",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_build_brain_returns_chat_brain_when_demo_tools_unset(monkeypatch):
    monkeypatch.setenv("API_KEY", "bella-key")

    brain = voice_web_server._build_brain(voice_web_server.EchoLlmClient())

    assert isinstance(brain, ChatBrain)
    assert isinstance(brain._grounder, RealtimeGroundingCoordinator)


def test_build_brain_keeps_zero_config_echo_path_free_of_planner_calls():
    brain = voice_web_server._build_brain(voice_web_server.EchoLlmClient())

    assert isinstance(brain, ChatBrain)
    assert brain._grounder is None


def test_build_realtime_grounder_reuses_llm_and_only_enables_real_search_with_key(
    monkeypatch,
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    client = EchoLlmClient()

    without_search = voice_web_server._build_realtime_grounder(client)

    assert isinstance(without_search, RealtimeGroundingCoordinator)
    assert isinstance(without_search._planner, LlmGroundingPlanner)
    assert without_search._planner._llm_client is client
    assert without_search._web_search is None

    monkeypatch.setenv("BYTE_WEB_SEARCH_API_KEY", "search-key")
    with_search = voice_web_server._build_realtime_grounder(client)

    assert isinstance(with_search._web_search, ByteWebSearch)


def test_build_realtime_grounder_accepts_legacy_search_key_name(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("WEB_SEARCH_API_KEY", "search-key")

    grounder = voice_web_server._build_realtime_grounder(EchoLlmClient())

    assert isinstance(grounder, RealtimeGroundingCoordinator)
    assert isinstance(grounder._web_search, ByteWebSearch)
    assert grounder._web_search._api_key == "search-key"


def test_build_brain_returns_tool_calling_brain_when_demo_tools_set(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_DEMO_TOOLS", "1")

    brain = voice_web_server._build_brain(voice_web_server.EchoLlmClient())

    assert isinstance(brain, ToolCallingBrain)


def test_public_knowledge_registry_excludes_builtin_and_custom_tools(monkeypatch):
    monkeypatch.delenv("VOICEAGENT_DEMO_TOOLS", raising=False)
    knowledge = voice_web_server.LocalCatalogKnowledgeBase("issuer#user")
    registry = voice_web_server._build_tool_registry(knowledge_base=knowledge, include_builtins=False)
    assert [tool.name for tool in registry.as_list()] == ["search_knowledge_base"]


def test_explicit_public_registry_uses_tool_brain_without_demo_flag(monkeypatch):
    monkeypatch.delenv("VOICEAGENT_DEMO_TOOLS", raising=False)
    registry = voice_web_server._build_tool_registry(
        knowledge_base=voice_web_server.LocalCatalogKnowledgeBase("issuer#user"),
        include_builtins=False,
    )
    assert isinstance(voice_web_server._build_brain(EchoLlmClient(), tool_registry=registry), ToolCallingBrain)


def test_public_tool_client_uses_the_admitted_personal_llm_key(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "platform-key")
    binding = SimpleNamespace(
        llm_provider="deepseek", llm_source="personal",
        credentials={"deepseek": "personal-key"},
        instance_credentials={}, instance_models={}, instance_base_urls={}, instance_ids={}, instance_versions={},
    )
    client = voice_web_server._build_tool_calling_llm_client(binding=binding)
    assert client._api_key == "personal-key"


def test_public_clients_use_the_admitted_openai_key(monkeypatch):
    from types import SimpleNamespace

    binding = SimpleNamespace(
        llm_provider="openai", llm_source="personal",
        credentials={"openai": "personal-openai-key"},
        instance_credentials={}, instance_models={}, instance_base_urls={}, instance_ids={}, instance_versions={},
    )
    client = voice_web_server._build_llm_client(binding=binding)
    tool_client = voice_web_server._build_tool_calling_llm_client(binding=binding)
    for selected in (client, tool_client):
        assert selected._api_key == "personal-openai-key"
        assert selected._base_url == "https://api.openai.com/v1"
        assert selected._model == "gpt-4.1-mini"


def test_selected_instance_key_and_model_override_legacy_provider_credentials():
    from types import SimpleNamespace

    binding = SimpleNamespace(
        llm_provider="openai", llm_source="personal",
        credentials={"openai": "legacy-key"},
        instance_credentials={"llm": "instance-key"},
        instance_models={"llm": "gpt-selected"},
        instance_base_urls={"llm": "https://api.openai.com/v1"},
        instance_ids={"llm": "instance-id"},
        instance_versions={"llm": "config-revision"},
    )
    client = voice_web_server._build_llm_client(binding=binding)
    assert client._api_key == "instance-key"
    assert client._model == "gpt-selected"
    assert client._base_url == "https://api.openai.com/v1"
    assert client._instance_id == "instance-id"
    assert client._config_version == "config-revision"


def test_selected_deepseek_instance_uses_the_protocol_verified_by_its_streaming_test(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("VOICEAGENT_LLM_API_STYLE", "responses")
    binding = SimpleNamespace(
        llm_provider="deepseek", llm_source="personal",
        credentials={}, instance_credentials={"llm": "instance-key"},
        instance_models={"llm": "deepseek-chat"},
        instance_base_urls={"llm": "https://api.deepseek.com"},
        instance_ids={"llm": "instance-id"}, instance_versions={"llm": "revision"},
    )

    client = voice_web_server._build_llm_client(binding=binding)

    assert client._api_style == "chat_completions"
    assert client._model == "deepseek-chat"


@pytest.mark.parametrize(
    ("provider", "expected_model"),
    [("deepseek", "deepseek-chat"), ("openai", "gpt-4.1-mini")],
)
def test_selected_llm_without_model_uses_the_same_default_as_its_streaming_test(
    monkeypatch, provider, expected_model,
):
    from types import SimpleNamespace

    monkeypatch.setenv("DEEPSEEK_LLM_MODEL", "unrelated-platform-model")
    monkeypatch.setenv("OPENAI_LLM_MODEL", "unrelated-platform-model")
    binding = SimpleNamespace(
        llm_provider=provider, llm_source="personal", credentials={},
        instance_credentials={"llm": "instance-key"}, instance_models={"llm": ""},
        instance_base_urls={},
        instance_ids={"llm": "instance-id"}, instance_versions={"llm": "revision"},
    )

    assert voice_web_server._build_llm_client(binding=binding)._model == expected_model
    assert voice_web_server._build_tool_calling_llm_client(binding=binding)._model == expected_model


def test_same_vendor_asr_and_tts_instances_use_independent_keys():
    from types import SimpleNamespace

    binding = SimpleNamespace(
        asr_provider="doubao", asr_source="personal",
        tts_provider="doubao", tts_source="personal",
        credentials={"doubao": "legacy-key"},
        instance_credentials={"asr": "asr-instance-key", "tts": "tts-instance-key"},
        instance_models={}, instance_ids={}, instance_versions={},
    )
    asr = voice_web_server._build_asr_engine(binding)
    tts = voice_web_server._build_session_tts_engine(binding)
    assert asr._api_key == "asr-instance-key"
    assert tts._factories["doubao"](tts._config)._api_key == "tts-instance-key"


def test_openai_platform_key_is_used_when_no_other_llm_is_configured(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "platform-openai-key")
    client = voice_web_server._build_llm_client()
    tool_client = voice_web_server._build_tool_calling_llm_client()
    for selected in (client, tool_client):
        assert selected._api_key == "platform-openai-key"
        assert selected._base_url == "https://api.openai.com/v1"


def test_build_llm_client_uses_explicit_generic_deepseek_config(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "deepseek-key")
    monkeypatch.setenv("VOICEAGENT_LLM_BASE_URL", "https://deepseek.example/v1/")
    monkeypatch.setenv("VOICEAGENT_LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("VOICEAGENT_LLM_DISABLE_THINKING", "1")

    client = voice_web_server._build_llm_client()

    assert isinstance(client, OpenAiCompatibleLlmClient)
    assert client._api_key == "deepseek-key"
    assert client._base_url == "https://deepseek.example/v1"
    assert client._model == "deepseek-v4-flash"
    assert client._disable_thinking is True


def test_build_llm_client_accepts_provider_key_with_low_latency_defaults(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    client = voice_web_server._build_llm_client()

    assert isinstance(client, OpenAiCompatibleLlmClient)
    assert client._api_key == "deepseek-key"
    assert client._base_url == "https://api.deepseek.com"
    assert client._model == "deepseek-v4-flash"
    assert client._disable_thinking is True
    assert client._api_style == "responses"


def test_build_llm_client_prefers_explicit_generic_config_over_legacy_bella(monkeypatch):
    monkeypatch.setenv("API_KEY", "bella-key")
    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "deepseek-key")
    monkeypatch.setenv("VOICEAGENT_LLM_MODEL", "deepseek-v4-flash")

    client = voice_web_server._build_llm_client()

    assert isinstance(client, OpenAiCompatibleLlmClient)
    assert client._api_key == "deepseek-key"
    assert client._model == "deepseek-v4-flash"


def test_build_llm_client_falls_back_to_legacy_bella(monkeypatch):
    monkeypatch.setenv("API_KEY", "bella-key")

    client = voice_web_server._build_llm_client()

    assert isinstance(client, OpenAiCompatibleLlmClient)
    assert client._api_key == "bella-key"
    assert client._base_url == voice_web_server.BELLA_BASE_URL
    assert client._model == voice_web_server.BELLA_LLM_MODEL


def test_build_llm_client_falls_back_to_echo_with_no_credentials():
    client = voice_web_server._build_llm_client()

    assert isinstance(client, EchoLlmClient)


def test_build_tool_calling_llm_client_prefers_explicit_generic_config(monkeypatch):
    monkeypatch.setenv("API_KEY", "bella-key")
    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "deepseek-key")
    monkeypatch.setenv("VOICEAGENT_LLM_MODEL", "deepseek-v4-flash")

    client = voice_web_server._build_tool_calling_llm_client()

    assert isinstance(client, OpenAiCompatibleToolCallingLlmClient)
    assert client._api_key == "deepseek-key"
    assert client._model == "deepseek-v4-flash"


def test_build_tool_calling_llm_client_falls_back_to_generic_env_vars(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_LLM_API_KEY", "deepseek-key")

    client = voice_web_server._build_tool_calling_llm_client()

    assert isinstance(client, OpenAiCompatibleToolCallingLlmClient)


def test_build_tool_calling_llm_client_accepts_provider_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    client = voice_web_server._build_tool_calling_llm_client()

    assert isinstance(client, OpenAiCompatibleToolCallingLlmClient)
    assert client._api_key == "deepseek-key"
    assert client._base_url == "https://api.deepseek.com"
    assert client._model == "deepseek-v4-flash"
    assert client._disable_thinking is True


def test_build_tool_calling_llm_client_falls_back_to_echo_with_no_credentials():
    client = voice_web_server._build_tool_calling_llm_client()

    assert isinstance(client, EchoToolCallingLlmClient)


def test_build_web_search_returns_byte_web_search_when_key_set(monkeypatch):
    monkeypatch.setenv("BYTE_WEB_SEARCH_API_KEY", "search-key")

    search = voice_web_server._build_web_search()

    assert isinstance(search, ByteWebSearch)


def test_build_web_search_accepts_legacy_search_key_name(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_API_KEY", "search-key")

    search = voice_web_server._build_web_search()

    assert isinstance(search, ByteWebSearch)
    assert search._api_key == "search-key"


def test_build_web_search_falls_back_to_deterministic_with_no_key():
    search = voice_web_server._build_web_search()

    assert isinstance(search, DeterministicWebSearch)


def test_build_vad_uses_direct_silero_adapter_with_256ms_eot():
    vad = voice_web_server._build_vad()

    assert isinstance(vad, SileroVad)
    assert vad._tracker._config.silence_duration_ms == 256.0
    assert vad._tracker._config.speech_onset_duration_ms == 96.0
    assert vad._threshold == 0.6


def test_build_vad_accepts_silence_window_override(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_VAD_SILENCE_MS", "240")
    monkeypatch.setenv("VOICEAGENT_VAD_ONSET_MS", "128")
    monkeypatch.setenv("VOICEAGENT_VAD_THRESHOLD", "0.7")

    vad = voice_web_server._build_vad()

    assert vad._tracker._config.silence_duration_ms == 240.0
    assert vad._tracker._config.speech_onset_duration_ms == 128.0
    assert vad._threshold == 0.7


def test_build_eot_classifier_uses_deepseek_responses_with_strict_schema(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    client = EchoLlmClient()

    classifier = voice_web_server._build_eot_classifier(client)

    assert isinstance(classifier, LlmEotClassifier)
    assert isinstance(classifier._llm_client, OpenAiCompatibleLlmClient)
    assert classifier._llm_client._api_style == "responses"
    assert classifier._llm_client._response_schema_name == "semantic_eot"
    assert classifier._source == "deepseek_responses"


def test_jev_can_replace_both_semantic_providers_without_llm_credentials(monkeypatch):
    from server.turn_policy.plugins.jev_classifier import (
        JevEotClassifier,
        JevSemanticInterruptionClassifier,
    )

    monkeypatch.setenv("JEV_API_KEY", "test")
    monkeypatch.setenv("VOICEAGENT_EOT_PROVIDER", "jev")
    monkeypatch.setenv("VOICEAGENT_INTERRUPTION_PROVIDER", "jev")
    monkeypatch.setenv("VOICEAGENT_EOT_FIRERED_MODEL_DIR", "/unused")
    assert isinstance(voice_web_server._build_eot_classifier(EchoLlmClient()), JevEotClassifier)
    assert isinstance(
        voice_web_server._build_semantic_interruption_classifier(EchoLlmClient()),
        JevSemanticInterruptionClassifier,
    )


def test_jev_missing_key_fails_explicitly(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.setenv("VOICEAGENT_EOT_PROVIDER", "jev")
    with pytest.raises(ValueError, match="API key"):
        voice_web_server._build_eot_classifier(EchoLlmClient())


def test_build_eot_classifier_uses_conservative_firered_fast_complete(monkeypatch):
    class ProbabilityModel:
        def predict(self, text: str) -> float:
            return 0.8

    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("VOICEAGENT_EOT_FIRERED_MODEL_DIR", "/models/firered")
    loads = 0

    def load_model(*args, **kwargs):
        nonlocal loads
        loads += 1
        return ProbabilityModel()

    monkeypatch.setattr(
        voice_web_server,
        "FireRedChatOnnxModel",
        load_model,
    )

    classifier = voice_web_server._build_eot_classifier(EchoLlmClient())
    second = voice_web_server._build_eot_classifier(EchoLlmClient())

    assert isinstance(classifier, FastCompleteFallbackEotClassifier)
    assert isinstance(classifier._fast_provider, FireRedChatEotProvider)
    assert classifier._fast_complete_threshold == 0.5
    assert classifier._fast_provider is second._fast_provider
    assert classifier._fast_provider._model is second._fast_provider._model
    assert loads == 1


def test_build_eot_classifier_keeps_shadow_strategy_as_explicit_rollback(
    monkeypatch,
):
    class ProbabilityModel:
        def predict(self, text: str) -> float:
            return 0.8

    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("VOICEAGENT_EOT_FIRERED_MODEL_DIR", "/models/firered-shadow")
    monkeypatch.setenv("VOICEAGENT_EOT_FIRERED_STRATEGY", "primary_with_shadow")
    monkeypatch.setattr(
        voice_web_server,
        "FireRedChatOnnxModel",
        lambda *args, **kwargs: ProbabilityModel(),
    )

    classifier = voice_web_server._build_eot_classifier(EchoLlmClient())

    assert isinstance(classifier, HybridEotClassifier)
    assert classifier._strategy == "primary_with_shadow"


def test_build_dual_intent_classifier_uses_deepseek_client(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    client = EchoLlmClient()

    classifier = voice_web_server._build_dual_intent_classifier(client)

    assert isinstance(classifier, LlmDualIntentClassifier)
    assert classifier._llm_client is client


def test_build_semantic_interruption_classifier_uses_deepseek_client(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    client = EchoLlmClient()

    classifier = voice_web_server._build_semantic_interruption_classifier(client)

    assert isinstance(classifier, LlmSemanticInterruptionClassifier)
    assert classifier._llm_client is client


def test_build_asr_engine_defaults_to_doubao_direct_when_key_set(monkeypatch):
    monkeypatch.setenv("DOUBAO_API_KEY", "doubao-key")

    asr = voice_web_server._build_asr_engine()

    assert isinstance(asr, DoubaoAsrEngine)


def test_dashscope_asr_instance_uses_its_own_workspace_and_key():
    from types import SimpleNamespace

    from server.speech.plugins.bailian_asr import BailianAsrEngine

    binding = SimpleNamespace(
        asr_provider="dashscope", asr_source="personal", credentials={},
        instance_credentials={"asr": "instance-key"},
        instance_base_urls={"asr": "https://llm-test.cn-beijing.maas.aliyuncs.com"},
        instance_models={"asr": ""},
    )
    asr = voice_web_server._build_asr_engine(binding)
    assert isinstance(asr, BailianAsrEngine)
    assert asr._api_key == "instance-key"
    assert asr._url.startswith("wss://llm-test.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?")


def test_build_asr_engine_rejects_removed_bella_backend(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_ASR_BACKEND", "bella")
    monkeypatch.setenv("API_KEY", "bella-key")
    monkeypatch.setenv("DOUBAO_API_KEY", "doubao-key")

    with pytest.raises(ValueError, match="unsupported ASR backend"):
        voice_web_server._build_asr_engine()


def test_build_asr_engine_falls_back_to_preloaded_with_no_credentials():
    asr = voice_web_server._build_asr_engine()

    assert isinstance(asr, PreloadedAsrEngine)


def test_build_tts_engine_uses_bailian_duplex_backend(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_TTS_BACKEND", "bailian")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "bailian-key")
    monkeypatch.setenv("DASHSCOPE_WORKSPACE_ID", "llm-example")
    monkeypatch.setenv("BAILIAN_API_HOST", "llm-example.cn-beijing.maas.aliyuncs.com")
    monkeypatch.setenv("BAILIAN_TTS_MODEL", "cosyvoice-v3.5-flash")
    monkeypatch.setenv("BAILIAN_TTS_VOICE", "cosyvoice-clone-demo")

    tts = voice_web_server._build_tts_engine()

    assert isinstance(tts, BailianTtsEngine)
    assert tts._ws_url == (
        "wss://llm-example.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
    )
    assert tts._model == "cosyvoice-v3.5-flash"
    assert tts._voice == "cosyvoice-clone-demo"
    assert tts._workspace_id == "llm-example"


def test_build_tts_engine_bailian_falls_back_to_silent_without_key(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_TTS_BACKEND", "bailian")

    tts = voice_web_server._build_tts_engine()

    assert isinstance(tts, SilentTtsEngine)


def test_session_tts_engine_exposes_every_configured_provider(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_TTS_BACKEND", "bailian")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "bailian-key")
    monkeypatch.setenv("DOUBAO_API_KEY", "doubao-key")

    tts = voice_web_server._build_session_tts_engine()

    assert isinstance(tts, SelectableTtsEngine)
    assert tts.provider == "bailian"
    assert tts.available_providers == ("bailian", "doubao")
    assert voice_web_server._supports_tts_preview(tts) is True


def test_legacy_kernel_builder_is_not_exposed_by_the_production_demo() -> None:
    assert not hasattr(voice_web_server, "_build_kernel")
    assert not hasattr(voice_web_server, "_finish_build_kernel")


def test_production_demo_accepts_only_v2_endpoint_sessions() -> None:
    assert voice_web_server._session_registry._supported_protocol_versions == (2,)


def test_endpoint_security_defaults_to_explicit_development_identity() -> None:
    registry, serve_endpoint = voice_web_server._build_endpoint_security()

    assert registry._development_identity == AuthenticatedTransportIdentity(
        tenant_id="local",
        user_id="local-user",
        device_id="browser",
    )
    assert serve_endpoint.keywords["authenticator"] is None


def test_static_bearer_endpoint_security_requires_complete_server_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VOICEAGENT_ENDPOINT_AUTH_MODE", "static_bearer")
    with pytest.raises(RuntimeError, match="VOICEAGENT_ENDPOINT_AUTH_TOKEN"):
        voice_web_server._build_endpoint_security()

    monkeypatch.setenv(
        "VOICEAGENT_ENDPOINT_AUTH_TOKEN",
        "a-secure-static-bearer-token-0001",
    )
    monkeypatch.setenv("VOICEAGENT_TENANT_ID", "tenant-1")
    monkeypatch.setenv("VOICEAGENT_USER_ID", "user-1")
    monkeypatch.setenv("VOICEAGENT_DEVICE_ID", "browser-1")

    registry, serve_endpoint = voice_web_server._build_endpoint_security()

    assert registry._development_identity is None
    assert isinstance(
        serve_endpoint.keywords["authenticator"],
        StaticBearerWebSocketAuthenticator,
    )


async def test_application_shutdown_closes_main_runtime_when_avatar_close_fails(
    monkeypatch,
) -> None:
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    calls: list[str] = []

    class FailingAvatarRuntime:
        async def close(self) -> None:
            calls.append("avatar.close")
            raise RuntimeError("avatar close failed")

    async def close_main(self) -> None:
        del self
        calls.append("application.close")

    monkeypatch.setattr(type(runtime), "close", close_main)
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    monkeypatch.setattr(
        voice_web_server,
        "_avatar_asset_runtime",
        FailingAvatarRuntime(),
    )

    with pytest.raises(RuntimeError, match="avatar close failed"):
        await voice_web_server._stop_application_runtime(runtime)

    assert calls == ["avatar.close", "application.close"]
    assert voice_web_server._avatar_asset_runtime is None
    assert voice_web_server._application_runtime is None


@pytest.mark.parametrize("prefetch_tts", [False, True])
@pytest.mark.parametrize("sentence_prefetch", [None, "0", "true"])
async def test_session_runtime_can_select_stateful_realtime_transport(
    monkeypatch, prefetch_tts, sentence_prefetch,
):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    monkeypatch.setenv("VOICEAGENT_REALTIME_RUNTIME", "1")
    monkeypatch.setenv("VOICEAGENT_RESPONSE_PREFETCH_ENABLED", "1")
    if sentence_prefetch is None:
        monkeypatch.delenv("VOICEAGENT_SENTENCE_HANDOFF_PREFETCH_ENABLED", raising=False)
    else:
        monkeypatch.setenv("VOICEAGENT_SENTENCE_HANDOFF_PREFETCH_ENABLED", sentence_prefetch)
    monkeypatch.setenv("VOICEAGENT_RESPONSE_PREFETCH_TTS_ENABLED", "1" if prefetch_tts else "0")
    monkeypatch.setenv("VOICEAGENT_TURN_RESPONSE_TIMEOUT_S", "12")
    monkeypatch.setenv("VOICEAGENT_EOT_ASR_IDLE_MS", "750")
    monkeypatch.setenv("VOICEAGENT_LATE_ASR_RECOVERY_MS", "384")
    monkeypatch.setenv("VOICEAGENT_FAST_RESUME_WINDOW_S", "4.5")
    monkeypatch.setenv("VOICEAGENT_RECOVERY_DEADLINE_S", "14")
    semantic_eot = object()
    monkeypatch.setattr(
        voice_web_server,
        "_build_eot_classifier",
        lambda client: semantic_eot,
    )

    class DuplexTts:
        async def synthesize_duplex(
            self,
            text_stream: AsyncIterator[str],
        ) -> AsyncIterator[SynthesizedAudioChunk]:
            async for _ in text_stream:
                pass
            if False:
                yield SynthesizedAudioChunk(b"", 16_000, True)

        async def close(self) -> None:
            return None

    monkeypatch.setattr(voice_web_server, "_build_tts_engine", DuplexTts)

    class Session:
        session_id = "realtime-session"
        authenticated_identity = TEST_ENDPOINT_IDENTITY
        authorized_thread_id = session_id

        async def send(self, frame):
            del frame

        async def receive(self):
            if False:
                yield

        async def close(self):
            return None

    session_runtime = voice_web_server._build_session_runtime(Session())

    assert isinstance(session_runtime, VoiceSessionWebSocketSession)
    assert session_runtime._admission is runtime.voice_session_admission
    assert session_runtime._fast_resume_window_s == 4.5
    assert session_runtime._recovery_deadline_s == 14
    assert isinstance(session_runtime._profile, ResolvedRealtimeProfile)
    assert len(session_runtime._profile.diagnostic_digest) == 64
    assert session_runtime._runtime_factory._journal is runtime.journal
    assert (
        session_runtime._runtime_factory._engine._speech_deliveries
        is runtime.speech_deliveries
    )
    turn_manager = session_runtime._runtime_factory._engine._turn_manager
    assert turn_manager._endpoint_gate._classifier is semantic_eot
    assert turn_manager._endpoint_gate._classifier_timeout_s == 5.0
    assert turn_manager._asr_idle_stop_s == 0.75
    assert turn_manager._late_asr_recovery_us == 384_000
    assert turn_manager._incomplete_timeout_s == 5.0
    assert session_runtime._runtime_factory._engine._response_timeout_s == 12.0
    assert (
        session_runtime._runtime_factory._engine._response_first_text_timeout_s
        == 5.0
    )
    assert session_runtime._runtime_factory._engine._tts._cancel_timeout_s == 0.3
    assert isinstance(
        session_runtime._runtime_factory._engine._brain._brain,
        SpeculativeSpeechPipeline if prefetch_tts else SpeculativeStreamingBrain,
    )
    assert (
        turn_manager._response_prefetcher
        is session_runtime._runtime_factory._engine._brain._brain
    )
    assert turn_manager.response_prefetch_enabled is True
    assert turn_manager.sentence_handoff_prefetch_enabled is (sentence_prefetch == "true")
    assert turn_manager.input_evidence_journal is runtime.journal
    assert turn_manager.input_budget.max_text_bytes == 16384
    assert turn_manager.input_evidence_timeout_s == 1
    if prefetch_tts:
        assert session_runtime._runtime_factory._engine._tts._engine is session_runtime._runtime_factory._engine._brain._brain
    else:
        assert isinstance(session_runtime._runtime_factory._engine._tts._engine, DuplexTts)
    assert isinstance(
        session_runtime._runtime_factory._observer,
        RealtimeTelemetryObserver,
    )

    await runtime.close()


async def test_stateful_realtime_prefetches_chat_without_speculating_tools(
    monkeypatch,
):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    monkeypatch.setenv("VOICEAGENT_REALTIME_RUNTIME", "1")
    monkeypatch.setenv("VOICEAGENT_DEMO_TOOLS", "1")
    monkeypatch.setattr(voice_web_server, "_build_vad", lambda: object())
    monkeypatch.setattr(voice_web_server, "_build_eot_classifier", lambda client: None)
    monkeypatch.setattr(
        voice_web_server,
        "_build_dual_intent_classifier",
        lambda client: None,
    )

    class Session:
        session_id = "realtime-tools-session"
        authenticated_identity = TEST_ENDPOINT_IDENTITY
        authorized_thread_id = session_id

        async def send(self, frame):
            del frame

        async def close(self):
            return None

    session_runtime = voice_web_server._build_session_runtime(Session())
    engine = session_runtime._runtime_factory._engine
    brain = engine._brain._brain
    turn_manager = engine._turn_manager

    assert isinstance(brain, VoiceRuntimeBrainStreamingAdapter)
    assert isinstance(brain._chat, SpeculativeStreamingBrain)
    assert turn_manager._response_prefetcher is brain

    await runtime.close()


async def test_session_runtime_defaults_to_stateful_realtime_transport(monkeypatch):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)

    class Session:
        session_id = "default-realtime-session"
        authenticated_identity = TEST_ENDPOINT_IDENTITY
        authorized_thread_id = session_id

        async def send(self, frame):
            del frame

        async def receive(self):
            if False:
                yield

        async def close(self):
            return None

    session_runtime = voice_web_server._build_session_runtime(Session())

    assert isinstance(session_runtime, VoiceSessionWebSocketSession)
    await runtime.close()


async def test_removed_legacy_runtime_flag_cannot_restore_the_old_production_path(monkeypatch):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    monkeypatch.setenv("VOICEAGENT_REALTIME_RUNTIME", "legacy")

    class Session:
        session_id = "legacy-rollback-session"
        client_hello = None
        authenticated_identity = TEST_ENDPOINT_IDENTITY
        authorized_thread_id = session_id

        async def send(self, frame):
            del frame

        async def receive(self):
            if False:
                yield

        async def close(self):
            return None

    session_runtime = voice_web_server._build_session_runtime(Session())

    assert isinstance(session_runtime, VoiceSessionWebSocketSession)
    await runtime.close()


async def test_native_realtime_engine_is_not_a_phase1_production_selection(monkeypatch):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    monkeypatch.setenv("VOICEAGENT_REALTIME_RUNTIME", "1")
    monkeypatch.setenv("VOICEAGENT_REALTIME_ENGINE", "native")
    monkeypatch.setenv("VOICEAGENT_NATIVE_REALTIME_API_KEY", "native-key")
    monkeypatch.setenv("VOICEAGENT_NATIVE_REALTIME_MODEL", "gpt-realtime-test")

    class Session:
        session_id = "native-realtime-session"
        authenticated_identity = TEST_ENDPOINT_IDENTITY
        authorized_thread_id = session_id

        async def send(self, frame):
            del frame

        async def receive(self):
            if False:
                yield

        async def close(self):
            return None

    with pytest.raises(ValueError, match="only supports the cascaded engine"):
        voice_web_server._build_session_runtime(Session())

    await runtime.close()


async def test_input_evidence_reader_and_deletion_use_actual_session_identity(monkeypatch):
    from server.conversation_journal import (
        ConversationItemDraft,
        ConversationItemKind,
        ConversationItemStatus,
        TextContent,
    )
    from server.conversation_journal.input_evidence import (
        InputEvidenceRecorder,
        input_evidence_scope,
    )
    from server.core.interaction_context import InteractionContext
    from server.observability.telemetry import TelemetryIdentity

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    ctx = InteractionContext(tenant_id="ticket-tenant", user_id="public-user", device_id="device",
                             voice_session_id="resumed-session", thread_id="existing-thread", turn_id="turn", generation=1)
    recorder = InputEvidenceRecorder(runtime.journal, context=ctx, on_failure=lambda _: None)
    try:
        await runtime.journal.append(ConversationItemDraft(
            item_id="keep-shared-thread", context=ctx, kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMMITTED, producer="test", content=(TextContent("shared conversation"),)))
        await recorder.offer("input", "asr_revision", {"suffix": "后续问题"}).committed
        runtime.telemetry.bind(TelemetryIdentity(tenant_id=ctx.tenant_id, user_id=ctx.user_id, device_id=ctx.device_id,
                              voice_session_id=ctx.voice_session_id, thread_id=ctx.thread_id)).record("interaction.collection_ready")
        result = await voice_web_server._read_session_input_evidence(ctx.voice_session_id, 0, 1)
        assert result["status"] == "available"
        assert result["records"][0]["detail"]["suffix"] == "后续问题"
        empty_tail = await voice_web_server._read_session_input_evidence(ctx.voice_session_id, 1, 1)
        assert empty_tail["status"] == "available" and empty_tail["records"] == []
        missing = await voice_web_server._read_session_input_evidence("missing", 100, 1)
        assert missing["status"] == "not_collected"
        deleted = await voice_web_server._delete_session_history([ctx.voice_session_id])
        assert deleted["deleted_evidence_threads"] == 1
        assert deleted["deleted_threads"] == 0
        assert await runtime.journal.read(input_evidence_scope(ctx)) == ()
        from server.conversation_journal import JournalScope
        assert len(await runtime.journal.read(JournalScope.from_context(ctx))) == 1
    finally:
        await recorder.close()
        await runtime.close()
