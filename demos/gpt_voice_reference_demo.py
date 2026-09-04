"""Run the minimal GPT Voice-style coordinator without network credentials."""

from __future__ import annotations

import asyncio

from server.gpt_voice_reference import (
    CallTool,
    DelegateTask,
    InMemoryRealtimeSession,
    InMemoryToolExecutor,
    InMemoryWorkerManager,
    OpenRealtime,
    Speak,
)


async def main() -> None:
    realtime = InMemoryRealtimeSession(
        [
            Speak(
                "你好，我可以直接回答、调用快速工具，或者委派复杂任务。"
            ),
            CallTool("call-clock", "clock", {}),
            Speak("现在是演示时间 10:30。"),
            DelegateTask("分析项目架构", "我在后台分析，完成后告诉你。"),
            Speak("后台分析完成：项目采用媒体、控制和任务三个执行平面。"),
        ]
    )
    tools = InMemoryToolExecutor()
    tools.register("clock", lambda _: "10:30")
    agent = OpenRealtime(
        realtime=realtime,
        tools=tools,
        workers=InMemoryWorkerManager(),
    )

    for utterance in ("你好", "现在几点", "分析项目架构"):
        print(utterance, "=>", await agent.submit_turn(utterance))
    print("worker-1 =>", await agent.complete_worker("worker-1", result="三平面架构"))


if __name__ == "__main__":
    asyncio.run(main())
