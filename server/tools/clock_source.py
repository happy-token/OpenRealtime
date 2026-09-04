"""Exposes the current date/time as a Canonical Tool, so a Brain never has
to guess "today" from stale training data. See CONTEXT.md — Canonical Tool
Schema, and ADR-0014 for why this needed no dedicated Protocol: it's a pure
local clock read, not a swappable backend/integration point.

Reports in an explicit, configured timezone rather than the host's local
time — a model given a bare naive timestamp (or a UTC one) has to guess
what "now" means for the user; it shouldn't have to. Set
VOICEAGENT_CLOCK_TIMEZONE (IANA name) to change it; defaults to
Asia/Shanghai.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from server.tools.canonical import (
    CanonicalTool,
    IdempotencyClass,
    LatencyClass,
    RiskLevel,
    ToolEffect,
)

_TOOL_NAME = "get_current_datetime"
_TOOL_DESCRIPTION = (
    "Get the authoritative current time and a target calendar date in an IANA timezone."
)
_PARAMETERS: dict[str, Any] = {
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
_TIMEZONE_ENV_VAR = "VOICEAGENT_CLOCK_TIMEZONE"
_DEFAULT_TIMEZONE = "Asia/Shanghai"
_MIN_DAY_OFFSET = -7
_MAX_DAY_OFFSET = 7
_SIMPLE_TIMEZONES = frozenset({"UTC", "Etc/UTC", "GMT"})


@dataclass(frozen=True, slots=True)
class ClockContext:
    frozen_at: datetime
    timezone: str
    base_time: datetime
    day_offset: int
    target_date: date

    def model_text(self) -> str:
        target_weekday = self.target_date.strftime("%A")
        return (
            "以下是本轮冻结的权威服务端时钟；只在本轮有效。\n"
            f"目标时区：{self.timezone}\n"
            f"日期偏移：{self.day_offset} 个日历日\n"
            f"基准时间：{self.base_time.isoformat()}\n"
            f"目标日期：{self.target_date.isoformat()}（{target_weekday}）\n"
            "目标日期已经应用日期偏移，不得再次加减日期；"
            "偏移按目标时区的日历日计算，不按固定 24 小时计算。"
        )


def resolve_timezone(tz_name: str | None = None) -> str:
    resolved = tz_name or os.environ.get(_TIMEZONE_ENV_VAR) or _DEFAULT_TIMEZONE
    if resolved not in available_timezones() or (
        "/" not in resolved and resolved not in _SIMPLE_TIMEZONES
    ):
        raise ValueError(f"invalid IANA timezone: {resolved!r}")
    return resolved


def resolve_clock(
    now: datetime,
    *,
    tz_name: str | None = None,
    day_offset: int = 0,
) -> ClockContext:
    if now.tzinfo is None:
        raise ValueError("clock requires a timezone-aware `now`")
    if isinstance(day_offset, bool) or not isinstance(day_offset, int):
        raise TypeError("day_offset must be an integer")
    if not _MIN_DAY_OFFSET <= day_offset <= _MAX_DAY_OFFSET:
        raise ValueError("day_offset must be between -7 and 7")
    resolved_tz_name = resolve_timezone(tz_name)
    try:
        localized = now.astimezone(ZoneInfo(resolved_tz_name))
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"invalid IANA timezone: {resolved_tz_name!r}") from error
    return ClockContext(
        frozen_at=now,
        timezone=resolved_tz_name,
        base_time=localized,
        day_offset=day_offset,
        target_date=localized.date() + timedelta(days=day_offset),
    )


def parse_clock_selector(selector: str) -> tuple[str, int]:
    if selector != selector.strip() or selector.count("|") != 1:
        raise ValueError("clock selector must be <IANA timezone>|<-7..7>")
    tz_name, raw_offset = selector.split("|", maxsplit=1)
    if raw_offset != raw_offset.strip():
        raise ValueError("clock selector day offset must not contain whitespace")
    try:
        day_offset = int(raw_offset)
    except ValueError as error:
        raise ValueError("clock selector day offset must be an integer") from error
    if str(day_offset) != raw_offset:
        raise ValueError("clock selector day offset must use canonical integer syntax")
    resolve_clock(datetime.now(UTC), tz_name=tz_name, day_offset=day_offset)
    return tz_name, day_offset


def localize(now: datetime, tz_name: str | None = None) -> tuple[datetime, str]:
    """Resolves the effective IANA timezone (explicit arg, else
    VOICEAGENT_CLOCK_TIMEZONE, else Asia/Shanghai) and returns `now`
    converted into it, alongside the resolved timezone name. Shared by
    ClockToolSource and ChatBrain's prompt grounding so both agree on "now"
    without duplicating the resolution order."""
    context = resolve_clock(now, tz_name=tz_name)
    return context.base_time, context.timezone


class ClockToolSource:
    def __init__(
        self,
        *,
        tz_name: str | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._tz_name = tz_name
        self._now = now

    def list_tools(self) -> list[CanonicalTool]:
        return [
            CanonicalTool(
                name=_TOOL_NAME,
                description=_TOOL_DESCRIPTION,
                parameters=_PARAMETERS,
                handler=self._get_current_datetime,
                effects=frozenset({ToolEffect.READ_PUBLIC}),
                risk=RiskLevel.LOW,
                idempotency=IdempotencyClass.IDEMPOTENT,
                latency=LatencyClass.FAST,
            )
        ]

    async def _get_current_datetime(self, arguments: dict[str, Any]) -> str:
        now = self._now()
        assert now.tzinfo is not None, "ClockToolSource requires a timezone-aware `now`"
        requested_timezone = arguments.get("timezone")
        if requested_timezone is not None and not isinstance(requested_timezone, str):
            raise ValueError("timezone must be a string")
        context = resolve_clock(
            now,
            tz_name=requested_timezone or self._tz_name,
            day_offset=arguments.get("day_offset", 0),
        )
        return context.model_text()
