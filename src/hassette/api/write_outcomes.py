"""Resolving a recorded write's outcome when the write may not be recorded (spec 149 D1, D4).

``Api.begin_write`` returns ``None`` when nothing records the write, so every write method guards its handle. These
helpers hold that guard for the outcomes several write methods share. The module imports ``ApiWriteHandle`` only for
type checking: ``hassette.core.api_write_recorder`` transitively imports ``hassette.api`` at runtime.
"""

import typing

if typing.TYPE_CHECKING:
    from hassette.core.api_write_recorder import ApiWriteHandle


def resolve_unsent(record: "ApiWriteHandle | None") -> None:
    """Record a write the transport never sent: refused before sending, or the send itself failed.

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
