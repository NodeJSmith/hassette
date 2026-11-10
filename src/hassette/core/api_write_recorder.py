"""Records each named ``Api`` write an app sends to Home Assistant, and how it ended.

One ``ApiWriteRecorder`` per process, created by ``Hassette``. An app's ``Api`` calls ``begin`` once per
write, at send: it enqueues the ``pending`` row and returns an ``ApiWriteHandle`` whose ``resolve`` enqueues
the outcome. Who calls ``resolve`` is fixed per transport (design/specs/149-api-write-records D1, D4): a
WebSocket write's pending-reply entry owns it, except for ``not_sent``, which the caller records; a REST
write's caller owns every outcome.

Rows go through the database write queue, which is FIFO with one writer, so a row's insert always lands
before its update as long as ``begin`` runs before the request is registered or sent. Recording is
best-effort: a dropped row or update is counted and warned about once per episode, never retried, and
never raised into the app.
"""

import logging
import time
import typing
from dataclasses import dataclass, field
from typing import Any

import uuid_utils
from hassette_wire import ApiWriteKind, ApiWriteOutcome

from hassette.context import CURRENT_EXECUTION_ID
from hassette.core.execution_record_builder import format_display_value
from hassette.core.pipeline_counters import PipelineCounter
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.exceptions import CommandNotSentError, EntityNotFoundError, HttpRequestError

if typing.TYPE_CHECKING:
    from collections.abc import Coroutine

    from hassette import Hassette

LOGGER = logging.getLogger(__name__)

API_WRITE_DATA_MAX_CHARS = 2048
"""Code points of a write's ``data`` display string kept before it is cut with a trailing ``…``."""

HTTP_NOT_FOUND = "404"
"""``error_code`` for a REST write whose entity doesn't exist; stored as text like every other code."""


@dataclass(frozen=True, slots=True)
class ApiWriteRow:
    """The columns of a new ``api_writes`` row, written as ``pending`` at send."""

    write_id: str
    session_id: int | None
    app_key: str
    instance_name: str
    execution_id: str | None
    kind: ApiWriteKind
    operation: str | None
    target: dict[str, list[str]] | None
    data: str | None
    sent_ts: float


