"""Structlog event-dict processors for Hassette's log pipeline, and the console renderer.

``enable_basic_logging`` in ``hassette.logging_`` chains these. The ``console`` and ``compact`` formats print
one identity column before the message and no key=value tail; JSON output and the DB keep every field.
"""

from collections.abc import Mapping
from typing import Any

import structlog.dev
import structlog.types

from hassette.const import HASSETTE_LOGGER_NAME
from hassette.context import CURRENT_EXECUTION_ID

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
    renderer = structlog.dev.ConsoleRenderer(pad_level=not compact, pad_event_to=0)
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

    Inserted in the shared processor chain after TimeStamper so structlog-native callers
    carry the execution correlation identifier. Stdlib callers rely on CorrelationFilter
    instead (the processor chain does not run for them until ProcessorFormatter picks them
    up, which is after the calling context).
    """
    event_dict["execution_id"] = CURRENT_EXECUTION_ID.get(None)
    return event_dict


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
