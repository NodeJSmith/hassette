import typing
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar, Generic, Self

from whenever import Date, PlainDateTime, Time, ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

if typing.TYPE_CHECKING:
    from hassette.core.type_registry import TypeRegistry

T = typing.TypeVar("T")


class BaseStateValue(Generic[T]):
    """Runtime representation of a state's value."""

    _value: T
    """The internal canonical value."""

    python_type: ClassVar[type] = str
    """The default Python type this StateValue maps to. Incoming data will be converted to this type by default."""

    @property
    def value(self) -> T:
        return self._value

    def to_python(self) -> T:
        """Convert this StateValue to its canonical Python representation."""
        return self._value

    def __init__(self, value: T) -> None:
        self._value = value

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} value={self._value!r}>"

    @classmethod
    def register(cls, registry: "TypeRegistry") -> None:
        """Default: canonical python_type via to_python()."""
        registry.register(cls, type(None), lambda _: None)
        registry.register(cls, cls.python_type, cls.to_python)

    @classmethod
    def from_raw(cls, raw: Any) -> "BaseStateValue":
        return cls(raw)


class DateTimeStateValue(BaseStateValue[ZonedDateTime]):
    """Semantic state value for date/time-ish states.

    Internally canonicalized to ZonedDateTime.
    """

    python_type: ClassVar[type[ZonedDateTime]] = ZonedDateTime

    @classmethod
    def register(cls, registry: "TypeRegistry") -> None:
        # canonical via to_python()
        super().register(registry)

        # extra projections — no lambdas, just method references
        registry.register(cls, ZonedDateTime, DateTimeStateValue.to_python)
        registry.register(cls, PlainDateTime, DateTimeStateValue.plain_datetime)
        registry.register(cls, Date, DateTimeStateValue.date)

        registry.register(cls, date, DateTimeStateValue.stdlib_date)
        registry.register(cls, datetime, DateTimeStateValue.stdlib_datetime)
        registry.register(cls, str, DateTimeStateValue.iso_string)

    def date(self) -> Date:
        """Get the date portion of this ZonedDateTime as a Whenever Date."""
        if self.value is None:
            raise ValueError("Datetime state cannot be None")
        return self._value.to_plain().date()

    def plain_datetime(self) -> PlainDateTime:
        """Get the PlainDateTime portion of this ZonedDateTime as a Whenever PlainDateTime."""
        if self.value is None:
            raise ValueError("Datetime state cannot be None")
        return self._value.to_plain()

    def stdlib_date(self) -> "date":
        """Get the date portion of this ZonedDateTime as a standard library date."""
        if self.value is None:
            raise ValueError("Datetime state cannot be None")
        return self.date().py_date()

    def stdlib_datetime(self) -> "datetime":
        """Get this ZonedDateTime as a standard library datetime."""
        if self.value is None:
            raise ValueError("Datetime state cannot be None")
        return self._value.py_datetime()

    def iso_string(self) -> str:
        """Get this ZonedDateTime as an ISO 8601 string."""
        if self.value is None:
            raise ValueError("Datetime state cannot be None")
        return self.value.format_iso()

    @classmethod
    def from_raw(cls, value: Any) -> Self:
        """Normalize raw HA value into a canonical ZonedDateTime."""

        if value is None:
            return cls(value)

        if isinstance(value, ZonedDateTime):
            return cls(value)

        if isinstance(value, (PlainDateTime)):
            # however you want to “attach” zone for these
            return cls(value.assume_system_tz())

        if isinstance(value, Date):
            return cls(value.at(Time(0, 0, 0, nanosecond=0)).assume_system_tz())

        if isinstance(value, str):
            try:
                return cls(convert_datetime_str_to_system_tz(value))
            except ValueError:
                pass
            try:
                return cls(PlainDateTime.parse_iso(value).assume_system_tz())
            except ValueError:
                pass
            try:
                return cls(Date.parse_iso(value).at(Time(0, 0, 0, nanosecond=0)).assume_system_tz())
            except ValueError:
                pass

        raise ValueError(f"State must be a datetime-like string, got {value!r}")


