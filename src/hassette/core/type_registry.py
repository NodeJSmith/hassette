from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from logging import getLogger
from string import Formatter
from typing import Any, ClassVar, Generic, TypeVar, overload

from whenever import Date, Instant, OffsetDateTime, PlainDateTime, Time, ZonedDateTime

from hassette.exceptions import UnableToConvertValueError
from hassette.utils.date_utils import convert_datetime_str_to_system_tz

R = TypeVar("R")
T = TypeVar("T")

ALLOWED_FORMAT_FIELDS = {"value", "from_type", "to_type"}
"""Allowed fields for formatting error messages in type converters."""

LOGGER = getLogger(__name__)


def get_format_fields(string_value: str) -> list[str]:
    """Get the format fields from a string.

    Args:
        string_value: The string to parse.

    Returns:
        A list of format fields (e.g. ["field1", "field2"]).

    Example:
        >>> get_format_fields("Hello, {name}!")
        ['name']
    """
    return [fn for _, fn, _, _ in Formatter().parse(string_value) if fn is not None]


@dataclass
class TypeConverterEntry(Generic[T, R]):
    """Represents a type conversion function and its associated metadata."""

    func: Callable[[T], R]
    from_type: type[T]
    to_type: type[R]
    error_types: tuple[type[BaseException], ...] = (ValueError,)
    error_message: str | None = None


@overload
def register_type_converter_fn(fn: Callable[[T], R]) -> Callable[[T], R]: ...


@overload
def register_type_converter_fn(
    fn: None = None, *, error_message: str | None = None, error_types: tuple[type[BaseException], ...] = (ValueError,)
) -> Callable[[Callable[[T], R]], Callable[[T], R]]: ...


def register_type_converter_fn(
    fn: Callable[[T], R] | None = None,
    *,
    error_message: str | None = None,
    error_types: tuple[type[BaseException], ...] = (ValueError,),
):
    """Register a type conversion function with the TypeRegistry.

    Can be used as:

        @register_type_converter
        def convert_x(value: T) -> R: ...

    or:

        @register_type_converter(error_message="failed to convert X")
        def convert_x(value: T) -> R: ...
    """
    if error_message is not None:
        fields = get_format_fields(error_message)
        invalid_fields = set(fields) - ALLOWED_FORMAT_FIELDS
        if invalid_fields:
            raise ValueError(f"Invalid format fields in error_message: {invalid_fields}")

    def decorator(func: Callable[[T], R]) -> Callable[[T], R]:
        from_type = func.__annotations__["value"]
        to_type = func.__annotations__["return"]
        TypeRegistry.register(
            TypeConverterEntry(
                func=func, from_type=from_type, to_type=to_type, error_message=error_message, error_types=error_types
            )
        )
        return func

    # Used as bare @register_type_converter
    if fn is not None:
        return decorator(fn)

    # Used as @register_type_converter(...)
    return decorator


def register_simple_type_converter(
    from_type: type[T],
    to_type: type[R],
    fn: Callable[[T], R] | None = None,
    error_message: str | None = None,
    error_types: tuple[type[BaseException], ...] = (ValueError,),
):
    """Register a simple type conversion function from a non-user defined function, such as a constructor.

    Args:
        from_type: The source type to convert from.
        to_type: The target type to convert to.
        fn: The function to use for conversion. If None, the target type constructor is used.
        error_message: Optional custom error message if conversion fails.
        error_types: Tuple of exception types to catch and wrap in UnableToConvertValueError.

    Example:
        register_simple_type_converter(int, float, error_message="Failed to convert int to float")
        register_simple_type_converter(ZonedDateTime, str, fn=ZonedDateTime.format_iso)
    """
    if error_message is not None:
        fields = get_format_fields(error_message)
        invalid_fields = set(fields) - ALLOWED_FORMAT_FIELDS
        if invalid_fields:
            raise ValueError(f"Invalid format fields in error_message: {invalid_fields}")

    fn = fn or (lambda x: to_type(x))  # pyright: ignore[reportCallIssue]

    TypeRegistry.register(
        TypeConverterEntry(
            func=fn,
            from_type=from_type,
            to_type=to_type,
            error_message=error_message,
            error_types=error_types,
        )
    )


