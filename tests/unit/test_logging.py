"""Tests for LogEntry seq field and LogCaptureHandler seq incrementing."""

import logging

from hassette.logging_ import LogCaptureHandler, LogEntry


class TestLogCaptureHandlerSeqIncrements:
    """seq increments monotonically from 1 across multiple emit() calls."""

    def test_seq_increments_monotonically(self) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        logger = logging.getLogger("test.seq_increment")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        for _ in range(5):
            logger.info("test message")

        entries = list(handler.buffer)
        assert len(entries) == 5
        assert [e.seq for e in entries] == [1, 2, 3, 4, 5]

        logger.removeHandler(handler)

    def test_seq_starts_at_one(self) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        logger = logging.getLogger("test.seq_start")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        logger.info("first")

        entries = list(handler.buffer)
        assert entries[0].seq == 1

        logger.removeHandler(handler)

    def test_separate_handlers_have_independent_seq(self) -> None:
        handler_a = LogCaptureHandler(buffer_size=100)
        handler_b = LogCaptureHandler(buffer_size=100)

        logger_a = logging.getLogger("test.seq_a")
        logger_a.addHandler(handler_a)
        logger_a.setLevel(logging.DEBUG)

        logger_b = logging.getLogger("test.seq_b")
        logger_b.addHandler(handler_b)
        logger_b.setLevel(logging.DEBUG)

        for _ in range(3):
            logger_a.info("a msg")
        for _ in range(2):
            logger_b.info("b msg")

        assert [e.seq for e in handler_a.buffer] == [1, 2, 3]
        assert [e.seq for e in handler_b.buffer] == [1, 2]

        logger_a.removeHandler(handler_a)
        logger_b.removeHandler(handler_b)


class TestLogEntryToDictIncludesSeq:
    """to_dict() includes the seq field."""

    def test_to_dict_contains_seq(self) -> None:
        entry = LogEntry(
            seq=42,
            timestamp=1234567890.0,
            level="INFO",
            logger_name="hassette.test",
            func_name="test_func",
            lineno=10,
            message="hello",
        )
        d = entry.to_dict()
        assert d["seq"] == 42

    def test_to_dict_seq_position(self) -> None:
        """seq should be present alongside timestamp in the dict."""
        entry = LogEntry(
            seq=7,
            timestamp=1000.0,
            level="DEBUG",
            logger_name="test",
            func_name="fn",
            lineno=1,
            message="msg",
        )
        d = entry.to_dict()
        assert "seq" in d
        assert "timestamp" in d