class TimeStateValue(BaseStateValue[Time]):
    """Semantic state value for time-ish states.

    Internally canonicalized to Time.
    """

    python_type: ClassVar[type[Time]] = Time

    def to_string(self) -> str:
        """Get this Time as an ISO 8601 string."""
        if self.value is None:
            raise ValueError("Time state cannot be None")
        return self.value.format_iso()

    def to_stdlib_time(self) -> time:
        """Get this Time as a standard library time."""
        if self.value is None:
            raise ValueError("Time state cannot be None")

        return self.value.py_time()

    @classmethod
    def register(cls, registry: "TypeRegistry") -> None:
        # canonical via to_python()
        super().register(registry)

        # extra projections — no lambdas, just method references
        registry.register(cls, Time, TimeStateValue.to_python)
        registry.register(cls, str, TimeStateValue.to_string)
        registry.register(cls, time, TimeStateValue.to_stdlib_time)

    @classmethod
    def from_raw(cls, value: Any) -> Self:
        """Normalize raw HA value into a canonical Time."""

        if value is None:
            return cls(value)

        if isinstance(value, Time):
            return cls(value)

        if isinstance(value, str):
            try:
                return cls(Time.parse_iso(value))
            except ValueError:
                pass

        raise ValueError(f"State must be a time-like string, got {value!r}")


class StrStateValue(BaseStateValue[str]):
    """Semantic state value for string states.

    Internally canonicalized to str.
    """

    python_type: ClassVar[type[str]] = str

    @classmethod
    def from_raw(cls, value: Any) -> Self:
        """Normalize raw HA value into a canonical str."""

        if value is None:
            return cls(value)

        if isinstance(value, str):
            return cls(value)

        return cls(str(value))


class BoolStateValue(BaseStateValue[bool]):
    """Semantic state value for boolean states.

    Internally canonicalized to bool.
    """

    python_type: ClassVar[type[bool]] = bool

    def to_string(self) -> str:
        """Get this BoolStateValue as 'true'/'false' string."""
        if self.value is None:
            raise ValueError("Bool state cannot be None")
        return "true" if self.value else "false"

    @classmethod
    def register(cls, registry: "TypeRegistry") -> None:
        super().register(registry)

        registry.register(cls, str, BoolStateValue.to_string)

    @classmethod
    def from_raw(cls, value: Any) -> Self:
        """Normalize raw HA value into a canonical bool."""

        if value is None:
            return cls(value)

        if isinstance(value, bool):
            return cls(value)

        if isinstance(value, str):
            if value.lower() == "on":
                return cls(True)
            if value.lower() == "off":
                return cls(False)

        raise ValueError(f"State must be a boolean or 'on'/'off' string, got {value!r}")


class NumericStateValue(BaseStateValue[Decimal]):
    """Semantic state value for numeric states.

    Internally canonicalized to decimal.
    """

    python_type: ClassVar[type[Decimal]] = Decimal

    def to_int(self) -> int:
        if self.value is None:
            raise ValueError("Numeric state cannot be None")
        return int(self.value)

    def to_float(self) -> float:
        if self.value is None:
            raise ValueError("Numeric state cannot be None")
        return float(self.value)

    @classmethod
    def register(cls, registry: "TypeRegistry") -> None:
        # canonical via to_python()
        super().register(registry)

        # extra projections — no lambdas, just method references
        registry.register(cls, int, NumericStateValue.to_int)
        registry.register(cls, float, NumericStateValue.to_float)
        registry.register(cls, str, lambda self: str(self.value))

    @classmethod
    def from_raw(cls, value: Any) -> Self:
        """Normalize raw HA value into a canonical Decimal."""

        if value is None:
            return cls(value)

        try:
            return cls(Decimal(str(value)))
        except (ValueError, TypeError, InvalidOperation):
            pass

        raise ValueError(f"State must be a numeric value, got {value!r}")
