from server.knowledge_base.in_memory_knowledge_base import InMemoryKnowledgeBase


async def test_search_matches_case_insensitive_substring():
    kb = InMemoryKnowledgeBase(["The Eiffel Tower is in Paris", "Mount Fuji is in Japan"])

    results = await kb.search("PARIS")

    assert results == ["The Eiffel Tower is in Paris"]


async def test_search_truncates_to_top_k():
    kb = InMemoryKnowledgeBase(["cat one", "cat two", "cat three"])

    results = await kb.search("cat", top_k=2)

    assert results == ["cat one", "cat two"]


async def test_search_returns_empty_list_when_no_match():
    kb = InMemoryKnowledgeBase(["The Eiffel Tower is in Paris"])

    results = await kb.search("Tokyo")

    assert results == []


async def test_default_constructed_knowledge_base_always_returns_empty():
    kb = InMemoryKnowledgeBase()

    results = await kb.search("anything")

    assert results == []
