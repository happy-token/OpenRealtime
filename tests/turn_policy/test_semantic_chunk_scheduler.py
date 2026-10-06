from server.turn_policy.semantic_chunk_scheduler import SemanticChunkScheduler


def test_single_flight_and_bounded_context():
    scheduler = SemanticChunkScheduler(character_limit=64)
    scheduler.observe("好的，嗯嗯，明白，", revision=1, stable=True)
    first = scheduler.begin_next()
    assert first is not None
    assert scheduler.begin_next() is None
    assert scheduler.complete("stale") is None
    assert scheduler.active == first
    scheduler.complete(first.chunk_id, feedback=True)
    second = scheduler.begin_next()
    scheduler.complete(second.chunk_id, feedback=True)
    third = scheduler.begin_next()
    scheduler.complete(third.chunk_id, feedback=False)
    assert scheduler.previous_chunks == ("嗯嗯，", "明白，")
    assert not scheduler.feedback_only
    assert not scheduler.busy


def test_rewrite_invalidates_inflight_result_and_feedback_context():
    scheduler = SemanticChunkScheduler(character_limit=64)
    scheduler.observe("好的，查北京天气。", revision=1, stable=True)
    first = scheduler.begin_next()
    scheduler.complete(first.chunk_id, feedback=True)
    stale = scheduler.begin_next()
    update = scheduler.observe("不是，查上海天气。", revision=2, stable=True)
    assert update.invalidated_active == stale
    assert scheduler.complete(stale.chunk_id, feedback=True) is None
    assert scheduler.previous_chunks == ()
    assert not scheduler.feedback_only
    assert scheduler.begin_next().text == "不是，"


def test_pending_overflow_merges_without_resending_active_chunk():
    scheduler = SemanticChunkScheduler(character_limit=64, pending_limit=2)
    scheduler.observe("第一句，", revision=1, stable=True)
    active = scheduler.begin_next()
    update = scheduler.observe("第一句，第二句，第三句，第四句，", revision=2, stable=True)
    assert update.merged is not None
    assert len(update.merged_sources) == 3
    assert scheduler.active == active
    scheduler.complete(active.chunk_id)
    merged = scheduler.begin_next()
    assert merged.text == "第二句，第三句，第四句，"
    scheduler.complete(merged.chunk_id)
    assert not scheduler.busy


def test_parallel_bound_and_out_of_order_context():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    scheduler.observe("第一句，第二句，第三句，", revision=1, stable=True)
    first, second = scheduler.begin_next(), scheduler.begin_next()
    assert scheduler.begin_next() is None
    assert scheduler.context_before(second) == ("第一句，",)
    assert scheduler.complete(second.chunk_id) == second
    third = scheduler.begin_next()
    assert third.text == "第三句，"
    scheduler.complete(first.chunk_id)
    scheduler.complete(third.chunk_id)
    assert scheduler.previous_chunks == ("第二句，", "第三句，")
    assert not scheduler.busy


def test_rewrite_cancels_only_invalid_candidates():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    scheduler.observe("第一句，查北京。", revision=1, stable=True)
    first, second = scheduler.begin_next(), scheduler.begin_next()
    update = scheduler.observe("第一句，查上海。", revision=2, stable=True)
    assert update.invalidated_candidates == (second,)
    assert scheduler.matches_active(first.chunk_id)
    assert not scheduler.matches_active(second.chunk_id)
    assert scheduler.begin_next().text == "查上海。"


def test_issued_candidate_history_stays_bounded_for_long_input():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    text = ''
    previous = []
    for number in range(300):
        next_text = f'第{number}句，'
        text += next_text
        scheduler.observe(text, revision=number + 1, stable=True)
        chunk = scheduler.begin_next()
        assert scheduler.context_before(chunk) == tuple(previous[-2:])
        scheduler.complete(chunk.chunk_id)
        previous.append(next_text)
    retained = sum(
        len(value) for value in vars(scheduler).values() if isinstance(value, (list, dict))
    )
    assert retained <= 6  # Queue/accepted/inflight metadata, excluding buffer revision evidence.


def test_deep_rewrites_recover_valid_issued_context_without_accumulating_metadata():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    prefix = '第一句，第二句，'
    scheduler.observe(prefix, revision=1, stable=True)
    first, second = scheduler.begin_next(), scheduler.begin_next()
    scheduler.complete(first.chunk_id)
    scheduler.complete(second.chunk_id)
    text = prefix
    for number in range(30):
        text += f'第{number}段，'
        scheduler.observe(text, revision=number + 2, stable=True)
        chunk = scheduler.begin_next()
        scheduler.complete(chunk.chunk_id)
    for number in range(300):
        scheduler.observe(prefix + f'新版本{number}，', revision=number + 40, stable=True)
        chunk = scheduler.begin_next()
        assert scheduler.context_before(chunk) == ('第一句，', '第二句，')
        scheduler.complete(chunk.chunk_id)
    assert not scheduler.busy


def test_unissued_cancelled_pending_chunks_are_not_prior_context():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    scheduler.observe('第一句，第二句，第三句，', revision=1, stable=True)
    first = scheduler.begin_next()
    scheduler.cancel_active()
    scheduler.observe('第一句，第二句，第三句，第四句，', revision=2, stable=True)
    fourth = scheduler.begin_next()
    assert scheduler.context_before(fourth) == (first.text,)


