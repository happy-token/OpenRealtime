"""Small, deterministic everyday tools with no external credentials or side effects."""

from __future__ import annotations

import math
from typing import Any

from server.tools.canonical import (
    CanonicalTool,
    IdempotencyClass,
    LatencyClass,
    RiskLevel,
    ToolEffect,
)


def _tool(name: str, description: str, parameters: dict[str, Any], handler: Any) -> CanonicalTool:
    return CanonicalTool(
        name=name, description=description, parameters=parameters, handler=handler,
        effects=frozenset({ToolEffect.READ_PUBLIC}), risk=RiskLevel.LOW,
        idempotency=IdempotencyClass.IDEMPOTENT, latency=LatencyClass.FAST,
    )


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e12:
        raise ValueError("number must be finite and within ±1e12")
    return float(value)


class EverydayToolSource:
    def list_tools(self) -> list[CanonicalTool]:
        return [
            _tool("calculate", "Calculate addition, subtraction, multiplication, division or a percentage.", {
                "type": "object", "properties": {
                    "operation": {"type": "string", "enum": ["add", "subtract", "multiply", "divide", "percent"]},
                    "a": {"type": "number"}, "b": {"type": "number"},
                }, "required": ["operation", "a", "b"],
            }, self._calculate),
            _tool("convert_units", "Convert common length, mass or temperature units.", {
                "type": "object", "properties": {
                    "value": {"type": "number"},
                    "from_unit": {"type": "string", "enum": ["mm", "cm", "m", "km", "in", "ft", "mi", "g", "kg", "lb", "oz", "C", "F", "K"]},
                    "to_unit": {"type": "string", "enum": ["mm", "cm", "m", "km", "in", "ft", "mi", "g", "kg", "lb", "oz", "C", "F", "K"]},
                }, "required": ["value", "from_unit", "to_unit"],
            }, self._convert),
            _tool("count_text", "Count characters, words and lines in short text.", {
                "type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
            }, self._count),
        ]

    async def _calculate(self, arguments: dict[str, Any]) -> str:
        a, b = _number(arguments["a"]), _number(arguments["b"])
        operation = arguments["operation"]
        if operation not in {"add", "subtract", "multiply", "divide", "percent"}:
            raise ValueError("unsupported operation")
        if operation == "divide" and b == 0:
            raise ValueError("cannot divide by zero")
        result = {"add": lambda: a + b, "subtract": lambda: a - b,
                  "multiply": lambda: a * b, "divide": lambda: a / b,
                  "percent": lambda: a * b / 100}[operation]()
        if not math.isfinite(result) or abs(result) > 1e18:
            raise ValueError("result is out of range")
        return f"{result:.12g}"

    async def _convert(self, arguments: dict[str, Any]) -> str:
        value = _number(arguments["value"])
        source, target = arguments["from_unit"], arguments["to_unit"]
        length = {"mm": .001, "cm": .01, "m": 1, "km": 1000, "in": .0254, "ft": .3048, "mi": 1609.344}
        mass = {"g": .001, "kg": 1, "lb": .45359237, "oz": .028349523125}
        if source in length and target in length:
            result = value * length[source] / length[target]
        elif source in mass and target in mass:
            result = value * mass[source] / mass[target]
        elif source in {"C", "F", "K"} and target in {"C", "F", "K"}:
            kelvin = value + 273.15 if source == "C" else (value + 459.67) * 5 / 9 if source == "F" else value
            if kelvin < 0:
                raise ValueError("temperature is below absolute zero")
            result = kelvin - 273.15 if target == "C" else kelvin * 9 / 5 - 459.67 if target == "F" else kelvin
        else:
            raise ValueError("units must belong to the same category")
        return f"{result:.12g} {target}"

    async def _count(self, arguments: dict[str, Any]) -> str:
        content = arguments["text"]
        if not isinstance(content, str) or len(content) > 10000:
            raise ValueError("text must contain at most 10000 characters")
        return f"characters: {len(content)}; words: {len(content.split())}; lines: {len(content.splitlines()) if content else 0}"
