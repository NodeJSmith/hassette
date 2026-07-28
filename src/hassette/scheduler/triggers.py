"""Trigger objects for the Hassette scheduler.

Each trigger encapsulates a scheduling strategy (fixed delay, wall-clock time,
cron expression, etc.) and exposes a uniform interface via TriggerProtocol.
"""

import typing
from logging import getLogger
from typing import Any, Literal

from whenever import PlainDateTime, Time, TimeDelta, ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.utils.hass_utils import valid_entity_id

from .classes import CronTrigger

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette.events import HassStateDict

LOGGER = getLogger(__name__)

NO_OCCURRENCE = ZonedDateTime(9999, 12, 31, 23, 59, 59, tz="UTC")
"""Fire time used by :class:`EntityTime` when the entity carries no usable time.

The scheduler heap has no "registered but unscheduled" state, so a trigger that
currently has nowhere to fire parks the job at a time it will never reach. The job
keeps its database row and its telemetry, and the state-change listener that
``Scheduler`` registers alongside it moves the job back to a real time as soon as
the entity reports one.
"""

UNUSABLE_STATE_VALUES = frozenset({"", "unknown", "unavailable", "none", "null"})
"""Entity state strings that carry no time value."""


def parse_entity_time(value: Any) -> ZonedDateTime | None:
    """Parse a Home Assistant state or attribute value into a ``ZonedDateTime``.

    Covers the shapes Home Assistant uses for times: offset-aware ISO strings
    (``"2026-07-28T07:00:00-05:00"``, what most sensors report), naive ISO
    date-times (``"2026-07-28 07:00:00"``, what ``input_datetime`` puts in its
    state), time-only strings (``"07:00:00"``, an ``input_datetime`` with no date
    component), and unix timestamps (the ``timestamp`` attribute on
    ``input_datetime``). Naive and time-only values are interpreted in the
    configured timezone; time-only values resolve against today's date.

    Args:
        value: The raw state or attribute value.

    Returns:
        The parsed time, or ``None`` when the value carries none — an unavailable
        entity, an empty state, or a string in a format that is not a time.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, ZonedDateTime):
        return value
    if isinstance(value, int | float):
        return date_utils.convert_utc_timestamp_to_tz(value)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if text.lower() in UNUSABLE_STATE_VALUES:
        return None

    try:
        return date_utils.convert_datetime_str_to_tz(text)
    except ValueError:
        pass

    try:
        return date_utils.assume_tz(PlainDateTime.parse_iso(text))
    except ValueError:
        pass

    try:
        time_of_day = Time.parse_iso(text)
    except ValueError:
        LOGGER.warning("Could not parse %r as a time value", value)
        return None

    today = date_utils.now()
    return ZonedDateTime(
        today.year,
        today.month,
        today.day,
        time_of_day.hour,
        time_of_day.minute,
        time_of_day.second,
        tz=today.tz,
    )


def parse_hh_mm(at: str, label: str) -> tuple[int, int]:
    parts = at.split(":")
    if len(parts) != 2:
        raise ValueError(f"{label} 'at' must be 'HH:MM', got {at!r}")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"{label} 'at' must be 'HH:MM', got {at!r}") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"{label} 'at' time out of range: {at!r}")
    return hour, minute


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
        if self._delay.total("seconds") <= 0:
            raise ValueError("After trigger delay must be positive")

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return current_time plus the delay."""
        return current_time.add(seconds=self._delay.total("seconds")).round("second")

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> None:
        """One-shot trigger; always returns None."""
        return

    def trigger_label(self) -> str:
        return "after"

    def trigger_detail(self) -> str | None:
        return f"{int(self._delay.total('seconds'))}s"

    def trigger_db_type(self) -> Literal["after"]:
        return "after"

    def trigger_id(self) -> str:
        return f"after:{int(self._delay.total('seconds'))}"


class Once:
    """One-shot trigger that fires at a specific wall-clock time.

    Args:
        at: Target time. Accepts a ``"HH:MM"`` string (interpreted as today's
            wall-clock time in the configured timezone — see
            ``HassetteConfig.timezone``; falls back to the process timezone
            when unset) or a ``ZonedDateTime`` (absolute instant; timezone
            is explicit).
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
            hour, minute = parse_hh_mm(at, "Once")
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
                    "Once received ZonedDateTime in the past; firing immediately — "
                    "if_past='tomorrow' cannot defer an absolute instant. (at=%r)",
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
        total_seconds = total.total("seconds")
        if total_seconds <= 0:
            raise ValueError("Every trigger interval must be positive")
        if total_seconds != int(total_seconds):
            raise ValueError("Every trigger interval must be a whole number of seconds")
        self._interval = total
        self._start = start

    @property
    def interval_seconds(self) -> float:
        return self._interval.total("seconds")

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the first run time, aligned to the interval grid."""
        start = self._start if self._start is not None else current_time
        if start > current_time:
            return start.round("second")
        return self.advance_past(start, current_time)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the next interval tick after previous_run that is later than current_time."""
        return self.advance_past(previous_run, current_time)

    def advance_past(self, anchor: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        """Advance anchor by whole intervals until the result is strictly after current_time."""
        interval_secs = self._interval.total("seconds")
        elapsed = (current_time - anchor).total("seconds")
        if elapsed > 0:
            missed = int(elapsed / interval_secs)
            anchor = anchor.add(seconds=missed * interval_secs)
        result = anchor.add(seconds=interval_secs)
        # Guard: if floating-point truncation landed result at or before current_time,
        # advance one more interval. Boundary-exact slots are treated as "past."
        if result <= current_time:
            result = result.add(seconds=interval_secs)
        return result.round("second")

    def trigger_label(self) -> str:
        return "every"

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

    Args:
        at: Target time in ``"HH:MM"`` format (e.g. ``"07:00"``),
            interpreted in the configured timezone (see
            ``HassetteConfig.timezone``; falls back to the process timezone
            when unset).

    Example:
        Daily(at="07:00")   # fires every day at 07:00 wall-clock time
    """

    def __init__(self, at: str) -> None:
        hour, minute = parse_hh_mm(at, "Daily")
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
        return "daily"

    def trigger_detail(self) -> str | None:
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
        except ValueError as exc:
            raise ValueError(f"Invalid cron expression: {expression!r}") from exc

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


