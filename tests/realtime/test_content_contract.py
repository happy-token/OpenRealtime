from __future__ import annotations

from server.conversation_journal.models import StructuredContent, TextContent
from server.realtime import AssistantContent, DisplayContent, SpokenContent


def test_assistant_content_keeps_semantic_display_and_spoken_representations_distinct() -> None:
    content = AssistantContent(
        semantic=(
            TextContent("任务已经完成，共修改三个文件，并且测试全部通过。"),
            StructuredContent({"changed_files": 3, "tests": "passed"}),
        ),
        display=DisplayContent(
            markdown="## 已完成\n\n- 修改 3 个文件\n- 全部测试通过",
        ),
        spoken=SpokenContent(text="任务已经完成，修改了三个文件，测试全部通过。"),
    )

    assert content.semantic[0].text == "任务已经完成，共修改三个文件，并且测试全部通过。"
    assert content.semantic[1].value == {"changed_files": 3, "tests": "passed"}
    assert content.display is not None
    assert content.display.markdown == "## 已完成\n\n- 修改 3 个文件\n- 全部测试通过"
    assert content.spoken is not None
    assert content.spoken.text == "任务已经完成，修改了三个文件，测试全部通过。"