def test_context_stays_ordered_while_old_candidate_remains_inflight():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    scheduler.observe('第一句，', revision=1, stable=True)
    first = scheduler.begin_next()
    text = first.text
    previous = [first.text]
    for number in range(300):
        text += f'第{number}段，'
        scheduler.observe(text, revision=number + 2, stable=True)
        chunk = scheduler.begin_next()
        assert scheduler.context_before(chunk) == tuple(previous[-2:])
        scheduler.complete(chunk.chunk_id)
        previous.append(chunk.text)
    assert scheduler.context_before(first) == ()
    assert scheduler.complete(first.chunk_id) == first


def test_unresolved_predecessor_is_not_confirmed_feedback():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    scheduler.observe('不是北京是上海，嗯。', revision=1, stable=True)
    first, second = scheduler.begin_next(), scheduler.begin_next()
    assert not scheduler.feedback_only_before(second)
    scheduler.complete(second.chunk_id, feedback=True)
    assert not scheduler.feedback_only_before(second)
    scheduler.complete(first.chunk_id, feedback=False)
    assert not scheduler.feedback_only_before(second)
    assert scheduler.feedback_only_before(first)


def test_feedback_prefix_requires_all_predecessors_not_just_two_context_chunks():
    scheduler = SemanticChunkScheduler(character_limit=64)
    scheduler.observe('查上海天气，好的，明白，嗯。', revision=1, stable=True)
    first = scheduler.begin_next()
    scheduler.complete(first.chunk_id, feedback=False)
    for _ in range(2):
        feedback = scheduler.begin_next()
        scheduler.complete(feedback.chunk_id, feedback=True)
    tail = scheduler.begin_next()
    assert scheduler.context_before(tail) == ('好的，', '明白，')
    assert not scheduler.feedback_only_before(tail)


def test_feedback_prefix_recovers_from_rewrite_and_out_of_order_completion():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    scheduler.observe('好的，明白，嗯。', revision=1, stable=True)
    first, second = scheduler.begin_next(), scheduler.begin_next()
    scheduler.complete(second.chunk_id, feedback=True)
    tail = scheduler.begin_next()
    assert not scheduler.feedback_only_before(tail)
    scheduler.complete(first.chunk_id, feedback=True)
    assert scheduler.feedback_only_before(tail)
    scheduler.complete(tail.chunk_id, feedback=False)
    scheduler.observe('好的，明白，哦。', revision=2, stable=True)
    rewritten_tail = scheduler.begin_next()
    assert scheduler.feedback_only_before(rewritten_tail)
    scheduler.observe('好的，不是，哦。', revision=3, stable=True)
    rewritten_middle = scheduler.begin_next()
    new_tail = scheduler.begin_next()
    assert scheduler.feedback_only_before(rewritten_middle)
    assert not scheduler.feedback_only_before(new_tail)
    scheduler.complete(rewritten_tail.chunk_id, feedback=True)
    assert not scheduler.feedback_only_before(new_tail)


def test_cumulative_text_preserves_punctuation_without_later_semantics():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    text = '今天去北京，  然后去上海？'
    scheduler.observe(text, revision=1, stable=True)
    first, second = scheduler.begin_next(), scheduler.begin_next()
    assert scheduler.cumulative_text(first) == '今天去北京，  '
    assert scheduler.cumulative_text(second) == text
    assert scheduler.begin_next() is None


def test_cumulative_text_uses_equivalent_raw_punctuation_revision():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    scheduler.observe('先查天气，再查时间。', revision=1, stable=True)
    first, second = scheduler.begin_next(), scheduler.begin_next()
    update = scheduler.observe('  先查天气？！  再查时间！ ', revision=2, stable=True)
    assert update.sealed == ()
    assert update.invalidated_candidates == ()
    assert scheduler.cumulative_text(first) == '  先查天气？！  '
    assert scheduler.cumulative_text(second) == '  先查天气？！  再查时间！ '


def test_cumulative_text_for_merged_candidate_preserves_current_raw_prefix():
    scheduler = SemanticChunkScheduler(character_limit=64, pending_limit=2)
    scheduler.observe('第一句，', revision=1, stable=True)
    first = scheduler.begin_next()
    update = scheduler.observe('第一句，第二句；第三句？第四句！', revision=2, stable=True)
    assert update.merged is not None
    scheduler.complete(first.chunk_id)
    merged = scheduler.begin_next()
    assert scheduler.cumulative_text(merged) == '第一句，第二句；第三句？第四句！'
    scheduler.observe('第一句，第二句；第三句？第四句！  第五句。', revision=3, stable=True)
    assert scheduler.cumulative_text(merged) == '第一句，第二句；第三句？第四句！  '
    scheduler.complete(merged.chunk_id)
    assert scheduler.begin_next().text == '第五句。'


def test_cumulative_text_invalid_candidate_has_no_misleading_full_text():
    scheduler = SemanticChunkScheduler(character_limit=64, max_concurrency=2)
    scheduler.observe('查北京天气，明天下雨吗？', revision=1, stable=True)
    first, second = scheduler.begin_next(), scheduler.begin_next()
    scheduler.observe('查上海天气，明天下雨吗？', revision=2, stable=True)
    assert scheduler.cumulative_text(first) is None
    assert scheduler.cumulative_text(second) is None