class EntityTime:
    """Trigger that fires at a time read from a Home Assistant entity.

    The entity holds the schedule: a phone alarm sensor, an ``input_datetime``
    helper, or any entity whose state or attribute is a time. Whenever that value
    changes, ``Scheduler`` moves the job to the new time — no manual cancel and
    reschedule.

    An entity with no usable value (unavailable, ``unknown``, no alarm set) parks
    the job at :data:`NO_OCCURRENCE` instead of removing it. The job stays
    registered and starts firing again as soon as the entity reports a time.

    Args:
        entity_id: The entity holding the time, e.g. ``"sensor.phone_next_alarm"``.
        attribute: Read the time from this attribute instead of the entity's state.
        offset: Shift the fire time. Negative values fire before the entity's time
            (``TimeDelta(minutes=-30)`` fires 30 minutes early).
        daily: Keep only the time of day and fire at it every day. Without this, the
            trigger fires at the entity's absolute date and time and then waits for
            the entity to name a new one.

    Example:
        EntityTime("sensor.phone_next_alarm")
        EntityTime("input_datetime.morning_routine", offset=TimeDelta(minutes=-30), daily=True)
        EntityTime("sun.sun", attribute="next_dawn")
    """

    def __init__(
        self,
        entity_id: str,
        *,
        attribute: str | None = None,
        offset: TimeDelta | None = None,
        daily: bool = False,
    ) -> None:
        if not valid_entity_id(entity_id):
            raise ValueError(f"EntityTime entity_id must be '<domain>.<object_id>', got {entity_id!r}")
        self.entity_id = entity_id
        self.attribute = attribute
        self.offset = offset if offset is not None else TimeDelta()
        self.daily = daily
        self._state_reader: Callable[[str], HassStateDict | None] | None = None

    def __repr__(self) -> str:
        return f"EntityTime({self.trigger_detail()})"

    def bind_state_reader(self, reader: "Callable[[str], HassStateDict | None]") -> None:
        """Attach the state source used to read the entity.

        Called by ``Scheduler.schedule()`` before the first run time is computed.
        An unbound trigger resolves to :data:`NO_OCCURRENCE`, so a trigger used
        outside the scheduler never fires rather than raising.
        """
        self._state_reader = reader

    def resolve(self, current_time: ZonedDateTime) -> ZonedDateTime | None:
        """Return the next fire time read from the bound state source, or ``None``."""
        if self._state_reader is None:
            LOGGER.debug("EntityTime(%s): no state reader bound", self.entity_id)
            return None
        return self.resolve_from_state(self._state_reader(self.entity_id), current_time)

    def resolve_from_state(self, state: "HassStateDict | None", current_time: ZonedDateTime) -> ZonedDateTime | None:
        """Return the next fire time for an explicit state, or ``None`` when there is none.

        Returns ``None`` for a state that carries no parsable time, and for an absolute
        time at or before ``current_time`` — in both cases the trigger has nowhere to fire
        until the entity changes. Treating the boundary as past keeps a restart from
        re-firing an alarm that already went off; the cost is that an entity reporting the
        current second exactly parks instead of firing, and waits for its next change.

        Taking the state as an argument lets the rescheduling path use the state carried on
        the state-change event. The scheduler's listener and the StateProxy's cache update
        are dispatched concurrently, so reading the cache there could see the old value.
        """
        if state is None:
            return None
        raw = state.get("attributes", {}).get(self.attribute) if self.attribute is not None else state.get("state")

        parsed = parse_entity_time(raw)
        if parsed is None:
            return None

        target = parsed.add(seconds=self.offset.total("seconds"))
        if self.daily:
            # Delegate the daily rollover to cron so it stays wall-clock aligned across
            # DST transitions, the same way Daily does.
            time_of_day = target.time()
            expression = f"{time_of_day.minute} {time_of_day.hour} * * * {time_of_day.second}"
            return CronTrigger(expression).first_run_time(current_time)

        if target <= current_time:
            return None
        return target.round("second")

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the entity's next time, or ``NO_OCCURRENCE`` when it has none."""
        return self.resolve(current_time) or NO_OCCURRENCE

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        """Re-read the entity and return its next time, or ``NO_OCCURRENCE`` when it has none.

        Never returns ``None``: the job outlives any individual fire so the entity can
        schedule it again.
        """
        return self.resolve(current_time) or NO_OCCURRENCE

    def trigger_label(self) -> str:
        return "entity_time"

    def trigger_detail(self) -> str | None:
        detail = self.entity_id
        if self.attribute is not None:
            detail += f".{self.attribute}"
        offset_seconds = int(self.offset.total("seconds"))
        if offset_seconds:
            detail += f" {offset_seconds:+d}s"
        if self.daily:
            detail += " daily"
        return detail

    def trigger_db_type(self) -> Literal["custom"]:
        return "custom"

    def trigger_id(self) -> str:
        offset_seconds = int(self.offset.total("seconds"))
        return f"entity_time:{self.entity_id}:{self.attribute or ''}:{offset_seconds}:{int(self.daily)}"
