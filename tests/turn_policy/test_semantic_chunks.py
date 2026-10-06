import tracemalloc

from server.turn_policy.semantic_chunks import SemanticChunkBuffer, _BoundaryIndex


class CountedText(str):
    def __new__(cls, value, work):
        result = super().__new__(cls, value)
        result.work = work
        return result

    def __getitem__(self, key):
        result = super().__getitem__(key)
        self.work[0] += len(result) if isinstance(key, slice) else 1
        return CountedText(result, self.work)

    def __iter__(self):
        for character in super().__iter__():
            self.work[0] += 1
            yield character


def test_incremental_text_only_emits_at_five_new_characters():
    buffer = SemanticChunkBuffer(character_limit=5)
    emitted = []
    text = "不是北京是上海明天的天气"
    for revision, end in enumerate(range(1, len(text) + 1), 1):
        emitted.extend(buffer.update(text[:end], revision=revision))
    assert [chunk.text for chunk in emitted] == ["不是北京是", "上海明天的"]
    assert [chunk.text for chunk in buffer.update(text, revision=20, force=True)] == ["天气"]
    assert buffer.update(text + "。", revision=21, force=True) == ()


def test_punctuation_creates_independent_chunks_without_resending_prefix():
    buffer = SemanticChunkBuffer()
    chunks = buffer.update("帮我查天气，明天上海会下雨吗？", revision=1, stable=True)
    assert [chunk.text for chunk in chunks] == ["帮我查天气，", "明天上海会下雨吗？"]
    assert buffer.update("帮我查天气，明天上海会下雨吗？", revision=2, stable=True) == ()


def test_candidate_punctuation_waits_for_stability():
    buffer = SemanticChunkBuffer()
    assert buffer.update("如果明天下雨，", revision=1) == ()
    assert buffer.update("如果明天下雨，", revision=1, stable=True)[0].text == "如果明天下雨，"


def test_rewritten_text_invalidates_affected_chunks_and_keeps_prior_chunk():
    buffer = SemanticChunkBuffer()
    first, second = buffer.update("查天气，明天北京？", revision=1, stable=True)
    corrected = buffer.update("查天气，明天上海？", revision=2, stable=True)
    assert len(corrected) == 1
    assert corrected[0].text == "明天上海？"
    assert buffer.valid(first)
    assert not buffer.valid(second)
    assert corrected[0].chunk_id != second.chunk_id


def test_decimal_period_is_not_a_boundary():
    buffer = SemanticChunkBuffer()
    assert [c.text for c in buffer.update("买3.5公斤苹果。", revision=1, stable=True)] == [
        "买3.5公斤苹果。"
    ]


def test_domain_and_english_words_are_not_per_letter_chunks():
    buffer = SemanticChunkBuffer(character_limit=5)
    assert buffer.update("check example.com", revision=1, stable=True) == ()
    assert buffer.update("check example.com tomorrow", revision=2) == ()
    chunks = buffer.update("check example.com tomorrow morning", revision=3)
    assert [chunk.text for chunk in chunks] == ["check example.com tomorrow morning"]


def test_ascii_sentence_punctuation_is_a_stability_candidate():
    buffer = SemanticChunkBuffer()
    assert buffer.update("hello.", revision=1) == ()
    assert buffer.pending_boundary == "hello"
    assert [chunk.text for chunk in buffer.update("hello.", revision=1, stable=True)] == ["hello."]


def test_rewrite_of_merged_pending_chunk_reissues_its_retained_prefix():
    buffer = SemanticChunkBuffer(character_limit=2)
    chunks = buffer.update("查天气换上海看明天", revision=1)
    merged = buffer.merge_pending(list(chunks[1:]))
    revised = buffer.update("查天气换上海看后天", revision=2, force=True)
    assert not buffer.valid(merged)
    assert "".join(chunk.text for chunk in revised) == "气换上海看后天"


def test_cumulative_text_preserves_decimal_and_domain_punctuation():
    buffer = SemanticChunkBuffer()
    text = "查3.5元，访问example.com。"
    first, second = buffer.update(text, revision=1, stable=True)
    assert buffer.cumulative_text(first) == "查3.5元，"
    assert buffer.cumulative_text(second) == text


def test_rewritten_candidate_does_not_revive_when_original_text_returns():
    buffer = SemanticChunkBuffer()
    old = buffer.update("查北京天气。", revision=1, stable=True)[0]
    buffer.update("查上海天气。", revision=2, stable=True)
    current = buffer.update("查北京天气。", revision=3, stable=True)[0]
    assert buffer.valid(current)
    assert not buffer.valid(old)
    assert buffer.cumulative_text(old) is None


