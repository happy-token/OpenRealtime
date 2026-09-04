from datetime import UTC, datetime

import pytest

from server.tools.clock_source import ClockToolSource, parse_clock_selector


def _fixed_now() -> datetime:
    return datetime(2026, 8, 2, 15, 30, 0, tzinfo=UTC)


def test_clock_source_exposes_a_single_get_current_datetime_tool():
    source = ClockToolSource(now=_fixed_now)

    tools = source.list_tools()

    assert len(tools) == 1
    assert tools[0].name == "get_current_datetime"
    assert tools[0].parameters == {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA timezone, for example Asia/Shanghai",
            },
            "day_offset": {
                "type": "integer",
                "minimum": -7,
                "maximum": 7,
                "description": "Calendar-day offset in the target timezone",
            },
        },
    }


async def test_clock_source_handler_localizes_to_configured_timezone_with_weekday():
    source = ClockToolSource(now=_fixed_now, tz_name="Asia/Shanghai")
    tool = source.list_tools()[0]

    result = await tool.handler({})

    assert "基准时间：2026-08-02T23:30:00+08:00" in result
    assert "目标时区：Asia/Shanghai" in result
    assert "目标日期：2026-08-02（Sunday）" in result


async def test_clock_source_accepts_target_timezone_and_calendar_day_offset():
    source = ClockToolSource(now=lambda: datetime(2026, 3, 8, 4, 30, tzinfo=UTC))
    tool = source.list_tools()[0]

    result = await tool.handler({"timezone": "America/New_York", "day_offset": 1})

    assert "基准时间：2026-03-07T23:30:00-05:00" in result
    assert "目标日期：2026-03-08（Sunday）" in result
    assert "不得再次加减日期" in result


@pytest.mark.parametrize(
    "arguments",
    [
        {"timezone": "Mars/Olympus"},
        {"timezone": "posixrules"},
        {"day_offset": 8},
        {"day_offset": True},
    ],
)
async def test_clock_source_rejects_invalid_timezone_or_offset(arguments):
    source = ClockToolSource(now=_fixed_now)
    tool = source.list_tools()[0]

    with pytest.raises((TypeError, ValueError)):
        await tool.handler(arguments)


@pytest.mark.parametrize(
    "selector",
    [
        "Asia/Shanghai| 1",
        "Asia/Shanghai|+1",
        "Asia/Shanghai|01",
        "Asia/Shanghai|-0",
    ],
)
def test_clock_selector_requires_canonical_integer_syntax(selector):
    with pytest.raises(ValueError):
        parse_clock_selector(selector)


async def test_clock_source_defaults_to_asia_shanghai_timezone(monkeypatch):
    monkeypatch.delenv("VOICEAGENT_CLOCK_TIMEZONE", raising=False)
    source = ClockToolSource(now=_fixed_now)
    tool = source.list_tools()[0]

    result = await tool.handler({})

    assert "Asia/Shanghai" in result


async def test_clock_source_reads_timezone_from_env_var(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_CLOCK_TIMEZONE", "America/New_York")
    source = ClockToolSource(now=_fixed_now)
    tool = source.list_tools()[0]

    result = await tool.handler({})

    assert "America/New_York" in result


async def test_clock_source_tz_name_argument_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_CLOCK_TIMEZONE", "America/New_York")
    source = ClockToolSource(now=_fixed_now, tz_name="UTC")
    tool = source.list_tools()[0]

    result = await tool.handler({})

    assert "UTC" in result
    assert "America/New_York" not in result


async def test_clock_source_asserts_on_naive_now():
    source = ClockToolSource(now=lambda: datetime(2026, 8, 2, 15, 30, 0))  # noqa: DTZ001
    tool = source.list_tools()[0]

    with pytest.raises(AssertionError):
        await tool.handler({})
