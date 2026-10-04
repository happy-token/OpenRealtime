from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from server.core.interaction_context import InteractionContext
from server.realtime.capabilities.speech_renderer import DeterministicSpeechRenderer
from server.realtime.capabilities.turn_manager import (
    DialogueStateChanged,
    LegacyTurnManagerCapabilityAdapter,
    ObserveVadEvent,
)
from server.realtime.capabilities.vad import VadSpeechStarted
from server.realtime.cascaded.pipeline import CascadedPipeline, CascadedPipelineBindings
from server.realtime.profile.models import (
    FailurePolicy,
    PluginConfigSchema,
    PluginKind,
    PluginManifest,
    PluginPlacement,
)
from server.realtime.profile.registry import RegisteredPlugin
from server.turn_policy.policy import Transition
from server.turn_policy.signals import Signal
from server.turn_policy.states import DialogueState


def context():
    return InteractionContext(
        tenant_id="test",
        user_id="alice",
        device_id="browser",
        voice_session_id="voice-one",
        thread_id="thread-one",
        turn_id="turn-one",
        generation=1,
    )


class Session:
    def __init__(self):
        self.closed = asyncio.Event()

    async def send(self, command):
        pass

    async def events(self):
        await self.closed.wait()
        if False:
            yield None

    async def close(self):
        self.closed.set()


class Provider:
    def __init__(self):
        self.opened = []

    async def open(self, *, context, config=None):
        session = Session()
        self.opened.append((context, config, session))
        return session


def bindings():
    return CascadedPipelineBindings(
        vad=Provider(),
        asr=Provider(),
        turn_manager=Provider(),
        brain=Provider(),
        tts=Provider(),
        speech_renderer=DeterministicSpeechRenderer(),
    )


@pytest.mark.asyncio
async def test_custom_turn_manager_is_selected_configured_and_closed(tmp_path):
    baseline = bindings()
    replacement = Provider()
    plugin = RegisteredPlugin(
        manifest=PluginManifest(
            plugin_id="custom.turns",
            plugin_version="1.0.0",
            plugin_kind=PluginKind.TURN_MANAGER,
            contract_version=1,
            placement=PluginPlacement.IN_PROCESS,
            capabilities=frozenset({"turn_management"}),
            latency_budget_ms=20,
            audio_formats=(),
            approved_data_grants=frozenset(),
            config_schema=PluginConfigSchema(
                {
                    "type": "object",
                    "properties": {"idle_ms": {"type": "integer"}},
                    "additionalProperties": False,
                }
            ),
            allowed_failure_policies=frozenset({FailurePolicy.FAIL}),
            default_failure_policy=FailurePolicy.FAIL,
        ),
        binding=replacement,
    )
    profile_path = tmp_path / "pipeline.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "engine_kind": "cascaded",
                "plugins": [
                    {
                        "slot": "turn_manager",
                        "plugin_id": "custom.turns",
                        "plugin_version": "1.0.0",
                        "config": {"idle_ms": 120},
                    },
                ],
            }
        )
    )
    pipeline = CascadedPipeline.assemble(baseline, profile_path=profile_path, plugins=(plugin,))
    first = await pipeline.engine.open(context=context(), profile=pipeline.profile)
    second = await pipeline.engine.open(
        context=replace(context(), voice_session_id="voice-two"), profile=pipeline.profile
    )
    assert not baseline.turn_manager.opened
    assert len(replacement.opened) == 2
    assert replacement.opened[0][1] == {"idle_ms": 120}
    assert replacement.opened[0][2] is not replacement.opened[1][2]
    await first.close()
    await second.close()
    assert all(session.closed.is_set() for _, _, session in replacement.opened)


def test_invalid_binding_fails_before_opening_audio():
    baseline = bindings()
    with pytest.raises(TypeError, match="turn_manager binding must expose open"):
        CascadedPipeline.assemble(replace(baseline, turn_manager=object()))
    assert not baseline.asr.opened


class CustomPolicy:
    """A structural conformer with no inheritance from the builtin TurnPolicy."""

    def __init__(self):
        self.state = DialogueState.IDLE

    async def evaluate(self, signal, *, generation):
        if signal is Signal.USER_SPEECH_ONSET:
            self.state = DialogueState.LISTEN
            return Transition("custom_onset", self.state, None)
        return None


@pytest.mark.asyncio
async def test_state_policy_can_be_replaced_without_replacing_endpoint_guards():
    provider = LegacyTurnManagerCapabilityAdapter(CustomPolicy)
    session = await provider.open(context=context())
    untouched = await provider.open(context=replace(context(), voice_session_id="voice-two"))
    try:
        await session.send(
            ObserveVadEvent(event=VadSpeechStarted(context=context(), audio_timestamp_us=0))
        )
        event = await asyncio.wait_for(anext(session.events()), timeout=1)
        assert isinstance(event, DialogueStateChanged)
        assert event.transition == "custom_onset"
        assert event.to_state is DialogueState.LISTEN
        assert untouched._policy.state is DialogueState.IDLE
    finally:
        await session.close()
        await untouched.close()
