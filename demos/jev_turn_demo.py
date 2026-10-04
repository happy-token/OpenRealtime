"""Live Jev + coordinator smoke demo using synthetic VAD/ASR events (no microphone)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict

from server.core.interaction_context import InteractionContext
from server.realtime.capabilities.asr import AsrTranscriptDelta, AsrTranscriptFinal
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    AsrDiscardRequested,
    AssistantYieldRequested,
    ObserveAsrEvent,
    ObserveAssistantSpokenText,
    ObserveAssistantYielded,
    ObserveSystemResponseStarted,
    ObserveVadEvent,
    UserTurnCommitted,
)
from server.realtime.capabilities.vad import VadSpeechStarted, VadSpeechStopped
from server.turn_policy.coordination import DefaultTurnCoordinationPolicy
from server.turn_policy.plugins.jev_classifier import (
    JevChoice,
    JevClient,
    JevEotClassifier,
    JevSemanticInterruptionClassifier,
)


async def run_case(name: str, transcript: str, playback: str | None) -> dict[str, object]:
    decisions: list[JevChoice] = []
    client = JevClient(
        api_key=os.environ.get("JEV_API_KEY", ""),
        model=os.environ.get("VOICEAGENT_JEV_MODEL", "jev-1.13.0"),
        timeout_s=float(os.environ.get("VOICEAGENT_JEV_TIMEOUT_MS", "2000")) / 1000,
        observer=decisions.append,
    )
    ctx = InteractionContext("demo", "demo", "demo", name, name, name, 1)
    provider = CoordinatedTurnManagerCapabilityAdapter(
        coordination_policy_factory=lambda: DefaultTurnCoordinationPolicy(
            backchannel_confidence=float(
                os.environ.get("VOICEAGENT_BACKCHANNEL_CONFIDENCE", "0.95")
            ),
        ),
        eot_classifier=JevEotClassifier(
            client,
            min_confidence=float(os.environ.get("VOICEAGENT_JEV_EOT_MIN_CONFIDENCE", "0.8")),
        ),
        semantic_interruption_classifier=JevSemanticInterruptionClassifier(client),
        semantic_interruption_idle_ms=20,
        semantic_interruption_timeout_ms=float(os.environ.get("VOICEAGENT_JEV_TIMEOUT_MS", "2000")),
        classifier_timeout_ms=float(os.environ.get("VOICEAGENT_JEV_TIMEOUT_MS", "2000")),
        recovery_timeout_ms=10000,
    )
    session = await provider.open(context=ctx)
    stream = session.events()
    started = time.perf_counter()
    yielded = False
    try:
        if playback is not None:
            await session.send(ObserveSystemResponseStarted(context=ctx, response_id="old"))
            await session.send(ObserveAssistantSpokenText(context=ctx, text=playback))
        await session.send(
            ObserveVadEvent(event=VadSpeechStarted(context=ctx, audio_timestamp_us=0))
        )
        await session.send(
            ObserveAsrEvent(
                event=AsrTranscriptDelta(
                    context=ctx,
                    revision=1,
                    delta=transcript,
                    accumulated_text=transcript,
                    audio_timestamp_us=100000,
                )
            )
        )
        await session.send(
            ObserveVadEvent(
                event=VadSpeechStopped(
                    context=ctx,
                    audio_timestamp_us=200000,
                    silence_duration_us=300000,
                )
            )
        )
        async with asyncio.timeout(12):
            async for event in stream:
                if isinstance(event, AssistantYieldRequested):
                    yielded = True
                    await session.send(ObserveAssistantYielded(context=event.context))
                elif isinstance(event, AsrCommitRequested):
                    await session.send(
                        ObserveAsrEvent(
                            event=AsrTranscriptFinal(
                                context=ctx,
                                revision=2,
                                text=transcript,
                                reason="demo_final",
                            )
                        )
                    )
                elif isinstance(event, UserTurnCommitted):
                    outcome = "committed"
                    break
                elif isinstance(event, AsrDiscardRequested):
                    outcome = "discarded"
                    break
            else:
                raise RuntimeError("coordinator ended without a decision")
        return {
            "case": name,
            "outcome": outcome,
            "yield_requested": yielded,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "decisions": [asdict(decision) for decision in decisions],
            "eot_model_result_observed": any(
                {label for label, _ in decision.probabilities}
                == {"complete", "incomplete", "uncertain"}
                for decision in decisions
            ),
            "interruption_model_result_observed": any(
                "interrupt" in dict(decision.probabilities) for decision in decisions
            ),
            "note": "synthetic ASR/VAD and immediate yield acknowledgement; no actual playback",
        }
    finally:
        await stream.aclose()
        await session.close()


async def main() -> None:
    for name, transcript, playback in (
        ("normal", "请查一下上海明天的天气", None),
        ("correction", "地点弄错了，我说的是上海，帮我重新查一下", "下面是北京明天的天气预报"),
        ("backchannel", "嗯，我在听，你继续讲", "下面介绍三个不同的方案"),
    ):
        print(
            json.dumps(await run_case(name, transcript, playback), ensure_ascii=False), flush=True
        )


if __name__ == "__main__":
    asyncio.run(main())
