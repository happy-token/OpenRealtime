import asyncio

import pytest

from server.tools.everyday_source import EverydayToolSource


def _run(name: str, arguments: dict) -> str:
    tool = next(tool for tool in EverydayToolSource().list_tools() if tool.name == name)
    return asyncio.run(tool.handler(arguments))


def test_calculator_and_invalid_division() -> None:
    assert _run("calculate", {"operation": "percent", "a": 240, "b": 15}) == "36"
    assert _run("calculate", {"operation": "divide", "a": 7, "b": 2}) == "3.5"
    with pytest.raises(ValueError, match="divide by zero"):
        _run("calculate", {"operation": "divide", "a": 1, "b": 0})


def test_unit_conversion_and_category_boundary() -> None:
    assert _run("convert_units", {"value": 1, "from_unit": "km", "to_unit": "m"}) == "1000 m"
    assert _run("convert_units", {"value": 32, "from_unit": "F", "to_unit": "C"}) == "0 C"
    with pytest.raises(ValueError, match="same category"):
        _run("convert_units", {"value": 1, "from_unit": "kg", "to_unit": "m"})


def test_text_count_is_bounded() -> None:
    assert _run("count_text", {"text": "hello world\nnext"}) == "characters: 16; words: 3; lines: 2"
    with pytest.raises(ValueError, match="10000"):
        _run("count_text", {"text": "x" * 10001})
