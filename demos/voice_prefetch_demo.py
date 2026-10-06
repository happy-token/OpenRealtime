"""Live JEV + reply-LLM prefetch comparison with synthetic ASR/VAD, no TTS.

Source local server environment before running. Timings end at server text,
not client playback; the small sample is a smoke check, not a P95 estimate.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from demos.voice_web_server import _build_llm_client
from server.brain.chat_brain import ChatBrain
from server.core.interaction_context import InteractionContext
from server.core.turn_content import TurnContent
from server.realtime.capabilities.asr import AsrEndpointHint, AsrTranscriptFinal
from server.realtime.capabilities.brain_streaming import BrainStreamingAdapter
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    ObserveAsrEvent,
    ObserveVadEvent,
    UserTurnCommitted,
)
from server.realtime.capabilities.vad import VadSpeechStarted, VadSpeechStopped
from server.turn_policy.plugins.jev_classifier import JevClient, JevEotClassifier


async def run_case(enabled: bool, jev: JevClient) -> dict:
    ctx = InteractionContext("demo", "demo", "demo", "prefetch", "prefetch", "prefetch", 1)
    transcript = "请用一句话介绍上海。"
    llm = _build_llm_client()
    base = BrainStreamingAdapter(ChatBrain(llm))
    calls = []
    events = []

    class Counted:
        async def stream(self, turn):
            calls.append(time.perf_counter())
            async for delta in base.stream(turn):
                yield delta

    brain = SpeculativeStreamingBrain(
        Counted(),
        observer=lambda operation, turn, attributes: events.append(
            {"operation": operation, **attributes}
        ),
    )
    session = await CoordinatedTurnManagerCapabilityAdapter(
        semantic_chunks_enabled=True,
        response_prefetch_enabled=enabled,
        response_prefetcher=brain,
        eot_classifier=JevEotClassifier(jev),
    ).open(context=ctx)
    stream = session.events()
    response_stream = None
    stopped_at = None
    try:
        async with asyncio.timeout(30):
            await session.send(
                ObserveVadEvent(event=VadSpeechStarted(context=ctx, audio_timestamp_us=0))
            )
            await session.send(
                ObserveAsrEvent(event=AsrEndpointHint(context=ctx, revision=1, text=transcript))
            )
            stopped_at = time.perf_counter()
            await session.send(
                ObserveVadEvent(
                    event=VadSpeechStopped(
                        context=ctx, audio_timestamp_us=100_000, silence_duration_us=300_000
                    )
                )
            )
            async for event in stream:
                if isinstance(event, AsrCommitRequested):
                    await session.send(
                        ObserveAsrEvent(
                            event=AsrTranscriptFinal(
                                context=event.context,
                                revision=2,
                                text=transcript,
                                reason="demo_final",
                            )
                        )
                    )
                elif isinstance(event, UserTurnCommitted):
                    committed_at = time.perf_counter()
                    response_stream = brain.stream(
                        TurnContent(text=event.text, generation=event.context.generation)
                    )
                    first = await anext(response_stream)
                    assert first and len(calls) == 1
                    return {
                        "prefetch_enabled": enabled,
                        "reply_model": getattr(llm, "_model", "unknown"),
                        "stop_to_commit_ms": round((committed_at - stopped_at) * 1000, 1),
                        "stop_to_server_first_text_ms": round(
                            (time.perf_counter() - stopped_at) * 1000, 1
                        ),
                        "reply_requests": len(calls),
                        "cache_events": events,
                        "scope": "synthetic ASR/VAD, live JEV and reply LLM; no TTS/client playback",
                    }
            raise RuntimeError("No committed user input")
    finally:
        if response_stream is not None:
            await response_stream.aclose()
        await stream.aclose()
        await session.close()


async def main() -> None:
    jev = JevClient(
        api_key=os.environ.get("JEV_API_KEY", ""),
        model=os.environ.get("VOICEAGENT_JEV_MODEL", "jev-1.13.0"),
        timeout_s=float(os.environ.get("VOICEAGENT_JEV_TIMEOUT_MS", "2000")) / 1000,
        reuse_connections=True,
    )
    try:
        for enabled in (False, True):
            print(json.dumps(await run_case(enabled, jev), ensure_ascii=False), flush=True)
    finally:
        await jev.close()


if __name__ == "__main__":
    asyncio.run(main())
