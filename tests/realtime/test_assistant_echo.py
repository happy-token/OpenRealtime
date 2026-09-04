from server.realtime.capabilities.assistant_echo import project_assistant_echo


def test_assistant_echo_only_is_suppressed_despite_punctuation_difference() -> None:
    assert (
        project_assistant_echo(
            "有什么我可以帮你的吗",
            "你好！有什么我可以帮你的吗？",
        )
        is None
    )


def test_real_user_query_after_echo_prefix_is_preserved() -> None:
    assert project_assistant_echo(
        "有什么我可以帮你的吗？今天天气怎么样呀",
        "你好！有什么我可以帮你的吗？",
    ) == "今天天气怎么样呀"


def test_unrelated_user_interruption_is_unchanged() -> None:
    assert project_assistant_echo(
        "今天天气怎么样呀？",
        "你好！有什么我可以帮你的吗？",
    ) == "今天天气怎么样呀？"


def test_short_repetition_is_not_suppressed_as_echo() -> None:
    assert project_assistant_echo("你好", "你好！有什么我可以帮你的吗？") == "你好"
