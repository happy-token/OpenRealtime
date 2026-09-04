import pytest

from server.web_search.deterministic_web_search import DeterministicWebSearch
from server.web_search.protocol import LookupFailure


async def test_search_matches_case_insensitive_substring():
    web_search = DeterministicWebSearch({"eiffel tower": ["The Eiffel Tower is 330m tall."]})

    evidence = await web_search.search("How tall is the EIFFEL TOWER?")

    assert evidence.structured()["untrusted"] is True
    assert [result.summary for result in evidence.results] == [
        "The Eiffel Tower is 330m tall."
    ]


async def test_search_truncates_to_top_k():
    web_search = DeterministicWebSearch({"cat": ["cat one", "cat two", "cat three"]})

    evidence = await web_search.search("tell me about cats", top_k=2)

    assert [result.summary for result in evidence.results] == ["cat one", "cat two"]


async def test_search_returns_typed_empty_result_when_no_match():
    web_search = DeterministicWebSearch({"eiffel tower": ["The Eiffel Tower is 330m tall."]})

    with pytest.raises(LookupFailure) as error:
        await web_search.search("weather in Tokyo")

    assert error.value.reason == "empty_result"


async def test_default_constructed_web_search_has_typed_empty_result():
    web_search = DeterministicWebSearch()

    with pytest.raises(LookupFailure) as error:
        await web_search.search("anything")

    assert error.value.reason == "empty_result"
