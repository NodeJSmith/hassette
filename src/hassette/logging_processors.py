"""Structlog event-dict processors for Hassette's log pipeline, the console renderer, and record readers.

``enable_basic_logging`` in ``hassette.logging_`` chains these. The ``console`` and ``compact`` formats print
one identity column before the message and no key=value tail; JSON output and the DB keep every field.
"""

import logging
import sys
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import structlog.dev
import structlog.types

from hassette.const import HASSETTE_LOGGER_NAME
from hassette.context import CURRENT_EXECUTION_ID
from hassette.utils.exception_utils import get_traceback_string

_RECORD_FIELDS = (
    "author",
    "app_key",
    "execution_id",
    "instance_name",
    "instance_index",
    "execution_kind",
    "listener_id",
    "job_id",
)

# Event-dict key the console identity column travels under, from console_identity to the renderer.
IDENTITY_KEY = "identity"
# Prefix on the identity column of a framework-authored line about an app.
FRAMEWORK_MARKER = f"{HASSETTE_LOGGER_NAME}:"
# Execution ids are UUIDv7, whose leading characters are a timestamp shared by executions close in
# time, so the short id is the random tail. The web UI's truncateId (frontend/src/utils/format.ts)
# shows the same tail, so a console id greps against the Log tab.
SHORT_EXECUTION_ID_LENGTH = 8
# Event-dict keys a console line keeps besides IDENTITY_KEY. ConsoleRenderer renders each one
# itself; the identity column takes the place of its ``logger`` column (see console_renderer).
CONSOLE_KEYS = ("timestamp", "level", "event", "exc_info", "exception", "stack")


def identity_label(event_dict: Mapping[str, Any]) -> str:
    """The console identity column's text for one event.

    The subject's instance name when one is bound, prefixed with ``hassette:`` when the framework
    wrote the line; otherwise the logger name without its ``hassette.`` prefix. A line inside an
    execution ends with ``@`` and the execution id's last characters.

    ``author``, ``instance_name`` and ``execution_id`` are the fields ``LogIdentityFilter`` and
    ``CorrelationFilter`` stamp on each record.
    """
    subject = event_dict.get("instance_name")
    if not subject:
        label = (event_dict.get("logger") or "").removeprefix(f"{HASSETTE_LOGGER_NAME}.")
    elif event_dict.get("author") == "framework":
        label = f"{FRAMEWORK_MARKER}{subject}"
    else:
        label = str(subject)

    execution_id = event_dict.get("execution_id")
    short_id = f"@{execution_id[-SHORT_EXECUTION_ID_LENGTH:]}" if execution_id else ""
    return " ".join(part for part in (label, short_id) if part)


