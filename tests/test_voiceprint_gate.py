from server.signals.voiceprint_gate import VoiceprintGate


class StubMatcher:
    def __init__(self) -> None:
        self.last_result = None


def test_gate_passes_through_when_no_result_is_cached_yet():
    matcher = StubMatcher()
    gate = VoiceprintGate(matcher)

    assert gate("hello") == "hello"


def test_gate_passes_through_on_match():
    matcher = StubMatcher()
    matcher.last_result = (1, "match")
    gate = VoiceprintGate(matcher)

    assert gate("hello") == "hello"


def test_gate_passes_through_on_unavailable():
    matcher = StubMatcher()
    matcher.last_result = (1, "unavailable")
    gate = VoiceprintGate(matcher)

    assert gate("hello") == "hello"


def test_gate_passes_through_on_adaptive():
    matcher = StubMatcher()
    matcher.last_result = (1, "adaptive")
    gate = VoiceprintGate(matcher)

    assert gate("hello") == "hello"


def test_gate_vetoes_on_no_match():
    matcher = StubMatcher()
    matcher.last_result = (1, "no_match")
    gate = VoiceprintGate(matcher)

    assert gate("hello") is None


def test_confirm_retrieves_a_vetoed_turns_text():
    matcher = StubMatcher()
    matcher.last_result = (1, "no_match")
    gate = VoiceprintGate(matcher)
    gate("hello")

    assert gate.confirm(1) == "hello"


def test_confirm_is_single_use():
    matcher = StubMatcher()
    matcher.last_result = (1, "no_match")
    gate = VoiceprintGate(matcher)
    gate("hello")
    gate.confirm(1)

    assert gate.confirm(1) is None


def test_confirm_returns_none_for_an_unknown_generation():
    matcher = StubMatcher()
    gate = VoiceprintGate(matcher)

    assert gate.confirm(999) is None


def test_confirm_returns_none_once_the_ttl_has_elapsed():
    matcher = StubMatcher()
    matcher.last_result = (1, "no_match")
    gate = VoiceprintGate(matcher, ttl_s=-1.0)
    gate("hello")

    assert gate.confirm(1) is None


def test_gate_keys_pending_text_by_generation():
    matcher = StubMatcher()
    gate = VoiceprintGate(matcher)

    matcher.last_result = (1, "no_match")
    gate("first")
    matcher.last_result = (2, "no_match")
    gate("second")

    assert gate.confirm(1) == "first"
    assert gate.confirm(2) == "second"
