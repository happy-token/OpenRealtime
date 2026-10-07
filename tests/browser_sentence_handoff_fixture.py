"""Loopback-only controlled providers around the real Managed/Core/WS bridge.

No application authentication bypass is added: only this test process exposes
scenario controls. The browser supplies all playback and stop evidence.
"""

from __future__ import annotations

import asyncio
import json
import signal
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import serve

from server.conversation_journal import ConversationItemKind, TextContent
from server.core.turn_content import TurnContent
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.capabilities.speculative_brain import SpeculativeStreamingBrain
from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from server.speech.plugins.doubao_tts_direct import _alignment_chunks
from server.speech.tts import SynthesizedAudioChunk
from server.transport.frame_parsing import parse_inbound_frame
from server.turn_policy.policy import TurnPolicy
from tests.realtime.test_coordinated_turn_manager import Interrupt, start, stop, text
from tests.realtime.test_realtime_websocket_bridge import context
from tests.realtime.test_reply_playback_observation import playing_core
from tests.realtime.test_sentence_permit_actor import ControlledAsr


class Provider:
    def __init__(self, *, pending: bool) -> None:
        self.turns: list[TurnContent] = []
        self.pending = pending
        self.release = asyncio.Event()
        self.cancelled = False
        self.exited = False

    async def stream(self, turn):
        self.turns.append(turn)
        candidate = len(self.turns) == 2
        try:
            yield "第一句。第二句。" if len(self.turns) == 1 else "补充后的回答。"
            if candidate and self.pending:
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    await self.release.wait()
        finally:
            if candidate:
                self.exited = True


class Duplex:
    async def synthesize_duplex(self, texts):
        async for value in texts:
            sentences = [part + "。" for part in value.split("。") if part]
            yield SynthesizedAudioChunk(pcm16=b"\0\0" * (16000 * len(sentences)), sample_rate_hz=16000, is_final=False)
            for index, sentence in enumerate(sentences):
                for chunk in _alignment_chunks({"text": sentence, "words": [{
                    "word": sentence, "startTime": index, "endTime": index + 1,
                }]}, 16000):
                    yield chunk


