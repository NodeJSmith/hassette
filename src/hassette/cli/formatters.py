"""Value formatters for hassette CLI output: durations, relative times, uptime, and labels.

Each formatter turns one raw field value into a display string. The rendering layer
(:mod:`hassette.cli.output`) applies them to table cells and detail-panel rows.
"""

import re
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from hassette_wire import LogEntry, ResourceStatus
from whenever import SYSTEM_TZ, Instant, OffsetDateTime, PlainDateTime

from hassette.const.misc import SECONDS_PER_DAY, SECONDS_PER_HOUR, SECONDS_PER_MINUTE

#: Past deltas shorter than this many seconds render as "just now".
JUST_NOW_SECONDS = 5
MS_PER_SECOND = 1000
#: Placeholder shown for a missing or empty value in detail panels and summary cells.
EMPTY_VALUE = "—"

# First line of a formatted exception group traceback, once the text is stripped.
EXCEPTION_GROUP_TRACEBACK_HEADER = "+ Exception Group Traceback"
# A ``| Type: message`` line inside one; the first is the outermost group's own.
EXCEPTION_GROUP_LINE_RE = re.compile(r"^\s*\| (\w[\w.]*: .*)$")
TRACEBACK_HEADER = "Traceback (most recent call last):"
# Lines that end one exception's section in a chained traceback; the logged exception's section comes last.
CHAINED_EXCEPTION_SEPARATORS = frozenset(
    {
        "The above exception was the direct cause of the following exception:",
        "During handling of the above exception, another exception occurred:",
    }
)


def now_epoch() -> float:
    """Return current time as epoch float. Patched in tests for determinism."""
    return time.time()


def numeric_formatter(func: Callable[[float], str]) -> Callable[[Any], str]:
    """Wrap a float formatter: ``None`` renders as ``""`` and a non-numeric value as ``str(value)``."""

    @wraps(func)
    def wrapper(value: Any) -> str:
        if value is None:
            return ""
        try:
            num = float(value)
        except (TypeError, ValueError):
            return str(value)
        return func(num)

    return wrapper


def fmt_relative_time(value: Any) -> str:
    """Convert an epoch float or ISO string to a relative time string.

    Examples: "2m ago", "1h ago", "just now", "in 5m".
    """
    if value is None:
        return ""
    try:
        delta = now_epoch() - _parse_timestamp(value)
        if delta < 0:
            ahead = -delta
            if ahead < SECONDS_PER_MINUTE:
                return "in <1m"
            return f"in {_delta_label(ahead)}"
        if delta < JUST_NOW_SECONDS:
            return "just now"
        if delta < SECONDS_PER_MINUTE:
            return f"{int(delta)}s ago"
        return f"{_delta_label(delta)} ago"
    except (TypeError, ValueError, OSError):
        return str(value)


def _parse_timestamp(value: Any) -> float:
    """Convert an epoch number or ISO string to epoch seconds.

    HA timestamps vary: UTC instant, offset, or bare local datetime. A bare datetime is read in
    the user's terminal timezone (CLI display), not the configured Hassette timezone.

    Raises:
        ValueError: If a string matches none of the accepted ISO forms.
    """
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value)
    try:
        return Instant.parse_iso(s).timestamp()
    except ValueError:
        pass
    try:
        return OffsetDateTime.parse_iso(s).timestamp()
    except ValueError:
        pass
    return PlainDateTime.parse_iso(s).assume_tz(SYSTEM_TZ, disambiguation="compatible").timestamp()


def _delta_label(seconds: float) -> str:
    """Render a non-negative span of at least a minute as whole minutes, hours, or days (``"5m"``)."""
    if seconds < SECONDS_PER_HOUR:
        return f"{int(seconds / SECONDS_PER_MINUTE)}m"
    if seconds < SECONDS_PER_DAY:
        return f"{int(seconds / SECONDS_PER_HOUR)}h"
    return f"{int(seconds / SECONDS_PER_DAY)}d"


@numeric_formatter
def fmt_duration_ms(ms: float) -> str:
    """Convert a duration in milliseconds to a human-readable string."""
    if abs(ms) < MS_PER_SECOND:
        return f"{ms:.0f}ms"
    return f"{ms / MS_PER_SECOND:.1f}s"


@numeric_formatter
def fmt_duration_s(num: float) -> str:
    """Convert a duration in seconds to a human-readable string."""
    if abs(num) < 1:
        return f"{num * MS_PER_SECOND:.0f}ms"
    return f"{num:.1f}s"


def fmt_log_author(value: Any) -> str:
    """Mark framework-authored log lines and leave app lines blank, so the framework ones stand out."""
    return "framework" if value == "framework" else ""


def fmt_log_message(entry: LogEntry) -> str:
    """The entry's message, with its exception's ``Type: message`` line (``ValueError: kaboom``) beneath it.

    A chained traceback lists earlier exceptions first, so only the last section is read. In it, everything
    describing the stack (frames, source and caret lines, repeated-frame markers) is indented, so the exception's
    line is the first unindented line after the ``Traceback`` header; a multi-line message continues below it.
    An exception group's section is indented throughout, so its line is the group's own
    ``| ExceptionGroup: ...`` header. The full traceback is in ``--json`` output and the web dashboard's log detail.

    This parses rendered text; capturing the summary when the exception is logged would replace it (#749).
    """
    lines = (entry.exc_info or "").strip().splitlines()
    start = next((i + 1 for i in range(len(lines) - 1, -1, -1) if lines[i] in CHAINED_EXCEPTION_SEPARATORS), 0)
    section = [line for line in lines[start:] if line.strip()]
    if not section:
        return entry.message
    if section[0].lstrip().startswith(EXCEPTION_GROUP_TRACEBACK_HEADER):
        header = next((m.group(1) for line in section if (m := EXCEPTION_GROUP_LINE_RE.match(line))), None)
        if header is not None:
            return f"{entry.message}\n{header}"
    summary = next((line for line in section if line != TRACEBACK_HEADER and not line[0].isspace()), section[-1])
    return f"{entry.message}\n{summary.strip()}"


def fmt_handler_short(value: Any) -> str:
    """Extract just the method name from a fully qualified handler path."""
    if value is None:
        return ""
    return str(value).rsplit(".", 1)[-1]


@numeric_formatter
def fmt_uptime(secs: float) -> str:
    """Convert seconds to a human-readable uptime string (e.g. ``'2h 30m 5s'``)."""
    if secs < 0:
        return EMPTY_VALUE
    if secs < SECONDS_PER_MINUTE:
        return f"{secs:.0f}s"
    if secs < SECONDS_PER_HOUR:
        m, s = divmod(int(secs), SECONDS_PER_MINUTE)
        return f"{m}m {s}s"
    h, remainder = divmod(int(secs), SECONDS_PER_HOUR)
    m, s = divmod(remainder, SECONDS_PER_MINUTE)
    return f"{h}h {m}m {s}s"


def fmt_services(services: list[dict[str, Any]]) -> str:
    """Comma-separated names of the running services, or the empty-value placeholder when none are running."""
    running = [s["name"] for s in services if s.get("status") == ResourceStatus.RUNNING.value]
    return ", ".join(running) if running else EMPTY_VALUE


def fmt_instance_count(value: Any) -> str:
    """Label a tracked-instance count so it can't be read as the configured-app total."""
    noun = "instance" if value == 1 else "instances"
    return f"{value} tracked {noun}"
