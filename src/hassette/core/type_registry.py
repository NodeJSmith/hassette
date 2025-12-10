import typing
from collections.abc import Callable
from dataclasses import dataclass
from string import Formatter
from typing import Any, ClassVar, TypeVar, overload

from hassette.exceptions import UnableToConvertValueError
from hassette.resources.base import Resource

if typing.TYPE_CHECKING:
    from hassette import Hassette
R = TypeVar("R")
T = TypeVar("T")

ALLOWED_FORMAT_FIELDS = {"value", "from_type", "to_type"}
"""Allowed fields for formatting error messages in type converters."""


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
class TypeConverterEntry[T, R]:
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
        TypeRegistry._type_converter_fns.append(
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

    TypeRegistry._type_converter_fns.append(
        TypeConverterEntry(
            func=fn,
            from_type=from_type,
            to_type=to_type,
            error_message=error_message,
            error_types=error_types,
        )
    )


class TypeRegistry(Resource):
    """Registry for state types and their conversions.

    The type registry manages the mapping between raw state values (e.g. "on", "off", 23.5, 1764976201), their
    corresponding state classes, and conversion between these and python representations.
    """

    _type_converter_fns: ClassVar[list[TypeConverterEntry[Any, Any]]] = []

    conversion_map: dict[tuple[type[Any], type[Any]], TypeConverterEntry[Any, Any]]

    async def after_initialize(self) -> None:
        if not self._type_converter_fns:
            # ensure we load our default converters
            from hassette.types import value_converters  # noqa # pyright: ignore[reportUnusedImport]

        self.build_registry()
        self.mark_ready()

    def build_registry(self) -> None:
        """Build the type conversion registry."""
        for type_converter in self._type_converter_fns:
            from_type = type_converter.from_type
            to_type = type_converter.to_type
            key = (from_type, to_type)
            if key in self.conversion_map:
                self.logger.warning(
                    "Overwriting existing conversion from %s to %s", from_type.__name__, to_type.__name__
                )
            self.conversion_map[key] = type_converter

    @classmethod
    def create(cls, hassette: "Hassette", parent: "Resource"):
        """Create a new StateRegistry resource instance.

        Args:
            hassette: The Hassette instance.
            parent: The parent resource (typically the Hassette core).

        Returns:
            A new StateRegistry instance.
        """
        inst = cls(hassette=hassette, parent=parent)
        inst.conversion_map = {}
        return inst

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
                try:
                    return self.convert(value, tt)
                except UnableToConvertValueError:
                    continue
            raise UnableToConvertValueError(f"Unable to convert {value!r} to any of the types {to_type}")

        # handle single type

        from_type = type(value)
        key = (from_type, to_type)

        if to_type is from_type:
            return value

        if value is None:
            return value

        try:
            fn = self.conversion_map[key]
        except KeyError as e:
            raise TypeError(f"No conversion registered from {from_type.__name__} to {to_type.__name__}") from e

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
