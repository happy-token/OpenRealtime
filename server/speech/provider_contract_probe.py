"""Bounded, trusted real-vendor ASR/TTS contract probe for one saved instance.

Invoked only by the authenticated Web API. JSON credentials arrive on stdin;
stdout contains a small summary, never text, audio, credentials, or vendor errors.
This module does not load or execute user bridge code.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from websockets.exceptions import InvalidStatus

from server.speech.plugins.bailian_tts import BailianTtsEngine
from server.speech.plugins.bailian_asr import BailianAsrEngine
from server.speech.plugins.doubao_asr import DoubaoAsrEngine
from server.speech.plugins.doubao_tts_direct import DoubaoDirectTtsEngine

_TEXT_FIRST = "你好，今天我们一起测试实时语音合成。"
_TEXT_SECOND = "现在继续说第二句话，确认文本和音频可以同时流动。"
_ASR_FIXTURE_TEXT = "你好，今天我们一起测试实时语音识别，请持续显示文字。"
_MAX_AUDIO_BYTES = 1_600_000
_ASR_RATE = 16_000
_ASR_FRAME_BYTES = 3_200


async def probe_tts(provider: str, api_key: str) -> dict[str, Any]:
    """Require audio before text input is closed in a single vendor session."""

    engine = (DoubaoDirectTtsEngine(api_key=api_key) if provider == "doubao"
              else BailianTtsEngine(api_key=api_key))
    release_second_text = asyncio.Event()
    text_finished = False
    first_text_at: float | None = None
    first_audio_ms: float | None = None
    audio_bytes = 0
    final_seen = False

    async def text_stream():
        nonlocal text_finished, first_text_at
        first_text_at = time.monotonic()
        yield _TEXT_FIRST
        yield _TEXT_SECOND
        await release_second_text.wait()
        text_finished = True

    try:
        async with asyncio.timeout(25):
            async for chunk in engine.synthesize_duplex(text_stream()):
                if chunk.pcm16:
                    if first_audio_ms is None:
                        if text_finished or first_text_at is None:
                            return {"ok": False, "message": "首音未在文本流结束前返回"}
                        first_audio_ms = round((time.monotonic() - first_text_at) * 1000, 1)
                        release_second_text.set()
                    audio_bytes += len(chunk.pcm16)
                    if audio_bytes > _MAX_AUDIO_BYTES:
                        return {"ok": False, "message": "测试音频超过上限"}
                final_seen |= chunk.is_final
    except TimeoutError:
        return {"ok": False, "message": "文本流未结束前未收到音频"}
    finally:
        release_second_text.set()
        await engine.close()
    if not text_finished or not final_seen or first_audio_ms is None:
        return {"ok": False, "message": "双流式输出缺少文本或音频结束事件"}
    return {"ok": True, "message": "双流式文本与音频已验证", "firstOutputMs": first_audio_ms}


async def probe_asr(api_key: str, fixture_tts_key: str, *, provider: str = "doubao",
                    base_url: str | None = None, model: str = "") -> dict[str, Any]:
    """Synthesize a fixed speech fixture, then require partial and final ASR."""

    tts = DoubaoDirectTtsEngine(api_key=fixture_tts_key, sample_rate_hz=_ASR_RATE)
    try:
        async with asyncio.timeout(15):
            fixture = await tts.synthesize(_ASR_FIXTURE_TEXT)
    except InvalidStatus as error:
        if error.response.status_code in {401, 403}:
            return {"ok": False, "message": "平台测试音频服务鉴权失败"}
        raise
    finally:
        await tts.close()
    if not fixture.pcm16 or len(fixture.pcm16) > _MAX_AUDIO_BYTES:
        return {"ok": False, "message": "无法生成有界 ASR 测试音频"}

    engine = (DoubaoAsrEngine(api_key=api_key, sample_rate_hz=_ASR_RATE) if provider == "doubao"
              else BailianAsrEngine(api_key=api_key, base_url=base_url,
                                    model=model or "qwen3-asr-flash-realtime"))
    session = await engine.start_session()
    first_frame_at: float | None = None
    first_text_ms: float | None = None
    final_at: float | None = None
    partial_seen = False
    try:
        async with asyncio.timeout(25):
            for offset in range(0, len(fixture.pcm16), _ASR_FRAME_BYTES):
                frame = fixture.pcm16[offset:offset + _ASR_FRAME_BYTES]
                now = time.monotonic()
                first_frame_at = first_frame_at or now
                await session.push_audio(frame, sample_rate_hz=_ASR_RATE)
                await asyncio.sleep(len(frame) / 2 / _ASR_RATE)
                snapshot = await session.snapshot()
                if snapshot.text and not snapshot.is_sentence_end:
                    partial_seen = True
                    if first_text_ms is None:
                        first_text_ms = round((time.monotonic() - first_frame_at) * 1000, 1)
                if snapshot.text and snapshot.is_sentence_end:
                    final_at = time.monotonic()
            for _ in range(15):
                if final_at is not None:
                    break
                await session.push_audio(b"\x00\x00" * 3200, sample_rate_hz=_ASR_RATE)
                await asyncio.sleep(0.2)
                snapshot = await session.snapshot()
                if snapshot.text and not snapshot.is_sentence_end:
                    partial_seen = True
                    if first_text_ms is None and first_frame_at is not None:
                        first_text_ms = round((time.monotonic() - first_frame_at) * 1000, 1)
                if snapshot.text and snapshot.is_sentence_end:
                    final_at = time.monotonic()
    except TimeoutError:
        return {"ok": False, "message": "ASR 未在时限内输出最终文本"}
    finally:
        await session.close()
    if not partial_seen or final_at is None:
        return {"ok": False, "message": "ASR 未同时输出 partial 与 final 文本"}
    return {"ok": True, "message": "partial/final 文本已验证", "firstOutputMs": first_text_ms}


async def execute_probe(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("invalid probe request")
    capability = payload.get("capability")
    provider = payload.get("provider")
    key = payload.get("apiKey")
    if not isinstance(key, str) or not 8 <= len(key) <= 512:
        raise ValueError("invalid credential")
    try:
        if capability == "tts" and provider in {"doubao", "dashscope"}:
            return await probe_tts(provider, key)
        if capability == "asr" and provider in {"doubao", "dashscope"}:
            fixture_key = payload.get("fixtureTtsKey")
            if not isinstance(fixture_key, str) or not 8 <= len(fixture_key) <= 512:
                raise ValueError("invalid fixture credential")
            return await probe_asr(key, fixture_key, provider=provider,
                                   base_url=payload.get("baseUrl"), model=payload.get("model", ""))
    except InvalidStatus as error:
        if error.response.status_code in {401, 403}:
            return {"ok": False, "message": f"API Key 未通过供应商鉴权（HTTP {error.response.status_code}），请检查个人配置"}
        raise
    raise ValueError("unsupported capability")


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read(4096))
        result = asyncio.run(execute_probe(payload))
    except Exception:  # noqa: BLE001 - never emit vendor errors that may contain credentials
        result = {"ok": False, "message": "供应商实时契约测试失败"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
