"""Resolving a recorded write's outcome when the write may not be recorded (spec 149 D1, D4).

``Api.begin_write`` returns ``None`` when nothing records the write, so every write method guards its handle. These
helpers hold that guard for the outcomes several write methods share, and ``read_before_write`` also owns the
error a write raises when a read it depends on fails. The module imports ``ApiWriteHandle`` only for
type checking: ``hassette.core.api_write_recorder`` transitively imports ``hassette.api`` at runtime.
"""

import typing

from hassette.exceptions import CommandNotSentError, OutcomeUnknownError

T = typing.TypeVar("T")

if typing.TYPE_CHECKING:
    from hassette.core.api_write_recorder import ApiWriteHandle


def resolve_unsent(record: "ApiWriteHandle | None") -> None:
    """Record a write the transport never sent: refused before sending, a read it depends on failed, or the send failed.

    For a WebSocket write, any exception that isn't a rejection or an unknown outcome comes from before or during
    the send (a closed connection, or a payload that can't be serialized), and the transport has already dropped
    the write's pending-reply entry. If the connection dropped mid-send, ``fail_all`` resolved the record first and
    this ``not_sent`` is ignored: a record keeps its first outcome.
    """
    if record is not None:
        record.resolve("not_sent")


def resolve_rest_failure(record: "ApiWriteHandle | None", exc: BaseException) -> None:
    """Resolve a REST write from the exception its request raised; no-op when nothing is recorded."""
    if record is not None:
        record.resolve_rest_failure(exc)


async def read_before_write(record: "ApiWriteHandle | None", read: typing.Awaitable[T]) -> T:
    """Await a read that must succeed before a write is sent, resolving the write as not sent if it fails.

    Any failure of the read (cancellation included) means the write never went out, so the record resolves
    ``not_sent``. A read that got no answer (:class:`OutcomeUnknownError`) says nothing about the write, so it is
    re-raised as :class:`CommandNotSentError` chained to the read's error; a caller that retries on "not sent" then
    takes its retry path. Every other exception propagates unchanged.
    """
    try:
        return await read
    except OutcomeUnknownError as exc:
        resolve_unsent(record)
        raise CommandNotSentError(
            f"write not sent: the read before it got no answer ({type(exc).__name__}: {exc})"
        ) from exc
    except BaseException:
        resolve_unsent(record)
        raise
