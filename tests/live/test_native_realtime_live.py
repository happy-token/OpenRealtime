"""Opt-in smoke test for the real end-to-end Native Realtime provider.

Run with:

    RUN_LIVE_NATIVE_REALTIME=1 \
    VOICEAGENT_NATIVE_REALTIME_API_KEY=<key> \
    VOICEAGENT_NATIVE_REALTIME_MODEL=<model> \
    uv run pytest tests/live/test_native_realtime_live.py -s
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    TextContent,
)
from server.conversation_journal.models import item_from_draft
from server.core.interaction_context import InteractionContext
from server.realtime import (
    AudioDelta,
    DisplayContentDelta,
    ProjectCommittedItem,
    RequestResponse,
    ResponseCompleted,
    ResponseStarted,
    SpokenContentDelta,
    ToolRequested,
)
from server.realtime.native import NativeRealtimeEngine, OpenAiRealtimeProvider
from server.tools.clock_source import ClockToolSource
from server.tools.registry import ToolRegistry

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("RUN_LIVE_NATIVE_REALTIME")
        and os.environ.get("VOICEAGENT_NATIVE_REALTIME_API_KEY")
        and os.environ.get("VOICEAGENT_NATIVE_REALTIME_MODEL")
    ),
    reason="requires explicit Native Realtime live-test credentials",
)


def _context() -> InteractionContext:
    return InteractionContext(
        tenant_id="live-test",
        user_id="live-test",
        device_id="pytest",
        voice_session_id="native-live-test",
        thread_id="native-live-test",
        turn_id="turn-1",
        generation=1,
    )


async def test_live_native_text_turn_streams_text_and_audio() -> None:
    context = _context()
    engine = NativeRealtimeEngine(
        provider=OpenAiRealtimeProvider(
            api_key=os.environ["VOICEAGENT_NATIVE_REALTIME_API_KEY"],
            model=os.environ["VOICEAGENT_NATIVE_REALTIME_MODEL"],
            base_url=os.environ.get(
                "VOICEAGENT_NATIVE_REALTIME_BASE_URL",
                "wss://api.openai.com/v1/realtime",
            ),
            session={"instructions": "请用一句简短中文回答，并输出语音。"},
        )
    )
    conversation = await engine.open(context=context, profile=None)
    try:
        item = item_from_draft(
            ConversationItemDraft(
                item_id="user-live-1",
                context=context,
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="native-live-test",
                content=(TextContent("请说：实时语音链路正常。"),),
            ),
            sequence=1,
            recorded_at=datetime.now(UTC),
        )
        await conversation.send(
            ProjectCommittedItem(
                command_id="project-live-1",
                idempotency_key="project-live-1",
                context=context,
                item=item,
            )
        )
        events = conversation.events()
        await asyncio.wait_for(anext(events), timeout=10)
        response_context = replace(context, response_id="response-live-1")
        started_at = perf_counter()
        await conversation.send(
            RequestResponse(
                command_id="response-live-1",
                idempotency_key="response-live-1",
                context=response_context,
                response_id="response-live-1",
                minimum_thread_sequence=1,
                output_item_id="assistant-live-1",
            )
        )

        emitted = []
        response_started_latency_s: float | None = None
        first_display_latency_s: float | None = None
        first_spoken_latency_s: float | None = None
        first_audio_latency_s: float | None = None
        previous_audio_received_at: float | None = None
        max_audio_gap_s = 0.0
        audio_chunks = 0
        while len(emitted) < 200:
            event = await asyncio.wait_for(anext(events), timeout=30)
            emitted.append(event)
            received_at = perf_counter()
            elapsed_s = received_at - started_at
            if isinstance(event, ResponseStarted) and response_started_latency_s is None:
                response_started_latency_s = elapsed_s
            elif isinstance(event, DisplayContentDelta) and first_display_latency_s is None:
                first_display_latency_s = elapsed_s
            elif isinstance(event, SpokenContentDelta) and first_spoken_latency_s is None:
                first_spoken_latency_s = elapsed_s
            elif isinstance(event, AudioDelta):
                audio_chunks += 1
                if first_audio_latency_s is None:
                    first_audio_latency_s = elapsed_s
                if previous_audio_received_at is not None:
                    max_audio_gap_s = max(
                        max_audio_gap_s,
                        received_at - previous_audio_received_at,
                    )
                previous_audio_received_at = received_at
            if isinstance(event, ResponseCompleted):
                break

        assert any(isinstance(event, DisplayContentDelta) for event in emitted)
        assert any(isinstance(event, SpokenContentDelta) for event in emitted)
        assert any(isinstance(event, AudioDelta) for event in emitted)
        assert isinstance(emitted[-1], ResponseCompleted)
        assert first_audio_latency_s is not None
        assert first_audio_latency_s < 10
        assert response_started_latency_s is not None
        assert first_display_latency_s is not None
        assert first_spoken_latency_s is not None
        print(
            json.dumps(
                {
                    "scenario": "native_text_audio",
                    "response_started_ms": round(response_started_latency_s * 1000, 1),
                    "first_display_ms": round(first_display_latency_s * 1000, 1),
                    "first_spoken_ms": round(first_spoken_latency_s * 1000, 1),
                    "first_audio_ms": round(first_audio_latency_s * 1000, 1),
                    "completed_ms": round((perf_counter() - started_at) * 1000, 1),
                    "audio_chunks": audio_chunks,
                    "max_audio_chunk_gap_ms": round(max_audio_gap_s * 1000, 1),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    finally:
        await conversation.close()


async def test_live_native_tool_call_continues_same_response() -> None:
    context = replace(_context(), voice_session_id="native-live-tool")
    tools = ToolRegistry([ClockToolSource()])
    engine = NativeRealtimeEngine(
        provider=OpenAiRealtimeProvider(
            api_key=os.environ["VOICEAGENT_NATIVE_REALTIME_API_KEY"],
            model=os.environ["VOICEAGENT_NATIVE_REALTIME_MODEL"],
            base_url=os.environ.get(
                "VOICEAGENT_NATIVE_REALTIME_BASE_URL",
                "wss://api.openai.com/v1/realtime",
            ),
            session={
                "instructions": (
                    "用户询问时间时必须先调用 get_current_datetime；"
                    "收到工具结果后用一句简短中文回答并输出语音。"
                )
            },
            tools=tools,
        ),
        tools=tools,
    )
    conversation = await engine.open(context=context, profile=None)
    try:
        user_item = item_from_draft(
            ConversationItemDraft(
                item_id="user-live-tool-1",
                context=context,
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="native-live-test",
                content=(TextContent("上海现在几点？"),),
            ),
            sequence=1,
            recorded_at=datetime.now(UTC),
        )
        await conversation.send(
            ProjectCommittedItem(
                command_id="project-live-tool-user",
                idempotency_key="project-live-tool-user",
                context=context,
                item=user_item,
            )
        )
        events = conversation.events()
        await asyncio.wait_for(anext(events), timeout=10)
        response_context = replace(context, response_id="response-live-tool-1")
        started_at = perf_counter()
        await conversation.send(
            RequestResponse(
                command_id="response-live-tool-1",
                idempotency_key="response-live-tool-1",
                context=response_context,
                response_id="response-live-tool-1",
                minimum_thread_sequence=1,
                output_item_id="assistant-live-tool-1",
            )
        )

        tool_requests = 0
        response_starts = 0
        first_tool_request_s: float | None = None
        first_audio_s: float | None = None
        for _ in range(200):
            event = await asyncio.wait_for(anext(events), timeout=30)
            if isinstance(event, ResponseStarted):
                response_starts += 1
            elif isinstance(event, ToolRequested):
                tool_requests += 1
                if first_tool_request_s is None:
                    first_tool_request_s = perf_counter() - started_at
                tool = tools.get(event.tool_name)
                assert tool is not None
                output = await tool.handler(dict(event.arguments))
                tool_context = replace(response_context, call_id=event.call_id)
                result = item_from_draft(
                    ConversationItemDraft(
                        item_id=f"tool-result-live-{event.call_id}",
                        context=tool_context,
                        kind=ConversationItemKind.TOOL_RESULT,
                        status=ConversationItemStatus.COMPLETED,
                        producer="native-live-test",
                        content=(TextContent(output),),
                    ),
                    sequence=tool_requests + 1,
                    recorded_at=datetime.now(UTC),
                )
                await conversation.send(
                    ProjectCommittedItem(
                        command_id=f"project-live-{event.call_id}",
                        idempotency_key=f"project-live-{event.call_id}",
                        context=tool_context,
                        item=result,
                    )
                )
            elif isinstance(event, AudioDelta) and first_audio_s is None:
                first_audio_s = perf_counter() - started_at
            elif isinstance(event, ResponseCompleted):
                break
        else:
            pytest.fail("Native tool response did not complete within 200 events")

        assert tool_requests == 1
        assert response_starts == 1
        assert first_tool_request_s is not None
        assert first_audio_s is not None
        print(
            json.dumps(
                {
                    "scenario": "native_tool_continuation",
                    "tool_requested_ms": round(first_tool_request_s * 1000, 1),
                    "first_audio_ms": round(first_audio_s * 1000, 1),
                    "completed_ms": round((perf_counter() - started_at) * 1000, 1),
                    "logical_response_starts": response_starts,
                    "tool_requests": tool_requests,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    finally:
        await conversation.close()


async def test_live_native_connection_can_reopen_repeatedly() -> None:
    engine = NativeRealtimeEngine(
        provider=OpenAiRealtimeProvider(
            api_key=os.environ["VOICEAGENT_NATIVE_REALTIME_API_KEY"],
            model=os.environ["VOICEAGENT_NATIVE_REALTIME_MODEL"],
            base_url=os.environ.get(
                "VOICEAGENT_NATIVE_REALTIME_BASE_URL",
                "wss://api.openai.com/v1/realtime",
            ),
        )
    )
    open_latencies_ms = []
    for attempt in range(3):
        started_at = perf_counter()
        conversation = await engine.open(
            context=replace(
                _context(),
                voice_session_id=f"native-live-reopen-{attempt}",
            ),
            profile=None,
        )
        open_latencies_ms.append((perf_counter() - started_at) * 1000)
        await conversation.close()

    assert max(open_latencies_ms) < 10_000
    print(
        json.dumps(
            {
                "scenario": "native_reopen",
                "attempts": len(open_latencies_ms),
                "open_ms": [round(value, 1) for value in open_latencies_ms],
                "max_open_ms": round(max(open_latencies_ms), 1),
            },
            sort_keys=True,
        )
    )
