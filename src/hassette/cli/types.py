"""Shared CLI flag types and converters for hassette commands."""

import re
from typing import Annotated, Literal

from cyclopts import Parameter
from whenever import Instant, OffsetDateTime, PlainDateTime

from hassette.cli.output import now_epoch
from hassette.const.misc import SECONDS_PER_DAY, SECONDS_PER_HOUR, SECONDS_PER_MINUTE

SINCE_HELP = (
    "Filter by time. Accepts relative (1h, 7d, 30m, 2w, 30s) or absolute "
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

_INVALID_FORMATS_HINT = (
    "Accepted formats: relative (1h, 7d, 30m, 2w, 30s) or "
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

    if _ISO_UTC_PATTERN.match(value):
        try:
            return Instant.parse_iso(value).timestamp()
        except ValueError:
            pass

    if _ISO_WITH_OFFSET_PATTERN.match(value):
        try:
            return OffsetDateTime.parse_iso(value).timestamp()
        except ValueError:
            pass

    if _ISO_NAIVE_PATTERN.match(value):
        try:
            return PlainDateTime.parse_iso(value).assume_system_tz().timestamp()
        except ValueError:
            pass

    if _DATE_ONLY_PATTERN.match(value):
        try:
            return PlainDateTime.parse_iso(value + "T00:00:00").assume_system_tz().timestamp()
        except ValueError:
            pass

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

JsonArg = Annotated[bool, Parameter(name=["--json"], help="Output results as JSON.", negative=[])]

AppKeyArg = Annotated[str | None, Parameter(name=["--app"], help="Filter by app key.")]

InstanceArg = Annotated[
    str | None,
    Parameter(
        name=["--instance"],
        help="Filter by app instance (integer index or instance name). Requires --app.",
    ),
]
