import asyncio
import contextlib
import logging
import logging.handlers
import queue
import typing
from typing import ClassVar

from hassette.core.database_service import DatabaseService
from hassette.logging_ import (
    CorrelationFilter,
    HassetteQueueListener,
    LogCaptureHandler,
    LogPersistenceHandler,
)
from hassette.resources.base import Resource

if typing.TYPE_CHECKING:
    from hassette import Hassette

_QUEUE_LISTENER_STOP_TIMEOUT_SECONDS = 5.0


class LoggingService(Resource):
    """Owns the full async logging pipeline.

    Phase 2 of the two-phase logging model: upgrades from the synchronous
    StreamHandler installed by ``enable_basic_logging()`` to a full async
    pipeline — QueueHandler + HassetteQueueListener dispatching to stream,
    capture, and persistence handlers.

    The async pipeline starts unconditionally. Persistence degrades gracefully
    on failure (QueueListener still runs with stream + capture handlers).
    """

    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]

    capture_handler: LogCaptureHandler
    persistence_handler: LogPersistenceHandler | None

    def __init__(
        self,
        hassette: "Hassette",
        *,
        stream_handler: logging.StreamHandler | None,
        parent: "Resource | None" = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        self._stream_handler = stream_handler
        self.capture_handler = LogCaptureHandler(buffer_size=hassette.config.web_api.log_buffer_size)
        self.persistence_handler = None
        self._queue_listener: HassetteQueueListener | None = None
        self._queue_handler: logging.handlers.QueueHandler | None = None

    async def on_initialize(self) -> None:
        """Upgrade logging from sync to async pipeline."""
        hassette_logger = logging.getLogger("hassette")

        for h in list(hassette_logger.handlers):
            if isinstance(h, logging.handlers.QueueHandler):
                hassette_logger.removeHandler(h)
        if self._queue_listener is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._queue_listener.stop)
            self._queue_listener = None

        handlers: list[logging.Handler] = []
        if self._stream_handler is not None:
            handlers.append(self._stream_handler)
        handlers.append(self.capture_handler)

        # Resolve persistence level before the try block so config errors raise loudly
        persistence_level = logging.getLevelNamesMapping()[self.hassette.config.logging.log_persistence_level]

        # Best-effort: add persistence handler
        try:
            loop = asyncio.get_running_loop()
            self.persistence_handler = LogPersistenceHandler(
                self.hassette.database_service,
                loop,
                persistence_level=persistence_level,
            )
            handlers.append(self.persistence_handler)
        except Exception:
            self.logger.exception("Failed to create persistence handler — logs will not be persisted")
            self.persistence_handler = None

        q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=self.hassette.config.logging.log_queue_max)
        queue_handler = logging.handlers.QueueHandler(q)
        queue_handler.addFilter(CorrelationFilter())

        listener = HassetteQueueListener(q, *handlers)

        # Atomic swap: add QueueHandler FIRST, then remove StreamHandler
        hassette_logger.addHandler(queue_handler)
        if self._stream_handler is not None:
            hassette_logger.removeHandler(self._stream_handler)

        listener.start()

        self._queue_listener = listener
        self._queue_handler = queue_handler

        self.mark_ready(reason="LoggingService initialized")

    async def on_shutdown(self) -> None:
        """Stop the async logging pipeline and restore synchronous console logging."""
        self.capture_handler.shutting_down = True
        hassette_logger = logging.getLogger("hassette")

        if self._queue_handler is not None:
            hassette_logger.removeHandler(self._queue_handler)
        if self._stream_handler is not None:
            hassette_logger.addHandler(self._stream_handler)

        self.logger.warning("LoggingService shutting down — subsequent log records will be console-only")

        # Stop QueueListener via asyncio.to_thread() to avoid blocking the event loop
        if self._queue_listener is not None:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._queue_listener.stop),
                    timeout=_QUEUE_LISTENER_STOP_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                self.logger.warning(
                    "QueueListener.stop() timed out after %ss during shutdown",
                    _QUEUE_LISTENER_STOP_TIMEOUT_SECONDS,
                )
            except Exception:
                self.logger.warning("QueueListener.stop() raised an exception during shutdown", exc_info=True)

        if self.persistence_handler is not None:
            self.persistence_handler.flush_if_pending()

    @property
    def dropped_count(self) -> int:
        """Return the number of log records dropped by the persistence handler."""
        if self.persistence_handler is None:
            return 0
        return self.persistence_handler.dropped_count
