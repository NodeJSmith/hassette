"""Trigger objects for the Hassette scheduler.

Each trigger encapsulates a scheduling strategy (fixed delay, wall-clock time,
cron expression, etc.) and exposes a uniform interface via TriggerProtocol.
"""

import logging
from typing import Literal

from whenever import TimeDelta, ZonedDateTime

import hassette.utils.date_utils as date_utils

from .classes import CronTrigger

LOGGER = logging.getLogger(__name__)


class After:
    """One-shot trigger that fires once after a fixed delay.

    Accepts seconds, minutes, or a TimeDelta directly.

    Args:
        seconds: Delay in seconds.
        minutes: Delay in minutes.
        timedelta: Delay as a TimeDelta object. Mutually exclusive with seconds/minutes.

    Example:
        After(seconds=30)       # fires 30 seconds from now
        After(minutes=5)        # fires 5 minutes from now
    """

    def __init__(
        self,
        seconds: float = 0,
        minutes: float = 0,
        timedelta: TimeDelta | None = None,
    ) -> None:
        if timedelta is not None:
            self._delay = timedelta
        else:
            self._delay = TimeDelta(seconds=seconds, minutes=minutes)
        if self._delay.in_seconds() <= 0:
            raise ValueError("After trigger delay must be positive")

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return current_time plus the delay."""
        return current_time.add(seconds=self._delay.in_seconds()).round(unit="second")

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> None:
        """One-shot trigger; always returns None."""
        return

    def trigger_label(self) -> str:
        return "after"

    def trigger_detail(self) -> str | None:
        return f"{int(self._delay.in_seconds())}s"

    def trigger_db_type(self) -> Literal["after"]:
        return "after"

    def trigger_id(self) -> str:
        return f"after:{int(self._delay.in_seconds())}"


class Once:
    """One-shot trigger that fires at a specific wall-clock time.

    .. warning::
        ``"HH:MM"`` string inputs are resolved against the **system process
        timezone** (``date_utils.now().tz``). Docker containers commonly run
        with ``TZ=UTC`` while the user's Home Assistant is configured for a
        local zone — a ``Once(at="07:00")`` written for local time will fire
        at 07:00 UTC in that environment with no warning. To avoid this: set
        ``TZ`` on the container to match the HA zone, or pass a
        ``ZonedDateTime`` directly with the intended timezone.

    Args:
        at: Target time. Accepts a ``"HH:MM"`` string (interpreted as today's
            wall-clock time in the **system process timezone** — see warning
            above) or a ``ZonedDateTime`` (absolute instant; timezone is
            explicit).
        if_past: Behavior when the computed fire time is in the past.
            - ``"tomorrow"`` (default): For ``"HH:MM"`` string inputs, defers to the next day.
              No effect for ``ZonedDateTime`` inputs (the absolute instant is used as-is;
              if it is in the past, the job fires immediately).
            - ``"error"``: Raises ``ValueError`` if the computed fire time is in the past.
              Applies to both ``"HH:MM"`` and ``ZonedDateTime`` inputs.

    Example:
        Once(at="07:00")                      # fires today at 07:00 (or tomorrow if past)
        Once(at="07:00", if_past="error")     # raises if 07:00 has already passed
    """

    def __init__(
        self,
        at: str | ZonedDateTime,
        if_past: Literal["tomorrow", "error"] = "tomorrow",
    ) -> None:
        self._if_past = if_past
        self._at_str: str | None = None

        if isinstance(at, str):
            self._at_str = at
            parts = at.split(":")
            if len(parts) != 2:
                raise ValueError(f"Once 'at' must be 'HH:MM', got {at!r}")
            try:
                hour = int(parts[0])
                minute = int(parts[1])
            except ValueError:
                raise ValueError(f"Once 'at' must be 'HH:MM', got {at!r}") from None
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError(f"Once 'at' time out of range: {at!r}")
            now = date_utils.now()
            target = ZonedDateTime(now.year, now.month, now.day, hour, minute, tz=now.tz)
            if target <= now:
                if if_past == "error":
                    raise ValueError(f"Once(at={at!r}) constructed after the target time and if_past='error'")
                # Defer to tomorrow
                LOGGER.warning(
                    "Once(at=%r) constructed after the target time — deferring to tomorrow.",
                    at,
                )
                target = target.add(days=1)
            self._fire_at = target
        else:
            now = date_utils.now()
            if at <= now:
                if if_past == "error":
                    raise ValueError(f"Once(at=<ZonedDateTime {at.format_iso()!r}>) is in the past and if_past='error'")
                LOGGER.warning(
                    "Once received ZonedDateTime in the past; `if_past` does not apply to absolute instants; "
                    "firing immediately. (at=%r)",
                    at.format_iso(),
                )
            self._fire_at = at

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the scheduled fire time."""
        return self._fire_at

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> None:
        """One-shot trigger; always returns None."""
        return

    def trigger_label(self) -> str:
        return "once"

    def trigger_detail(self) -> str | None:
        if self._at_str is not None:
            return self._at_str
        return self._fire_at.format_iso()

    def trigger_db_type(self) -> Literal["once"]:
        return "once"

    def trigger_id(self) -> str:
        # Always include the full ISO timestamp so two Once jobs constructed on different days
        # (both at "07:00") do not share a trigger_id and do not shadow each other in the heap.
        return f"once:{self._fire_at.format_iso()}"