# dup-ignore-start: structlog fixes the processor signature
def console_identity(
    _logger: object,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    # dup-ignore-end
    """Structlog processor: reduce a console line to its timestamp, level, identity column and event.

    Every other key is dropped; JSON output and the DB keep them.
    """
    out = {key: event_dict[key] for key in CONSOLE_KEYS if key in event_dict}
    label = identity_label(event_dict)
    if label:
        out[IDENTITY_KEY] = label
    return out


def console_renderer(*, compact: bool) -> structlog.dev.ConsoleRenderer:
    """A ConsoleRenderer that prints the identity column between the level and the event.

    ``compact`` drops the level padding for narrow viewers such as the add-on's Log tab. The event is
    never padded: nothing follows it on the line.
    """
    # Plain tracebacks: in Phase 2 this renders on the log queue's listener thread, where the default rich
    # formatter would read and repr the locals of frames the caller may still be running.
    renderer = structlog.dev.ConsoleRenderer(
        pad_level=not compact, pad_event_to=0, exception_formatter=structlog.dev.plain_traceback
    )
    # Reorder the renderer's own default columns so they keep its colors and padding settings. The
    # identity column reuses the logger column's formatter, which brackets and colors it. The ""
    # column is the renderer's required key=value fallback; it renders nothing here because
    # console_identity drops every key without a column.
    by_key = {column.key: column for column in renderer.columns}
    renderer.columns = [
        by_key[""],
        by_key["timestamp"],
        by_key["level"],
        structlog.dev.Column(IDENTITY_KEY, by_key["logger"].formatter),
        by_key["event"],
    ]
    return renderer


# dup-ignore-start: structlog fixes the processor signature
def add_execution_id(
    _logger: object,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    # dup-ignore-end
    """Structlog processor: stamp execution_id from CURRENT_EXECUTION_ID context var.

    Runs after the timestamp in both the native chain and ``foreign_pre_chain`` so structlog-native callers
    carry the execution correlation identifier. Stdlib callers rely on CorrelationFilter
    instead (the processor chain does not run for them until ProcessorFormatter picks them
    up, which is after the calling context).
    """
    event_dict["execution_id"] = CURRENT_EXECUTION_ID.get(None)
    return event_dict


def record_timestamper(fmt: str) -> Callable[[object, str, structlog.types.EventDict], structlog.types.EventDict]:
    """Structlog processor factory: stamp ``timestamp`` from a stdlib record's ``created`` time.

    For ``ProcessorFormatter``'s ``foreign_pre_chain``, which in Phase 2 runs on the log queue's listener thread,
    where ``TimeStamper`` would stamp the time the record was dequeued. Output matches ``TimeStamper(fmt=fmt,
    utc=False)``: ``"iso"`` gives a local ISO 8601 string, any other ``fmt`` is a ``strftime`` format in local time.
    stdlib ``datetime`` is used so the string is exactly what ``TimeStamper`` renders for native callers.
    """

    def stamp(_logger: object, _method_name: str, event_dict: structlog.types.EventDict) -> structlog.types.EventDict:
        record = event_dict.get("_record")
        if record is None:
            return event_dict
        created = datetime.fromtimestamp(record.created)  # noqa: DTZ006 - naive local time, as TimeStamper renders
        if fmt.upper() == "ISO":
            event_dict["timestamp"] = created.isoformat()
        else:
            event_dict["timestamp"] = created.astimezone().strftime(fmt)
        return event_dict

    return stamp


# dup-ignore-start: structlog fixes the processor signature
def extract_record_fields(
    _logger: object,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    # dup-ignore-end
    """Copy the attributes LogIdentityFilter and CorrelationFilter stamped on the LogRecord into the event dict.

    Runs in ProcessorFormatter's processors list (before remove_processors_meta) where _record is available.
    """
    record = event_dict.get("_record")
    if record:
        for key in _RECORD_FIELDS:
            val = getattr(record, key, None)
            if val is not None:
                event_dict[key] = val
    return event_dict


def structlog_event_dict(record: logging.LogRecord) -> dict[str, Any] | None:
    """The event dict a structlog-native record carries as ``msg``, or ``None`` for a stdlib record.

    ``ProcessorFormatter.wrap_for_formatter`` hands the event dict to stdlib logging as ``msg`` and marks
    the record with a ``_logger`` attribute, which is how ``ProcessorFormatter`` itself tells the two
    apart. A stdlib caller that logs a dict has no ``_logger``, so its dict is an ordinary message.
    """
    if hasattr(record, "_logger") and isinstance(record.msg, dict):
        return record.msg
    return None


# dup-ignore-start: structlog fixes the processor signature
def stack_info_to_stack(
    _logger: object,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    # dup-ignore-end
    """Move a stdlib caller's formatted stack from ``stack_info`` to ``stack``.

    ``stack`` is where StackInfoRenderer puts a structlog-native caller's stack and the key ConsoleRenderer
    renders, so every format carries both callers' stacks under one key. ProcessorFormatter hands a stdlib
    record's stack over as a ``stack_info`` string. StackInfoRenderer can't build it here: it rebuilds the
    stack from the current frame, which by format time is the formatter's, not the caller's. A ``stack``
    already in the event dict wins.
    """
    stack_info = event_dict.get("stack_info")
    if not isinstance(stack_info, str):
        return event_dict
    out = {key: value for key, value in event_dict.items() if key != "stack_info"}
    out.setdefault("stack", stack_info)
    return out


# dup-ignore-start: structlog fixes the processor signature
def resolve_exc_info(
    _logger: object,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    # dup-ignore-end
    """Replace a structlog-native caller's ``exc_info`` value with the exception tuple it refers to.

    ``exc_info=True`` means "the exception being handled", which only ``sys.exc_info()`` in the caller's
    thread can answer, and Hassette renders on the log queue's listener thread. So this runs in the native
    chain, before the record is queued. An exception instance becomes its tuple. Any other truthy value
    means the current exception, and a falsy one, or a truthy one with no exception being handled, is
    dropped, so renderers only ever see a tuple.
    """
    exc_info = event_dict.get("exc_info")
    if exc_info is None or isinstance(exc_info, tuple):
        return event_dict
    out = {key: value for key, value in event_dict.items() if key != "exc_info"}
    current = sys.exc_info()
    if isinstance(exc_info, BaseException):
        out["exc_info"] = (type(exc_info), exc_info, exc_info.__traceback__)
    elif exc_info and current[0] is not None:
        out["exc_info"] = current
    return out


def persisted_message(record: logging.LogRecord) -> str:
    """The message ``log_records`` stores for a record: its message with its stack appended.

    The table has no stack column. A structlog-native record's message is its event dict's ``event``
    and its stack is ``stack``, where ``StackInfoRenderer`` put it. A stdlib record's stack is
    ``stack_info``.
    """
    event_dict = structlog_event_dict(record)
    if event_dict is not None:
        message, stack = str(event_dict.get("event", "")), event_dict.get("stack")
    else:
        message, stack = record.getMessage(), record.stack_info
    return f"{message}\n{stack}" if stack else message


def persisted_exc_text(record: logging.LogRecord) -> str | None:
    """The formatted traceback ``log_records`` stores for a record, or ``None`` when it has no exception.

    A native ``error(..., exc_info=True)`` leaves ``record.exc_info`` unset; ``resolve_exc_info`` put
    the tuple in the event dict instead.
    """
    event_dict = structlog_event_dict(record)
    exc_info = event_dict.get("exc_info") if event_dict is not None else None
    exc_info = exc_info or record.exc_info
    if exc_info and exc_info[1] is not None:
        return get_traceback_string(exc_info[1])
    return None