@dataclass(slots=True)
class ApiWriteHandle:
    """One recorded write's identity, and the means to resolve its row exactly once.

    Holds no target or data, so a pending-reply entry carrying ``resolve`` stays small. The first ``resolve``
    wins and later ones are ignored: a connection that drops while a frame is still being sent resolves the
    row as ``connection_lost`` from ``fail_all``, and the send's own failure must not then overwrite it.
    """

    write_id: str
    execution_id: str | None
    kind: ApiWriteKind
    operation: str | None
    fire_and_forget: bool
    """Fixed at send: nobody waits on the call, so a rejection is reported by a WARNING instead of an exception."""
    logger: logging.Logger
    """The app's ``Api`` logger, so the rejected-call WARNING lands in that app's logs."""
    recorder: "ApiWriteRecorder"
    resolved: bool = field(default=False, init=False)
    """Set by the first ``resolve``. All callers run on the event loop, so a plain flag is enough."""

    # dup-ignore-start: ResolveCallback protocol signature restated by its implementation and its caller
    def resolve(
        self,
        outcome: ApiWriteOutcome,
        *,
        context_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        # dup-ignore-end
        """Enqueue the row's outcome; for a rejected fire-and-forget call, also log the rejected-call WARNING.

        A no-op once the row has been resolved.
        """
        if self.resolved:
            return
        self.resolved = True
        resolved_ts = None if outcome == "unresolved" else time.time()
        self.recorder.enqueue(
            self.recorder.repository.update_api_write_outcome(
                self.write_id,
                outcome=outcome,
                context_id=context_id,
                error_code=error_code,
                error_message=error_message,
                resolved_ts=resolved_ts,
            )
        )
        if outcome == "rejected" and self.fire_and_forget:
            self.warn_rejected(error_code, error_message)

    def warn_rejected(self, error_code: str | None, error_message: str | None) -> None:
        """Log the rejection under the run that made the call, so it shows with that execution's logs."""
        token = CURRENT_EXECUTION_ID.set(self.execution_id)
        try:
            self.logger.warning(
                "Home Assistant rejected %s %s (code %r): %s (execution %s, write %s)",
                self.kind,
                self.operation,
                error_code,
                error_message,
                self.execution_id,
                self.write_id,
            )
        finally:
            CURRENT_EXECUTION_ID.reset(token)

    def resolve_rest_failure(self, exc: BaseException) -> None:
        """Resolve a REST write from the exception its request raised."""
        if isinstance(exc, CommandNotSentError):
            self.resolve("not_sent")
        elif isinstance(exc, EntityNotFoundError):
            self.resolve("rejected", error_code=HTTP_NOT_FOUND, error_message=str(exc))
        elif isinstance(exc, HttpRequestError):
            self.resolve("rejected", error_code=str(exc.status), error_message=exc.message)
        else:
            # Sent, then timed out, dropped, failed reading the body, or cancelled: the outcome is unknown.
            self.resolve("connection_lost")


class ApiWriteRecorder:
    """Writes ``api_writes`` rows for app-owned ``Api`` writes through the database write queue."""

    def __init__(self, hassette: "Hassette") -> None:
        self.hassette = hassette
        self.repository = TelemetryRepository(hassette.database_service)
        self.logger = LOGGER
        self.last_drop_warn_ts: float | None = None

    def begin(
        self,
        *,
        api_logger: logging.Logger,
        app_key: str,
        instance_name: str,
        kind: ApiWriteKind,
        operation: str | None,
        target: dict[str, list[str]] | None,
        data: Any,
        fire_and_forget: bool = False,
    ) -> ApiWriteHandle:
        """Enqueue a ``pending`` row for a write about to be sent, and return the handle that resolves it.

        Must run before the request is registered or sent, so the insert is queued ahead of any update.

        Args:
            api_logger: The app's ``Api`` logger, for the rejected-call WARNING.
            app_key: The app making the write.
            instance_name: The app instance making the write.
            kind: Which named write this is.
            operation: ``domain.service``, the event type, or the helper domain; None otherwise.
            target: The normalized target (see ``service_call_target``).
            data: Everything else the caller passed, from the caller's own payload (``SecretStr`` still wrapped).
            fire_and_forget: Whether nobody waits on the call.
        """
        execution_id = CURRENT_EXECUTION_ID.get()
        handle = ApiWriteHandle(
            write_id=str(uuid_utils.uuid7()),
            execution_id=execution_id,
            kind=kind,
            operation=operation,
            fire_and_forget=fire_and_forget,
            logger=api_logger,
            recorder=self,
        )
        row = ApiWriteRow(
            write_id=handle.write_id,
            session_id=self.hassette.try_session_id(),
            app_key=app_key,
            instance_name=instance_name,
            execution_id=execution_id,
            kind=kind,
            operation=operation,
            target=target,
            data=None if data is None else format_display_value(data, API_WRITE_DATA_MAX_CHARS),
            sent_ts=time.time(),
        )
        self.enqueue(self.repository.insert_api_write(row))
        return handle

    def enqueue(self, coro: "Coroutine[Any, Any, None]") -> None:
        """Queue a row write fire-and-forget; count and warn on a drop, never raise."""
        try:
            queued = self.hassette.database_service.enqueue(coro)
        except RuntimeError:
            # enqueue() raises RuntimeError only when the queue isn't live (before startup or after shutdown).
            self.logger.debug("Database service not ready — dropping api_writes row write")
            return
        if queued:
            return
        self.hassette.pipeline_counters.increment(PipelineCounter.API_WRITE_RECORD_DROPPED)
        self.warn_drop()

    def warn_drop(self) -> None:
        """Log one WARNING per drop episode, paced like the execution write queue's capacity WARNING."""
        now = time.monotonic()
        interval = self.hassette.config.lifecycle.command_executor_capacity_warn_rate_limit_seconds
        if self.last_drop_warn_ts is not None and now - self.last_drop_warn_ts < interval:
            return
        self.last_drop_warn_ts = now
        self.logger.warning(
            "Database write queue is full; dropping API write records (counted under %s)",
            PipelineCounter.API_WRITE_RECORD_DROPPED.name,
        )
