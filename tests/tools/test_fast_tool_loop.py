from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemKind,
    InMemoryConversationJournal,
    JournalScope,
    TextContent,
)
from server.observability.telemetry import (
    InMemoryTelemetryStore,
    RuntimeTelemetry,
    TelemetryIdentity,
    TelemetryOutcome,
)
from server.tools import fast_loop
from server.tools.fast_loop import FastToolBudget, FastToolLoop, ToolExecutionResult
from server.tools.policy_gateway import (
    DefaultToolPolicyGateway,
    Deny,
    ToolExecutor,
    ToolPolicyContext,
)
from server.tools.registry import ToolRegistry
from server.tools.web_search_source import WebSearchToolSource
from server.web_search.deterministic_web_search import DeterministicWebSearch
from tests.tools.test_policy_gateway import registry, request


@pytest.mark.asyncio
async def test_fast_loop_journals_intent_before_side_effect_and_result_after() -> None:
    journal = InMemoryConversationJournal()
    observed_kinds: list[list[ConversationItemKind]] = []

    async def handler(arguments: dict) -> str:
        del arguments
        items = await journal.read(JournalScope.from_context(request().context))
        observed_kinds.append([item.kind for item in items])
        return "sunny"

    tools = registry(handler)
    gateway = DefaultToolPolicyGateway(tools)
    loop = FastToolLoop(
        gateway=gateway,
        executor=ToolExecutor(tools, gateway),
        journal=journal,
        budget=FastToolBudget(max_calls=2, max_elapsed_seconds=1),
    )

    outcome = await loop.handle(request(), ToolPolicyContext())
    items = await journal.read(JournalScope.from_context(request().context))

    assert outcome == ToolExecutionResult(success=True, output="sunny")
    assert observed_kinds == [[ConversationItemKind.TOOL_REQUESTED]]
    assert [item.kind for item in items] == [
        ConversationItemKind.TOOL_REQUESTED,
        ConversationItemKind.TOOL_RESULT,
    ]
    assert loop.committed_tool_items("call-1") == tuple(items)
    assert any(
        isinstance(content, TextContent) and content.text == "sunny"
        for content in items[-1].content
    )


@pytest.mark.asyncio
async def test_fast_loop_records_policy_and_execution_latency_without_arguments() -> None:
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store)
    await runtime.start()
    telemetry = runtime.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="browser",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )

    async def handler(arguments: dict) -> str:
        return str(arguments)

    tools = registry(handler)
    gateway = DefaultToolPolicyGateway(tools)
    loop = FastToolLoop(
        gateway=gateway,
        executor=ToolExecutor(tools, gateway),
        journal=InMemoryConversationJournal(),
        telemetry=telemetry,
    )

    outcome = await loop.handle(request(), ToolPolicyContext())
    await runtime.flush()
    detail = await store.session_detail("voice-1")

    assert isinstance(outcome, ToolExecutionResult)
    assert detail is not None
    spans = {event.name: event for event in detail.events}
    assert spans["tool.policy.evaluate"].outcome is TelemetryOutcome.OK
    assert spans["tool.execute"].outcome is TelemetryOutcome.OK
    assert spans["tool.execute"].call_id == "call-1"
    assert "arguments" not in str(spans["tool.execute"].to_dict())
    await runtime.close()


@pytest.mark.asyncio
async def test_fast_loop_reports_an_unavailable_search_as_failed_execution() -> None:
    tools = ToolRegistry([WebSearchToolSource(DeterministicWebSearch())])
    gateway = DefaultToolPolicyGateway(tools)
    loop = FastToolLoop(
        gateway=gateway,
        executor=ToolExecutor(tools, gateway),
        journal=InMemoryConversationJournal(),
    )
    search_request = replace(
        request(),
        tool_name="search_web",
        arguments={"query": "北京天气"},
    )

    outcome = await loop.handle(search_request, ToolPolicyContext())

    assert outcome == ToolExecutionResult(
        success=False,
        error_code="execution_failed",
        safe_message="工具执行失败。",
    )


@pytest.mark.asyncio
async def test_fast_loop_enforces_per_turn_call_count_and_timeout() -> None:
    async def fast(arguments: dict) -> str:
        return str(arguments)

    tools = registry(fast)
    gateway = DefaultToolPolicyGateway(tools)
    loop = FastToolLoop(
        gateway=gateway,
        executor=ToolExecutor(tools, gateway),
        journal=InMemoryConversationJournal(),
        budget=FastToolBudget(max_calls=1, max_elapsed_seconds=1),
    )

    first = await loop.handle(request(), ToolPolicyContext())
    second = await loop.handle(
        request(call_id="call-2"),
        ToolPolicyContext(),
    )

    assert isinstance(first, ToolExecutionResult)
    assert isinstance(second, Deny)
    assert second.reason_code == "fast_tool_call_limit"

    async def slow(arguments: dict) -> str:
        del arguments
        await asyncio.sleep(0.05)
        return "late"

    slow_tools = registry(slow)
    slow_gateway = DefaultToolPolicyGateway(slow_tools)
    slow_loop = FastToolLoop(
        gateway=slow_gateway,
        executor=ToolExecutor(slow_tools, slow_gateway),
        journal=InMemoryConversationJournal(),
        budget=FastToolBudget(max_calls=1, max_elapsed_seconds=0.001),
    )

    timed_out = await slow_loop.handle(request(), ToolPolicyContext())

    assert timed_out == ToolExecutionResult(
        success=False,
        error_code="timeout",
        safe_message="工具执行超时，已停止等待。",
    )


@pytest.mark.asyncio
async def test_tool_budget_starts_at_first_tool_action_not_llm_planning_time(
    monkeypatch,
) -> None:
    now = 0.0
    monkeypatch.setattr(fast_loop.time, "monotonic", lambda: now)

    async def handler(arguments: dict) -> str:
        del arguments
        return "sunny"

    tools = registry(handler)
    gateway = DefaultToolPolicyGateway(tools)
    loop = FastToolLoop(
        gateway=gateway,
        executor=ToolExecutor(tools, gateway),
        journal=InMemoryConversationJournal(),
        budget=FastToolBudget(max_calls=1, max_elapsed_seconds=3),
    )
    now = 10.0  # Simulate a slow first LLM tool-planning request.

    outcome = await loop.handle(request(), ToolPolicyContext())

    assert outcome == ToolExecutionResult(success=True, output="sunny")


@pytest.mark.asyncio
async def test_fast_loop_records_cancelled_result_when_tool_execution_is_cancelled() -> None:
    journal = InMemoryConversationJournal()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocking(arguments: dict) -> str:
        del arguments
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    tools = registry(blocking)
    gateway = DefaultToolPolicyGateway(tools)
    loop = FastToolLoop(
        gateway=gateway,
        executor=ToolExecutor(tools, gateway),
        journal=journal,
    )
    task = asyncio.create_task(loop.handle(request(), ToolPolicyContext()))
    await started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled.is_set()
    items = await journal.read(JournalScope.from_context(request().context))
    assert [item.kind for item in items] == [
        ConversationItemKind.TOOL_REQUESTED,
        ConversationItemKind.TOOL_RESULT,
    ]
    assert items[-1].status.value == "cancelled"
