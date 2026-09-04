from server.gpt_voice_reference import (
    CallTool,
    DelegateTask,
    EndSession,
    InMemoryRealtimeSession,
    InMemoryToolExecutor,
    InMemoryWorkerManager,
    OpenRealtime,
    RequireConfirmation,
    Speak,
    VoiceAgent,
)


def test_legacy_voice_agent_name_aliases_open_realtime() -> None:
    assert VoiceAgent is OpenRealtime


async def test_direct_turn_speaks_without_starting_tool_or_worker() -> None:
    realtime = InMemoryRealtimeSession([Speak("你好，我在。")])
    agent = OpenRealtime(realtime=realtime)

    events = await agent.submit_turn("你好")

    assert [(event.type, event.text) for event in events] == [
        ("speech.requested", "你好，我在。"),
    ]
    assert agent.snapshot().active_tool_calls == ()
    assert agent.snapshot().active_workers == ()


async def test_complex_turn_delegates_without_blocking_and_speaks_when_worker_finishes() -> None:
    realtime = InMemoryRealtimeSession(
        [
            DelegateTask(task="分析整个代码库", acknowledgement="我先在后台分析。"),
            Speak("分析完成：入口在 server/kernel。"),
        ]
    )
    workers = InMemoryWorkerManager()
    agent = OpenRealtime(realtime=realtime, workers=workers)

    accepted = await agent.submit_turn("帮我分析整个代码库")

    assert [(event.type, event.text) for event in accepted] == [
        ("speech.requested", "我先在后台分析。"),
        ("worker.started", None),
    ]
    assert agent.snapshot().active_workers == ("worker-1",)

    completed = await agent.complete_worker("worker-1", result="入口在 server/kernel")

    assert [(event.type, event.text) for event in completed] == [
        ("worker.completed", "入口在 server/kernel"),
        ("speech.requested", "分析完成：入口在 server/kernel。"),
    ]
    assert agent.snapshot().active_workers == ()


async def test_sensitive_action_requests_confirmation_instead_of_executing() -> None:
    realtime = InMemoryRealtimeSession(
        [RequireConfirmation("要现在提交订单吗？", confirmation_id="confirm-order")]
    )
    agent = OpenRealtime(realtime=realtime)

    events = await agent.submit_turn("帮我下单")

    assert [(event.type, event.text) for event in events] == [
        ("speech.requested", "要现在提交订单吗？"),
        ("confirmation.required", "要现在提交订单吗？"),
    ]
    assert agent.snapshot().pending_confirmation == "confirm-order"


async def test_tool_failure_returns_structured_context_so_realtime_can_recover() -> None:
    realtime = InMemoryRealtimeSession(
        [
            CallTool(call_id="call-broken", name="broken", arguments={}),
            Speak("工具暂时不可用，请稍后再试。"),
        ]
    )
    tools = InMemoryToolExecutor()

    def fail(_: dict[str, object]) -> str:
        raise TimeoutError("upstream timeout")

    tools.register("broken", fail)
    agent = OpenRealtime(realtime=realtime, tools=tools)

    events = await agent.submit_turn("调用失败的工具")

    assert [(event.type, event.text) for event in events] == [
        ("tool.started", None),
        ("tool.failed", "upstream timeout"),
        ("speech.requested", "工具暂时不可用，请稍后再试。"),
    ]
    assert agent.snapshot().active_tool_calls == ()


async def test_barge_in_cancels_audio_but_keeps_background_worker_running() -> None:
    realtime = InMemoryRealtimeSession(
        [
            DelegateTask(
                task="慢任务",
                acknowledgement="我正在处理，这可能需要一点时间。",
            )
        ]
    )
    workers = InMemoryWorkerManager()
    agent = OpenRealtime(realtime=realtime, workers=workers)
    await agent.submit_turn("开始慢任务")

    events = await agent.interrupt_output()

    assert [(event.type, event.text) for event in events] == [("response.cancelled", None)]
    assert realtime.cancel_count == 1
    assert agent.snapshot().output_active is False
    assert agent.snapshot().active_workers == ("worker-1",)


async def test_worker_failure_is_reinjected_and_explained_by_realtime() -> None:
    realtime = InMemoryRealtimeSession(
        [
            DelegateTask(task="远程任务", acknowledgement="我去处理。"),
            Speak("后台任务失败了：网络超时。"),
        ]
    )
    agent = OpenRealtime(realtime=realtime, workers=InMemoryWorkerManager())
    await agent.submit_turn("执行远程任务")

    events = await agent.fail_worker("worker-1", error="网络超时")

    assert [(event.type, event.text) for event in events] == [
        ("worker.failed", "网络超时"),
        ("speech.requested", "后台任务失败了：网络超时。"),
    ]
    assert agent.snapshot().active_workers == ()


async def test_realtime_can_end_the_voice_session_explicitly() -> None:
    agent = OpenRealtime(realtime=InMemoryRealtimeSession([EndSession(reason="user_requested")]))

    events = await agent.submit_turn("结束通话")

    assert [(event.type, event.text) for event in events] == [("session.ended", None)]
    assert agent.snapshot().phase == "closed"


async def test_playback_completion_clears_output_activity() -> None:
    agent = OpenRealtime(realtime=InMemoryRealtimeSession([Speak("一句话")]))
    await agent.submit_turn("说一句话")

    agent.mark_output_finished()

    assert agent.snapshot().output_active is False


async def test_worker_result_after_session_close_is_saved_but_not_spoken() -> None:
    realtime = InMemoryRealtimeSession(
        [
            DelegateTask(task="慢任务", acknowledgement="已启动。"),
            EndSession(reason="user_requested"),
        ]
    )
    agent = OpenRealtime(realtime=realtime, workers=InMemoryWorkerManager())
    await agent.submit_turn("启动慢任务")
    await agent.submit_turn("结束通话")

    events = await agent.complete_worker("worker-1", result="迟到结果")

    assert [(event.type, event.text) for event in events] == [
        ("worker.completed", "迟到结果"),
    ]
    assert events[0].data == {"worker_id": "worker-1", "spoken": False}
    assert agent.snapshot().items[-1].type == "worker_result"


async def test_explicit_worker_cancellation_does_not_depend_on_audio_interruption() -> None:
    workers = InMemoryWorkerManager()
    agent = OpenRealtime(
        realtime=InMemoryRealtimeSession(
            [DelegateTask(task="慢任务", acknowledgement="已启动。")]
        ),
        workers=workers,
    )
    await agent.submit_turn("启动慢任务")

    events = await agent.cancel_worker("worker-1")

    assert [(event.type, event.text) for event in events] == [("worker.cancelled", None)]
    assert workers.cancelled == ["worker-1"]
    assert agent.snapshot().active_workers == ()


async def test_quick_tool_waits_for_result_then_realtime_speaks() -> None:
    realtime = InMemoryRealtimeSession(
        [
            CallTool(call_id="call-weather", name="weather", arguments={"city": "上海"}),
            Speak("上海现在 28°C。"),
        ]
    )
    tools = InMemoryToolExecutor()
    tools.register("weather", lambda arguments: f"{arguments['city']}: 28°C")
    agent = OpenRealtime(realtime=realtime, tools=tools)

    events = await agent.submit_turn("上海天气怎么样")

    assert [(event.type, event.text) for event in events] == [
        ("tool.started", None),
        ("tool.completed", "上海: 28°C"),
        ("speech.requested", "上海现在 28°C。"),
    ]
    assert agent.snapshot().active_tool_calls == ()
