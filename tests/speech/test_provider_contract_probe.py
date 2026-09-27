from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace

from websockets.exceptions import InvalidStatus

from server.speech import provider_contract_probe
from server.speech.tts import SynthesizedAudioChunk


def test_tts_probe_requires_audio_before_two_chunk_text_input_is_closed(monkeypatch):
    class FakeEngine:
        async def synthesize_duplex(self, text_stream):
            iterator = text_stream.__aiter__()
            assert await anext(iterator)
            assert await anext(iterator)
            yield SynthesizedAudioChunk(pcm16=b"\x01\x00", sample_rate_hz=24000, is_final=False)
            try:
                await anext(iterator)
            except StopAsyncIteration:
                pass
            yield SynthesizedAudioChunk(pcm16=b"", sample_rate_hz=24000, is_final=True)

        async def close(self):
            pass

    monkeypatch.setattr(provider_contract_probe, "DoubaoDirectTtsEngine", lambda **_: FakeEngine())
    result = asyncio.run(provider_contract_probe.probe_tts("doubao", "test-key"))
    assert result["ok"] is True
    assert result["message"] == "双流式文本与音频已验证"
    assert result["firstOutputMs"] >= 0


def test_cli_never_returns_vendor_exception_or_key(monkeypatch, capsys):
    async def fail(_provider, _key):
        raise RuntimeError("upstream rejected secret-key")

    monkeypatch.setattr(provider_contract_probe, "probe_tts", fail)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "capability": "tts", "provider": "doubao", "apiKey": "secret-key",
    })))
    assert provider_contract_probe.main() == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {"ok": False, "message": "供应商实时契约测试失败"}
    assert "secret-key" not in output


def test_asr_probe_reports_vendor_auth_rejection_without_vendor_body_or_key(monkeypatch):
    async def reject(_key, _fixture_key, **_kwargs):
        raise InvalidStatus(SimpleNamespace(status_code=401))

    monkeypatch.setattr(provider_contract_probe, "probe_asr", reject)
    result = asyncio.run(provider_contract_probe.execute_probe({
        "capability": "asr", "provider": "doubao", "apiKey": "private-asr-key",
        "fixtureTtsKey": "platform-fixture-key",
    }))
    assert result == {"ok": False, "message": "API Key 未通过供应商鉴权（HTTP 401），请检查个人配置"}
    assert "private-asr-key" not in json.dumps(result)
