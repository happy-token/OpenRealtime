from __future__ import annotations

import json

from server.realtime import AudioEncoding
from server.realtime.profile import PluginKind
from server.realtime.profile.builtin import BuiltinCascadedBindings, resolve_builtin_profile


def test_builtin_cascaded_profile_resolves_every_replaceable_capability() -> None:
    bindings = BuiltinCascadedBindings(
        vad=object(),
        asr=object(),
        turn_manager=object(),
        brain=object(),
        speech_renderer=object(),
        tts=object(),
    )

    profile = resolve_builtin_profile(bindings)

    assert profile.negotiated_input_format is not None
    assert profile.negotiated_input_format.encoding is AudioEncoding.PCM_S16LE
    assert profile.negotiated_input_format.sample_rate_hz == 16_000
    assert {plugin.selection.slot for plugin in profile.plugins} == {
        PluginKind.VAD,
        PluginKind.ASR,
        PluginKind.TURN_MANAGER,
        PluginKind.BRAIN,
        PluginKind.SPEECH_RENDERER,
        PluginKind.TTS,
    }
    assert {
        plugin.selection.slot: plugin.binding for plugin in profile.plugins
    } == {
        PluginKind.VAD: bindings.vad,
        PluginKind.ASR: bindings.asr,
        PluginKind.TURN_MANAGER: bindings.turn_manager,
        PluginKind.BRAIN: bindings.brain,
        PluginKind.SPEECH_RENDERER: bindings.speech_renderer,
        PluginKind.TTS: bindings.tts,
    }
    assert len(profile.diagnostic_digest) == 64


def test_builtin_profile_can_be_selected_from_versioned_json_file(tmp_path) -> None:
    bindings = BuiltinCascadedBindings(
        vad=object(),
        asr=object(),
        turn_manager=object(),
        brain=object(),
        speech_renderer=object(),
        tts=object(),
    )
    profile_path = tmp_path / "realtime-profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "engine_kind": "cascaded",
                "plugins": [
                    {
                        "slot": "vad",
                        "plugin_id": "builtin.vad",
                        "plugin_version": "1.0.0",
                        "requested_data_grants": ["input_audio_processed"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    profile = resolve_builtin_profile(bindings, profile_path=profile_path)

    assert len(profile.plugins) == 1
    assert profile.plugins[0].selection.slot is PluginKind.VAD
    assert profile.plugins[0].binding is bindings.vad
