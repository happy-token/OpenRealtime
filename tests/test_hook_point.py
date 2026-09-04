import logging

from server.hooks.hook_point import HookPoint


def test_apply_with_no_middlewares_is_a_noop_passthrough():
    hook = HookPoint(name="test.hook")

    assert hook.apply("hi") == "hi"


def test_apply_runs_a_single_transforming_middleware():
    hook = HookPoint(name="test.hook", middlewares=(str.upper,))

    assert hook.apply("hi") == "HI"


def test_apply_returns_none_when_a_middleware_vetoes():
    hook = HookPoint(name="test.hook", middlewares=(lambda value: None,))

    assert hook.apply("hi") is None


def test_apply_chains_multiple_middlewares_in_registration_order():
    calls: list[str] = []

    def upper(value: str) -> str:
        calls.append("upper")
        return value.upper()

    def add_suffix(value: str) -> str:
        calls.append("add_suffix")
        return f"{value}!"

    hook = HookPoint(name="test.hook", middlewares=(upper, add_suffix))

    assert hook.apply("hi") == "HI!"
    assert calls == ["upper", "add_suffix"]


def test_apply_short_circuits_remaining_middlewares_once_one_vetoes():
    calls: list[str] = []

    def first(value: str) -> str:
        calls.append("first")
        return value

    def vetoing(value: str) -> None:
        calls.append("vetoing")

    def third(value: str) -> str:
        calls.append("third")
        return value

    hook = HookPoint(name="test.hook", middlewares=(first, vetoing, third))

    assert hook.apply("hi") is None
    assert calls == ["first", "vetoing"]


def test_apply_treats_a_raising_middleware_as_a_veto_and_logs(caplog):
    calls: list[str] = []

    def raiser(value: str) -> str:
        calls.append("raiser")
        raise RuntimeError("boom")

    def never_runs(value: str) -> str:
        calls.append("never_runs")
        return value

    hook = HookPoint(name="test.hook", middlewares=(raiser, never_runs))

    with caplog.at_level(logging.ERROR):
        result = hook.apply("hi")

    assert result is None
    assert calls == ["raiser"]
    assert any("test.hook" in record.message for record in caplog.records)
