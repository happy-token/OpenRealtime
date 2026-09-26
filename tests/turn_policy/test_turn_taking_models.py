from collections import Counter

import pytest

from scripts.evaluate_turn_taking_models import (
    CHALLENGE_DATASET,
    DATASET,
    HOLDOUT_DATASET,
    INSTRUCTIONS,
    SOURCE_AWARE_INSTRUCTIONS,
    load_cases,
    score,
    state_for,
)


def test_turn_taking_v2_categories_and_labels() -> None:
    cases = load_cases(DATASET)

    assert len(cases) == 30
    assert Counter(case["label"] for case in cases if case["task"] == "completeness") == {
        "complete": 4,
        "incomplete": 4,
        "review": 4,
    }
    assert Counter(case["category"] for case in cases if case["task"] == "interruption") == {
        "backchannel": 3,
        "stop": 3,
        "correction": 3,
        "new_request": 3,
        "background_speech": 3,
        "background_noise": 3,
    }
    assert state_for(cases[0]) == {
        "transcript": "帮我查一下明天上海的天气",
        "history": [],
    }
    assert state_for(cases[-1])["observation"]


def test_challenge_dataset_balances_contrast_pairs_without_leaking_labels() -> None:
    cases = load_cases(CHALLENGE_DATASET, split="challenge")

    assert len(cases) == 52
    assert Counter(case["label"] for case in cases if case["task"] == "completeness") == {
        "complete": 12,
        "incomplete": 12,
        "review": 4,
    }
    assert Counter(case["label"] for case in cases if case["task"] == "interruption") == {
        "backchannel": 4,
        "stop": 4,
        "correction": 4,
        "interrupt": 4,
        "ignore": 8,
    }
    pairs = {case["pair"] for case in cases if case.get("pair")}
    for pair in pairs:
        members = [case for case in cases if case.get("pair") == pair]
        assert len(members) == 2
        assert members[0]["label"] != members[1]["label"]
        assert all("rationale" not in state_for(case) for case in members)
    assert len({case["id"] for case in cases + load_cases(DATASET)}) == 82


def test_prompt_holdout_is_disjoint_and_source_balanced() -> None:
    cases = load_cases(HOLDOUT_DATASET, split="holdout")

    assert len(cases) == 20
    assert len({case["id"] for case in cases + load_cases(DATASET) + load_cases(CHALLENGE_DATASET)}) == 102
    assert Counter(case["label"] for case in cases if case["task"] == "completeness") == {
        "complete": 4,
        "incomplete": 4,
    }
    assert Counter(case["label"] for case in cases if case["task"] == "interruption") == {
        "stop": 2,
        "correction": 2,
        "interrupt": 2,
        "ignore": 4,
        "backchannel": 2,
    }
    assert all("label" not in state_for(case) for case in cases)
    assert INSTRUCTIONS["interruption"] != SOURCE_AWARE_INSTRUCTIONS["interruption"]


def test_score_counts_provider_errors_as_incorrect() -> None:
    rows = [
        {"expected": "complete", "predicted": "complete", "latency_ms": 10},
        {"expected": "incomplete", "predicted": None, "latency_ms": 20},
    ]

    result = score(rows)

    assert result["accuracy"] == 0.5
    assert result["macro_precision"] == 0.5
    assert result["macro_recall"] == 0.5
    assert result["per_label"]["incomplete"]["recall"] == 0
    assert result["errors"] == 1
    assert result["by_expected"]["incomplete"] == {"error": 1}
    assert result["latency"] == {
        "mean_ms": 15.0,
        "p90_ms": 20,
        "p50_ms": 10,
        "p95_ms": 20,
    }


def test_review_cases_are_not_counted_as_ground_truth() -> None:
    rows = [
        {"expected": "complete", "predicted": "complete", "latency_ms": 10},
        {"expected": "review", "predicted": "uncertain", "latency_ms": 20},
        {"expected": "review", "predicted": "incomplete", "latency_ms": 30},
    ]

    result = score(rows)

    assert result["evaluated"] == 1
    assert result["accuracy"] == 1.0
    assert result["review_uncertain_rate"] == 0.5


def test_score_tracks_false_positives_and_recall() -> None:
    rows = [
        {"expected": "complete", "predicted": "complete", "latency_ms": 10},
        {"expected": "incomplete", "predicted": "complete", "latency_ms": 20},
        {"expected": "incomplete", "predicted": "incomplete", "latency_ms": 30},
    ]

    result = score(rows)

    assert result["accuracy"] == 2 / 3
    assert result["per_label"]["complete"]["precision"] == 0.5
    assert result["per_label"]["complete"]["recall"] == 1.0
    assert result["per_label"]["incomplete"]["recall"] == 0.5
    assert result["latency"]["mean_ms"] == 20.0
    assert result["latency"]["p90_ms"] == 30


def test_dataset_rejects_duplicate_ids(tmp_path) -> None:
    first = DATASET.read_text(encoding="utf-8").splitlines()[0]
    path = tmp_path / "duplicate.jsonl"
    path.write_text(first + "\n" + first + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)