class TypeRegistry:
    """Registry for converting between types, used by State models and the Dependency Injection system."""

    conversion_map: ClassVar[dict[tuple[type[Any], type[Any]], TypeConverterEntry[Any, Any]]] = {}

    @classmethod
    def register(cls, type_converter: TypeConverterEntry[Any, Any]) -> None:
        """Register a type converter in the registry."""
        from_type = type_converter.from_type
        to_type = type_converter.to_type
        key = (from_type, to_type)
        if key in cls.conversion_map:
            LOGGER.warning("Overwriting existing conversion from %s to %s", from_type.__name__, to_type.__name__)
        cls.conversion_map[key] = type_converter

    def convert(self, value: Any, to_type: type[Any] | tuple[type[Any], ...]) -> Any:
        """Convert a StateValue to a target Python type.

        Args:
            value: The StateValue instance to convert.
            to_type: The target Python type.

        Returns:
            The converted value.
        """

        # handle tuple
        if isinstance(to_type, tuple):
            for tt in to_type:
                if tt is type(None) and value is not None:
                    LOGGER.debug("Not attempting to convert %r to NoneType", value)
                    continue
                try:
                    return self.convert(value, tt)
                except UnableToConvertValueError:
                    continue
            raise UnableToConvertValueError(f"Unable to convert {value!r} to any of the types {to_type}")

        # handle single type

        from_type = type(value)
        key = (from_type, to_type)

        # handle Any type
        if to_type is type(Any):
            return value

        # handle exact type match
        if to_type is from_type:
            return value

        # handle None value
        if value is None:
            return value

        if to_type is type(None) and value is not None:
            LOGGER.debug("Not attempting to convert %r to NoneType", value)
            raise UnableToConvertValueError(f"Cannot convert {value!r} to NoneType")

        # if we don't have this in our map, attempt to just convert using it as a constructor
        if key not in self.conversion_map and to_type is not type(None):
            try:
                return to_type(value)
            except Exception as e:
                raise UnableToConvertValueError(f"Unable to convert {value!r} to {to_type}") from e

        fn = self.conversion_map[key]

        try:
            return fn.func(value)
        except fn.error_types as e:
            default_err_msg = f"Error converting {value!r} ({type(value).__name__}) to {to_type.__name__}"
            err_msg = fn.error_message or default_err_msg
            if get_format_fields(err_msg):
                err_msg = err_msg.format(value=value, from_type=from_type, to_type=to_type)

            raise UnableToConvertValueError(err_msg) from e
        except Exception as e:
            raise RuntimeError(f"Error converting {value!r} ({type(value).__name__}) to {to_type.__name__}") from e

    def list_conversions(self) -> list[tuple[type, type, TypeConverterEntry]]:
        """List all registered type conversions.

        Returns a sorted list of all registered type conversions with their metadata.
        Useful for debugging and inspection of available converters.

        Returns:
            List of (from_type, to_type, entry) tuples sorted by from_type name then to_type name.

        Example:
            ```python
            from hassette.core.type_registry import TYPE_REGISTRY

            # List all conversions
            conversions = TYPE_REGISTRY.list_conversions()
            for from_type, to_type, entry in conversions:
                print(f"{from_type.__name__} → {to_type.__name__}: {entry.description}")
            ```
        """
        items = []
        for (from_type, to_type), entry in self.conversion_map.items():
            items.append((from_type, to_type, entry))

        # Sort by from_type name, then to_type name
        items.sort(key=lambda x: (x[0].__name__, x[1].__name__))
        return items


TYPE_REGISTRY = TypeRegistry()
"""Global type registry for managing type conversions."""

## Value Converters ##

# stdlib classes
register_simple_type_converter(Decimal, float)
register_simple_type_converter(Decimal, int)
register_simple_type_converter(float, Decimal, error_types=(ValueError, InvalidOperation))
register_simple_type_converter(float, int)
register_simple_type_converter(float, str)
register_simple_type_converter(int, float)
register_simple_type_converter(bool, str)
register_simple_type_converter(int, str)
register_simple_type_converter(str, Decimal, error_types=(ValueError, InvalidOperation))
register_simple_type_converter(str, float)
register_simple_type_converter(str, int)


# non-stdlib classes
register_simple_type_converter(str, Date, fn=Date.parse_iso)
register_simple_type_converter(str, Time, fn=Time.parse_iso)
register_simple_type_converter(str, OffsetDateTime, fn=OffsetDateTime.parse_iso)
register_simple_type_converter(str, PlainDateTime, fn=PlainDateTime.parse_iso)
register_simple_type_converter(Time, time, fn=Time.py_time)
register_simple_type_converter(Time, str, fn=Time.format_iso)
register_simple_type_converter(ZonedDateTime, Instant, fn=ZonedDateTime.to_instant)
register_simple_type_converter(ZonedDateTime, PlainDateTime, fn=ZonedDateTime.to_plain)
register_simple_type_converter(ZonedDateTime, str, fn=ZonedDateTime.format_iso)

# more complex converters


@register_type_converter_fn(error_message="String must be a datetime-like value, got {from_type}")
def from_string_to_zoned_date_time(value: str) -> ZonedDateTime:
    with suppress(ValueError):
        return convert_datetime_str_to_system_tz(value)
    with suppress(ValueError):
        return PlainDateTime.parse_iso(value).assume_system_tz()
    with suppress(ValueError):
        return Date.parse_iso(value).at(Time(0, 0, 0, nanosecond=0)).assume_system_tz()
    raise ValueError


@register_type_converter_fn(error_message="String must be a time-like value, got {from_type}")
def from_string_to_stdlib_time(value: str) -> time:
    return Time.parse_iso(value).py_time()


@register_type_converter_fn(error_message="String must be a date-like value, got {from_type}")
def from_string_to_stdlib_date(value: str) -> date:
    return Date.parse_iso(value).py_date()


@register_type_converter_fn(error_message="String must be a datetime-like value, got {from_type}")
def from_string_to_stdlib_datetime(value: str) -> datetime:
    return from_string_to_zoned_date_time(value).py_datetime()


@register_type_converter_fn(error_message="String must be a boolean-like value, got {from_type}")
def from_string_to_bool(value: str) -> bool:
    lower_val = value.lower()
    match lower_val:
        case "on" | "true" | "yes" | "1":
            return True
        case "off" | "false" | "no" | "0":
            return False
        case _:
            raise ValueError
