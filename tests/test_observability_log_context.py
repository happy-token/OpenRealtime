import asyncio
import logging

from server.observability.log_context import (
    VoiceSessionLogFilter,
    bind_voice_session_log_context,
    set_current_generation,
)


def _logger_with_filter() -> logging.Logger:
    logger = logging.getLogger("test_log_context")
    logger.handlers.clear()
    logger.addFilter(VoiceSessionLogFilter())
    logger.setLevel(logging.DEBUG)
    return logger


def test_outside_any_bound_context_fields_default_to_placeholders(caplog):
    logger = _logger_with_filter()
    with caplog.at_level(logging.INFO):
        logger.info("no context")
    record = caplog.records[-1]
    assert record.voice_session_id == "-"
    assert record.generation is None


def test_bound_context_stamps_voice_session_id_and_generation(caplog):
    logger = _logger_with_filter()
    with caplog.at_level(logging.INFO):
        with bind_voice_session_log_context("vs-1", generation=3):
            logger.info("inside")
    record = caplog.records[-1]
    assert record.voice_session_id == "vs-1"
    assert record.generation == 3


def test_context_resets_after_the_with_block_exits(caplog):
    logger = _logger_with_filter()
    with caplog.at_level(logging.INFO):
        with bind_voice_session_log_context("vs-1"):
            pass
        logger.info("after")
    record = caplog.records[-1]
    assert record.voice_session_id == "-"


def test_set_current_generation_updates_without_reopening_scope(caplog):
    logger = _logger_with_filter()
    with caplog.at_level(logging.INFO):
        with bind_voice_session_log_context("vs-1", generation=1):
            set_current_generation(2)
            logger.info("bumped")
    record = caplog.records[-1]
    assert record.voice_session_id == "vs-1"
    assert record.generation == 2


async def test_context_propagates_to_child_tasks(caplog):
    logger = _logger_with_filter()
    captured: dict[str, object] = {}

    async def child() -> None:
        logger.info("from child")
        captured["record"] = caplog.records[-1]

    with caplog.at_level(logging.INFO):
        with bind_voice_session_log_context("vs-parent", generation=7):
            await asyncio.create_task(child())
    record = captured["record"]
    assert record.voice_session_id == "vs-parent"
    assert record.generation == 7