async def main() -> None:
    stopped = asyncio.Event()
    state: dict = {}
    active = False
    actor = None
    asr = None
    provider = None
    core = None
    cache = None
    initial = []
    endpoint_transport = None

    async def http(connection, request):
        nonlocal actor
        path = urlsplit(request.path).path
        if path == "/start":
            if actor is None or state.get("started"):
                return connection.respond(409, "scenario not ready")
            state["started"] = True
            for frame in initial:
                await endpoint_transport.send(frame)
        elif path == "/trigger":
            if actor is None or state.get("triggered"):
                return connection.respond(409, "scenario not ready")
            state["triggered"] = True
            second = replace(context(), turn_id="supplement", generation=2)
            await start(actor, second)
            await text(actor, asr.latest, ctx=second)
            await stop(actor, second)
        elif path == "/revise":
            if actor is None or state.get("revised"):
                return connection.respond(409, "scenario not ready")
            state["revised"] = True
            asr.latest = "不是，明天不要看，只看今天。"
            await text(actor, asr.latest, revision=2, ctx=replace(context(), turn_id="supplement", generation=2))
        elif path == "/release":
            if provider is not None:
                provider.release.set()
        elif path != "/evidence":
            return None
        delivery = await core._speech_deliveries.get("response:reply") if core is not None else None
        body = json.dumps({**state, "provider_calls": len(provider.turns) if provider else 0,
            "conditional": bool(provider and len(provider.turns) > 1 and provider.turns[1].conditional_handoff),
            "commits": len(asr.commits) if asr else 0,
            "delivered": delivery.delivered_speech_transcript if delivery else None,
            "candidate_cancelled": provider.cancelled if provider else False,
            "candidate_exited": provider.exited if provider else False,
            "pending_owned": bool(cache and any(not task.done() for task in cache._cleanup._retired)),
            "retained_input": any(item.kind is ConversationItemKind.USER_INPUT
                and any(isinstance(part, TextContent) and asr.latest in part.text for part in item.content)
                for item in core._projected_items.values()) if core and asr else False}).encode()
        response = connection.respond(200, body.decode())
        del response.headers["Content-Type"]
        response.headers["Content-Type"] = "application/json"
        return response

    async def handle(socket):
        nonlocal actor, asr, provider, core, cache, active, initial, endpoint_transport
        # Acquire before any await and retain through full cleanup. A browser
        # reconnect must not overwrite another handler's provider ownership.
        if active:
            await socket.close(code=1013, reason="fixture scenario still active")
            return
        active = True
        state.clear()
        state.update(triggered=False, sent=[], received=[], prefetch=[])
        options = parse_qs(urlsplit(socket.request.path).query)
        provider, asr, tts = Provider(pending=options.get("scenario") == ["revoked_pending"]), ControlledAsr(), Duplex()
        asr.latest = "补充一下，明天也要看。"
        kind = options.get("kind", ["text"])[0]
        cache = (SpeculativeSpeechPipeline(brain=provider, tts=tts) if kind == "speech"
            else SpeculativeStreamingBrain(provider))
        manager = CoordinatedTurnManagerCapabilityAdapter(TurnPolicy,
            semantic_interruption_classifier=Interrupt(), response_prefetch_enabled=True,
            sentence_handoff_prefetch_enabled=True, response_prefetcher=cache,
            asr_idle_stop_ms=15, semantic_interruption_idle_ms=5, recovery_timeout_ms=2000)
        core, bridge = await playing_core(brain=cache, tts=cache if kind == "speech" else tts,
            asr=asr, turn_manager=manager, managed=True, precise_stop=True,
            speech_deliveries=InMemorySpeechDeliveryStore())
        actor = core._input_pipeline._turn_manager
        actor._prefetch._observer = lambda operation, generation, details: state["prefetch"].append(operation)
        initial = bridge._transport.frames

        class SocketTransport:
            async def send(self, frame):
                state["sent"].append(frame.type)
                await socket.send(frame.model_dump_json())

        bridge._transport = SocketTransport()
        endpoint_transport = bridge._transport
        pump = None
        try:
            hello = json.loads(await socket.recv())
            assert hello["type"] == "session_hello"
            await socket.send(json.dumps({"type": "session_ack", "session_id": "sentence-real-ws",
                "resumed": False, "protocol_version": 2, "resume_token": "fixture", "output_epoch": "epoch"}))
            await socket.send(json.dumps({"type": "session_capabilities", "server_asr": False,
                "server_tts": True, "assistant_text_streaming": True, "user_transcript_streaming": False}))
            # The application connects before the user opens the microphone.
            # Scenario PCM is released only by the test after that real action.
            async def drain():
                async for event in bridge._conversation.events():
                    await bridge.handle_event(event)
            pump = asyncio.create_task(drain())
            async for raw in socket:
                value = json.loads(raw)
                state["received"].append(value)
                # Session negotiation/config belongs to the fixture. Actual
                # playback evidence always uses the production parser/bridge.
                if value["type"] in {"playback_progress", "playback_progress_v2", "output_stop_result"}:
                    frame = parse_inbound_frame(raw)
                    assert frame is not None
                    await bridge.handle_inbound(frame)
        finally:
            actor = None
            provider.release.set()
            if pump is not None:
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)
            try:
                state["close_stage"] = "bridge"
                await bridge.close()
                state["close_stage"] = "conversation"
                await bridge._conversation.close()
            except Exception as error:
                state["close_error"] = str(error)
                raise
            state["closed"] = True
            state["close_stage"] = "done"
            active = False

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    async with serve(handle, "127.0.0.1", 0, process_request=http) as server:
        print(json.dumps({"port": server.sockets[0].getsockname()[1]}), flush=True)
        await stopped.wait()


if __name__ == "__main__":
    asyncio.run(main())
