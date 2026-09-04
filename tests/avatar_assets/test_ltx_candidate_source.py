from server.avatar_assets import CandidateSourceKind


def test_ltx_is_a_first_class_motion_candidate_source() -> None:
    assert CandidateSourceKind.LTX.value == "ltx"


def test_minimax_is_a_distinct_motion_candidate_source() -> None:
    assert CandidateSourceKind.MINIMAX.value == "minimax"
