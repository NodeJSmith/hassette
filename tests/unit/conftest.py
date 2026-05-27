"""Shared fixtures for tests/unit/."""

import logging
import logging.handlers
import queue
from dataclasses import dataclass
from io import StringIO
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
import structlog.processors
import structlog.stdlib

from hassette.logging_ import (
    CorrelationFilter,
    HassetteQueueListener,
    LogCaptureHandler,
    LogPersistenceHandler,
    _extract_record_fields,  # pyright: ignore[reportPrivateUsage]
    add_execution_id,
)


@dataclass
class LoggingPipelineFixture:
    """Holds all components of a local logging pipeline."""

    stream: StringIO
    stream_handler: logging.StreamHandler
    capture: LogCaptureHandler
    listener: HassetteQueueListener
    queue_handler: logging.handlers.QueueHandler
    logger: logging.Logger


@pytest.fixture
def logging_pipeline() -> "LoggingPipelineFixture":  # pyright: ignore[reportReturnType]
    """Local logging pipeline for unit tests — no module globals.

    Constructs a self-contained QueueListener + stream/capture handlers, wires them
    to the hassette logger, yields the fixture, then tears down cleanly.
    """
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_execution_id,
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            _extract_record_fields,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    stream = StringIO()
    stream_handler = logging.StreamHandler(stream)
    stream_handler.setLevel(logging.NOTSET)
    stream_handler.setFormatter(formatter)

    capture = LogCaptureHandler(buffer_size=100)

    q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=100)
    queue_handler = logging.handlers.QueueHandler(q)
    queue_handler.addFilter(CorrelationFilter())

    listener = HassetteQueueListener(q, stream_handler, capture)
    listener.start()

    logger = logging.getLogger("hassette")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(queue_handler)

    fixture_obj = LoggingPipelineFixture(
        stream=stream,
        stream_handler=stream_handler,
        capture=capture,
        listener=listener,
        queue_handler=queue_handler,
        logger=logger,
    )

    yield fixture_obj  # pyright: ignore[reportReturnType]

    listener.stop()
    logger.removeHandler(queue_handler)


@dataclass
class PersistenceFixture:
    """Holds a LogPersistenceHandler wired to a mock DatabaseService."""

    handler: LogPersistenceHandler
    db_service: MagicMock
    enqueued_batches: list[list[dict]]


@pytest.fixture
def persistence_handler() -> PersistenceFixture:
    """LogPersistenceHandler with a mock DatabaseService.

    - spec=[] on mocks prevents auto-attribute creation (avoids MagicMock deadlock).
    - call_soon_threadsafe executes immediately — makes flush deterministic.
    - enqueued_batches captures every batch passed to _insert_log_records.
    """
    enqueued_batches: list[list[dict]] = []

    mock_db_service = MagicMock(spec=[])
    mock_db_service.enqueue = MagicMock(return_value=True)

    def capture_insert(records: list[dict]) -> object:
        enqueued_batches.append(records)
        return AsyncMock()()

    mock_db_service._insert_log_records = MagicMock(side_effect=capture_insert)

    mock_loop = MagicMock(spec=[])
    mock_loop.call_soon_threadsafe = MagicMock(side_effect=lambda fn: fn())
    mock_loop.is_running = MagicMock(return_value=True)

    handler = LogPersistenceHandler(mock_db_service, mock_loop, persistence_level=logging.DEBUG)

    return PersistenceFixture(
        handler=handler,
        db_service=mock_db_service,
        enqueued_batches=enqueued_batches,
    )