class Every:
    """Fixed-interval trigger with drift-resistant scheduling.

    Accepts seconds, hours, minutes, or a combination. An optional ``start``
    parameter anchors the interval grid; if omitted, the first call to
    ``first_run_time`` is used as the anchor.

    Args:
        seconds: Interval component in seconds.
        minutes: Interval component in minutes.
        hours: Interval component in hours.
        start: Optional ``ZonedDateTime`` anchor for the interval grid. If the
            anchor is in the past, missed intervals are skipped to produce a
            near-future run time.

    Example:
        Every(hours=1)                          # every hour, anchored to first run
        Every(seconds=30, start=my_start_time)  # every 30 s, grid anchored to my_start_time
    """

    def __init__(
        self,
        seconds: float = 0,
        minutes: float = 0,
        hours: float = 0,
        start: ZonedDateTime | None = None,
    ) -> None:
        total = TimeDelta(seconds=seconds, minutes=minutes, hours=hours)
        if total.in_seconds() <= 0:
            raise ValueError("Every trigger interval must be positive")
        if total.in_seconds() != int(total.in_seconds()):
            raise ValueError("Every trigger interval must be a whole number of seconds")
        self._interval = total
        self._start = start

    @property
    def interval_seconds(self) -> float:
        return self._interval.in_seconds()

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the first run time, aligned to the interval grid."""
        start = self._start if self._start is not None else current_time
        if start > current_time:
            return start.round(unit="second")
        return self._advance_past(start, current_time)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the next interval tick after previous_run that is later than current_time."""
        return self._advance_past(previous_run, current_time)

    def _advance_past(self, anchor: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        """Advance anchor by whole intervals until the result is strictly after current_time."""
        interval_secs = self._interval.in_seconds()
        elapsed = (current_time - anchor).in_seconds()
        if elapsed > 0:
            missed = int(elapsed / interval_secs)
            anchor = anchor.add(seconds=missed * interval_secs)
        result = anchor.add(seconds=interval_secs)
        # Guard: if floating-point truncation landed result at or before current_time,
        # advance one more interval. Boundary-exact slots are treated as "past."
        if result <= current_time:
            result = result.add(seconds=interval_secs)
        return result.round(unit="second")

    def trigger_label(self) -> str:
        return "interval"

    def trigger_detail(self) -> str | None:
        return f"{int(self.interval_seconds)}s"

    def trigger_db_type(self) -> Literal["interval"]:
        return "interval"

    def trigger_id(self) -> str:
        return f"every:{int(self.interval_seconds)}"


class Daily:
    """Trigger that fires once per day at a fixed wall-clock time.

    Internally delegates to a 5-field cron expression to ensure DST-correct,
    wall-clock-aligned scheduling.

    .. warning::
        ``"HH:MM"`` is resolved against the **system process timezone** (from
        ``date_utils.now().tz``). Docker containers commonly run ``TZ=UTC``
        while the user's Home Assistant is configured for a local zone — a
        ``Daily(at="07:00")`` written for local time will fire at 07:00 UTC
        in that environment with no warning. To avoid this: set ``TZ`` on the
        container to match the HA zone. A future ``tz=`` parameter is tracked
        in the design doc follow-up work.

    Args:
        at: Target time in ``"HH:MM"`` format (e.g. ``"07:00"``),
            interpreted in the **system process timezone** — see warning above.

    Example:
        Daily(at="07:00")   # fires every day at 07:00 wall-clock time
    """

    def __init__(self, at: str) -> None:
        parts = at.split(":")
        if len(parts) != 2:
            raise ValueError(f"Daily 'at' must be 'HH:MM', got {at!r}")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            raise ValueError(f"Daily 'at' must be 'HH:MM', got {at!r}") from None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Daily 'at' time out of range: {at!r}")
        # 5-field standard cron: minute hour dom month dow
        self._expr = f"{minute} {hour} * * *"
        self._at_str = at
        self._cron = CronTrigger(self._expr)

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the next cron-grid-aligned daily run time at or after current_time."""
        return self._cron.first_run_time(current_time)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the next daily run time after previous_run that is later than current_time."""
        return self._cron.next_run_time(previous_run, current_time)

    def trigger_label(self) -> str:
        # Returns "cron" because Daily is implemented via CronTrigger internally.
        # Daily jobs surface identically to Cron jobs in `trigger_label`/`trigger_db_type`;
        # distinction only visible to the user via constructor choice. See design.md TENSION resolution.
        return "cron"

    def trigger_detail(self) -> str | None:
        # Return the user-written "HH:MM" so the UI can display "Daily at 07:00"
        # directly without parsing the underlying cron expression. Cron-backed
        # siblings return their full expression, letting the UI differentiate
        # Daily from Cron on the display surface even though trigger_label/db_type
        # are both "cron".
        return self._at_str

    def trigger_db_type(self) -> Literal["cron"]:
        return "cron"

    def trigger_id(self) -> str:
        return f"cron:{self._expr}"


class Cron:
    """Trigger based on an arbitrary cron expression.

    Accepts both 5-field (standard Unix cron: ``minute hour dom month dow``)
    and 6-field expressions (seconds appended as a 6th field per croniter
    convention: ``minute hour dom month dow second``).

    Args:
        expression: A valid 5- or 6-field cron expression.

    Raises:
        ValueError: If the expression is syntactically invalid.

    Example:
        Cron("0 9 * * 1-5")    # weekdays at 09:00
        Cron("0 9 * * 1-5 0")  # weekdays at 09:00:00 (6-field)
    """

    def __init__(self, expression: str) -> None:
        self._expression = expression
        try:
            self._cron = CronTrigger(expression)
        except ValueError as e:
            raise ValueError(f"Invalid cron expression: {expression!r}") from e

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the first cron-grid-aligned run time at or after current_time."""
        return self._cron.first_run_time(current_time)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the next cron-grid-aligned run time after previous_run that is later than current_time."""
        return self._cron.next_run_time(previous_run, current_time)

    def trigger_label(self) -> str:
        return "cron"

    def trigger_detail(self) -> str | None:
        return self._expression

    def trigger_db_type(self) -> Literal["cron"]:
        return "cron"

    def trigger_id(self) -> str:
        return f"cron:{self._expression}"
