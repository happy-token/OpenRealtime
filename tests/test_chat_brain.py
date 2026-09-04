from datetime import UTC, datetime

from server.brain.chat_brain import DEFAULT_SYSTEM_PROMPT, ChatBrain
from server.brain.llm_clients import EchoLlmClient
from server.brain.realtime_grounding import TurnGrounding
from server.core.turn_content import TurnContent


def _fixed_now() -> datetime:
    return datetime(2026, 8, 2, 15, 30, 0, tzinfo=UTC)


class _RecordingLlmClient:
    def __init__(self) -> None:
        self.seen_prompts: list[str] = []

    async def complete(self, *, system_prompt: str, user_text: str) -> str:
        self.seen_prompts.append(system_prompt)
        return "ok"


class _StreamingLlmClient(_RecordingLlmClient):
    def stream(self, *, system_prompt: str, user_text: str):
        self.seen_prompts.append(system_prompt)

        async def chunks():
            yield "你"
            yield "好"

        return chunks()


class _Grounder:
    async def resolve(self, transcript: str) -> TurnGrounding:
        assert transcript == "北京今天天气如何？"
        return TurnGrounding(
            action="lookup",
            frozen_at=_fixed_now(),
            default_timezone="Asia/Shanghai",
            evidence_text="1. 北京天气\n晴，30℃",
        )


async def test_chat_brain_returns_llm_client_output_as_response_text():
    brain = ChatBrain(EchoLlmClient())
    content = TurnContent(text="hello", generation=1)

    response = await brain.respond(content)

    assert response.text == "You said: hello"
    assert response.generation == 1
    assert response.action is None


async def test_chat_brain_passes_system_prompt_to_llm_client():
    llm_client = _RecordingLlmClient()

    brain = ChatBrain(
        llm_client, system_prompt="custom prompt", tz_name="Asia/Shanghai", now=_fixed_now
    )
    await brain.respond(TurnContent(text="hi", generation=2))

    assert llm_client.seen_prompts == [
        (
            "custom prompt\n\n"
            "当前时间：2026-08-02T23:30:00+08:00（Asia/Shanghai，Sunday）。"
            "回答日期/时间相关问题以此为准，不要凭训练数据猜测当前日期或年份。"
        )
    ]


async def test_chat_brain_resolves_the_active_persona_for_each_turn():
    llm_client = _RecordingLlmClient()
    active = {"prompt": "Persona A"}
    brain = ChatBrain(
        llm_client,
        system_prompt="BASE",
        system_prompt_transform=lambda base: f"{base}\n\n{active['prompt']}",
        tz_name="UTC",
        now=_fixed_now,
    )

    await brain.respond(TurnContent(text="first", generation=1))
    active["prompt"] = "Persona B"
    await brain.respond(TurnContent(text="second", generation=2))

    assert "BASE\n\nPersona A" in llm_client.seen_prompts[0]
    assert "BASE\n\nPersona B" in llm_client.seen_prompts[1]


async def test_chat_brain_grounding_reflects_tz_name_override():
    llm_client = _RecordingLlmClient()

    brain = ChatBrain(
        llm_client, system_prompt="custom prompt", tz_name="UTC", now=_fixed_now
    )
    await brain.respond(TurnContent(text="hi", generation=2))

    assert llm_client.seen_prompts == [
        (
            "custom prompt\n\n"
            "当前时间：2026-08-02T15:30:00+00:00（UTC，Sunday）。"
            "回答日期/时间相关问题以此为准，不要凭训练数据猜测当前日期或年份。"
        )
    ]


async def test_chat_brain_streams_native_llm_deltas_with_the_same_grounding():
    llm_client = _StreamingLlmClient()
    brain = ChatBrain(
        llm_client, system_prompt="custom prompt", tz_name="UTC", now=_fixed_now
    )

    chunks = [
        chunk
        async for chunk in brain.stream(TurnContent(text="hi", generation=3))
    ]

    assert chunks == ["你", "好"]
    assert llm_client.seen_prompts == [
        (
            "custom prompt\n\n"
            "当前时间：2026-08-02T15:30:00+00:00（UTC，Sunday）。"
            "回答日期/时间相关问题以此为准，不要凭训练数据猜测当前日期或年份。"
        )
    ]


async def test_chat_brain_stream_falls_back_to_one_complete_chunk():
    llm_client = _RecordingLlmClient()
    brain = ChatBrain(llm_client, now=_fixed_now)

    chunks = [
        chunk
        async for chunk in brain.stream(TurnContent(text="hi", generation=4))
    ]

    assert chunks == ["ok"]


async def test_zero_config_echo_brain_exposes_multiple_text_deltas():
    brain = ChatBrain(EchoLlmClient())

    chunks = [
        chunk
        async for chunk in brain.stream(
            TurnContent(text="hello", generation=1)
        )
    ]

    assert len(chunks) > 1
    assert "".join(chunks) == "You said: hello"


async def test_chat_brain_injects_grounding_as_explicit_system_and_untrusted_user_context():
    class RecordingClient(_RecordingLlmClient):
        def __init__(self) -> None:
            super().__init__()
            self.user_texts: list[str] = []

        async def complete(self, *, system_prompt: str, user_text: str) -> str:
            self.seen_prompts.append(system_prompt)
            self.user_texts.append(user_text)
            return "ok"

    client = RecordingClient()
    brain = ChatBrain(client, grounder=_Grounder())

    await brain.respond(TurnContent(text="北京今天天气如何？", generation=1))

    assert "基准时间：2026-08-02T23:30:00+08:00" in client.seen_prompts[0]
    assert "北京天气" not in client.seen_prompts[0]
    assert "外部不可信数据" in client.seen_prompts[0]
    assert client.user_texts[0].startswith("北京今天天气如何？")
    assert "外部不可信数据" in client.user_texts[0]
    assert "北京天气" in client.user_texts[0]


async def test_chat_brain_does_not_stream_leading_english_meta_reasoning_for_chinese_input():
    class MixedLanguageClient(_RecordingLlmClient):
        def stream(self, *, system_prompt: str, user_text: str):
            del system_prompt, user_text

            async def chunks():
                yield "Let me reconsider what the user is asking. "
                yield "Their message seems unclear and possibly garbled.\n\n"
                yield "我注意到您的问题似乎有些不太清楚。"

            return chunks()

    chunks = [
        chunk
        async for chunk in ChatBrain(MixedLanguageClient()).stream(
            TurnContent(text="学生和喝东西。如何？", generation=1)
        )
    ]

    assert "".join(chunks) == "我注意到您的问题似乎有些不太清楚。"


async def test_chat_brain_complete_response_removes_leading_meta_reasoning():
    class MixedLanguageClient(_RecordingLlmClient):
        async def complete(self, *, system_prompt: str, user_text: str) -> str:
            del system_prompt, user_text
            return (
                "Let me analyze what the user means.\n\n"
                "您的问题可能没有识别完整，请再说一次。"
            )

    response = await ChatBrain(MixedLanguageClient()).respond(
        TurnContent(text="刚才说的那个怎么样？", generation=1)
    )

    assert response.text == "您的问题可能没有识别完整，请再说一次。"


def test_default_prompt_requires_language_consistency_and_hides_reasoning():
    assert "same language" in DEFAULT_SYSTEM_PROMPT
    assert "Never expose" in DEFAULT_SYSTEM_PROMPT