def test_matching_text_from_another_input_is_not_a_valid_candidate():
    first, second = SemanticChunkBuffer(), SemanticChunkBuffer()
    foreign = first.update("查北京天气。", revision=1, stable=True)[0]
    second.update("查北京天气。", revision=1, stable=True)
    assert not second.valid(foreign)
    assert second.cumulative_text(foreign) is None


def test_retained_buffer_memory_scales_linearly_with_long_input():
    def retained_bytes(length: int) -> int:
        text = "查北京天气" * (length // 5)
        tracemalloc.start()
        try:
            buffer = SemanticChunkBuffer(character_limit=5)
            last = buffer.update(text, revision=1)[-1]
            retained, _ = tracemalloc.get_traced_memory()
            assert buffer.cumulative_text(last) == text
            return retained
        finally:
            tracemalloc.stop()

    short = retained_bytes(1000)
    long = retained_bytes(4000)
    assert long <= short * 5, (short, long)


def test_long_chinese_input_does_not_rescan_the_entire_tail_for_each_chunk():
    work = [0]
    text = CountedText("查北京天气" * 200, work)
    chunks = SemanticChunkBuffer(character_limit=5).update(text, revision=1)
    assert "".join(chunk.text for chunk in chunks) == text
    assert work[0] <= len(text) * 30


def test_threshold_cut_preserves_suffix_sensitive_url_period_rules():
    buffer = SemanticChunkBuffer(character_limit=2)
    first = buffer.update("go https://example.com/foo/.bar", revision=1)
    assert [chunk.text for chunk in first] == ["go https", "://example.com"]
    assert [
        chunk.text
        for chunk in buffer.update("go https://example.com/foo/.bar", revision=2, stable=True)
    ] == ["foo/."]
    assert [
        chunk.text
        for chunk in buffer.update("go https://example.com/foo/.bar", revision=3, force=True)
    ] == ["bar"]


def test_long_input_with_url_period_does_not_rescan_or_copy_each_remaining_tail():
    work = [0]
    text = CountedText("查北京天气" * 200 + " https://example.com/foo/.", work)
    chunks = SemanticChunkBuffer(character_limit=5).update(text, revision=1, force=True)
    assert "".join(chunk.text for chunk in chunks) == text
    assert work[0] <= len(text) * 30, (len(text), work[0])


def test_index_matches_legacy_period_rules_at_every_monotone_suffix():
    import random

    def legacy_boundary(text, index):
        character = text[index]
        if character in "，,；;。？！?!\n":
            return True
        if character != ".":
            return False
        if (
            index > 0
            and index + 1 < len(text)
            and text[index - 1].isalnum()
            and text[index + 1].isalnum()
        ):
            return False
        words = text[: index + 1].split()
        return "://" not in (words[-1] if words else "")

    randomizer = random.Random(20261007)
    texts = [
        "https://example.com/foo/.bar",
        "a.b 3.5 x. http://foo/.",
        "http://a.b/路径/.\u2003next.",
        ".a.b.\nhttps://x/.y",
        "https://a/.b://c/..，完。",
    ]
    atoms = [
        "a",
        "中",
        ".",
        "3",
        "/",
        ":",
        "://",
        " ",
        "\n",
        "\t",
        "\u2003",
        ",",
        "！",
        "https://x.y/",
        "'word'",
    ]
    texts.extend("".join(randomizer.choices(atoms, k=20)) for _ in range(500))
    for text in texts:
        boundaries = _BoundaryIndex(text)
        for cursor in range(len(text) + 1):
            suffix = text[cursor:]
            expected = next(
                (
                    cursor + index + 1
                    for index in range(len(suffix))
                    if legacy_boundary(suffix, index)
                ),
                None,
            )
            assert boundaries.next(cursor) == expected, (text, cursor, expected)


def test_large_punctuation_and_url_inputs_have_bounded_character_work():
    for raw in (
        "查北京天气" * 800 + " https://example.com/foo/.",
        ("a." * 2000),
        ("https://a.b/" + "a/" * 2000 + "."),
    ):
        work = [0]
        text = CountedText(raw, work)
        chunks = SemanticChunkBuffer(character_limit=5).update(text, revision=1, force=True)
        assert "".join(chunk.text for chunk in chunks) == text
        assert work[0] <= len(text) * 30, (len(text), work[0])
