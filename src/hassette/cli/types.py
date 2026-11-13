"""Shared CLI flag types and converters for hassette commands."""

import re
from collections.abc import Callable
from typing import Annotated, Literal

from cyclopts import Parameter
from hassette_wire import QueryAuthor

from hassette.cli.formatters import now_epoch, parse_iso_epoch
from hassette.const.misc import SECONDS_PER_DAY, SECONDS_PER_HOUR, SECONDS_PER_MINUTE

_RELATIVE_EXAMPLES = "1h, 7d, 30m, 2w, 30s"

SINCE_HELP = (
    f"Filter by time. Accepts relative ({_RELATIVE_EXAMPLES}) or absolute "
    "(2026-05-22, 2026-05-22T14:00:00) timestamps. Naive timestamps use local time."
)

_RELATIVE_PATTERN = re.compile(r"^(\d+)([smhdw])$")

_RELATIVE_MULTIPLIERS: dict[str, int] = {
    "s": 1,
    "m": SECONDS_PER_MINUTE,
    "h": SECONDS_PER_HOUR,
    "d": SECONDS_PER_DAY,
    "w": 7 * SECONDS_PER_DAY,
}

_ISO_WITH_OFFSET_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
_ISO_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ISO_NAIVE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
_DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The regexes gate which shapes --since accepts; a value can match one and still fail to parse (2026-13-45).
_ABSOLUTE_PARSERS: tuple[tuple[re.Pattern[str], Callable[[str], float]], ...] = (
    (_ISO_UTC_PATTERN, parse_iso_epoch),
    (_ISO_WITH_OFFSET_PATTERN, parse_iso_epoch),
    (_ISO_NAIVE_PATTERN, parse_iso_epoch),
    (_DATE_ONLY_PATTERN, lambda v: parse_iso_epoch(v + "T00:00:00")),
)

_INVALID_FORMATS_HINT = (
    f"Accepted formats: relative ({_RELATIVE_EXAMPLES}) or "
    "absolute (2026-05-22, 2026-05-22T14:00:00, 2026-05-22T18:00:00Z, "
    "2026-05-22T14:00:00-04:00). Compound durations (1h30m) and "
    "month/year units are not supported."
)


def convert_since(value: str) -> float:
    """Convert a --since value to a Unix epoch float.

    Raises ValueError with a descriptive message on invalid input.
    """
    if not value:
        raise ValueError(f"Empty --since value. {_INVALID_FORMATS_HINT}")

    match = _RELATIVE_PATTERN.match(value)
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        return now_epoch() - n * _RELATIVE_MULTIPLIERS[unit]

    for pattern, parse in _ABSOLUTE_PARSERS:
        if not pattern.match(value):
            continue
        try:
            return parse(value)
        except ValueError:
            continue

    raise ValueError(f"Invalid --since value: {value!r}. {_INVALID_FORMATS_HINT}")


SinceArg = Annotated[
    float | None,
    Parameter(
        name=["--since"],
        # cyclopts passes (type, tuple[Token, ...]) — one Token per flag occurrence
        converter=lambda _, tokens: convert_since(tokens[0].value),
        help=SINCE_HELP,
    ),
]

LimitArg = Annotated[int | None, Parameter(name=["--limit"], help="Maximum number of results to return.")]

SourceTierArg = Annotated[
    Literal["app", "framework", "all"] | None,
    Parameter(name=["--source-tier"], help="Filter by telemetry source tier: 'app', 'framework', or 'all'."),
]

AuthorArg = Annotated[
    QueryAuthor | None,
    Parameter(
        name=["--author"],
        help="Filter log lines by who wrote them: 'app', 'framework', or 'all'. "
        "Omit for app lines plus framework lines at ERROR and above.",
    ),
]

LevelArg = Annotated[
    str | None,
    Parameter(
        name=["--level"],
        help="Show only log lines at this level (DEBUG, INFO, WARNING, ERROR, CRITICAL; case-insensitive). "
        "Exact match, not a minimum. Hassette's own lines below ERROR stay hidden unless --author is 'all'.",
    ),
]

AppKeyArg = Annotated[str | None, Parameter(name=["--app"], help="Filter by app key.")]

InstanceArg = Annotated[
    str | None,
    Parameter(
        name=["--instance"],
        help="Filter by app instance name. Requires --app.",
    ),
]

# Hidden: log entries have no server-side instance filter; this flag only turns `--instance` into a usage error.
LogInstanceArg = Annotated[str | None, Parameter(name=["--instance"], show=False)]

# Action commands take a positional key and no `--app`, so `--instance` doesn't require `--app`.
InstanceActionArg = Annotated[
    str | None,
    Parameter(
        name=["--instance"],
        help="Targets a specific app instance by name.",
    ),
]

YesArg = Annotated[bool, Parameter(name=["--yes"], help="Skip the confirmation prompt.", negative=[])]
