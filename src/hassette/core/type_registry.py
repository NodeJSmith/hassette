import typing
from collections import deque
from collections.abc import Callable
from typing import Any

from hassette.resources.base import Resource
from hassette.types.value_converters import BaseValueConverter

if typing.TYPE_CHECKING:
    from hassette import Hassette


class TypeRegistry(Resource):
    """Registry for state types and their conversions.

    The type registry manages the mapping between raw state values (e.g. "on", "off", 23.5, 1764976201), their
    corresponding state classes, and conversion between these and python representations.
    """

    conversion_map: dict[tuple[type[BaseValueConverter], type[Any]], Callable[[BaseValueConverter], Any]]

    async def after_initialize(self) -> None:
        self.build_registry()
        self.mark_ready()

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

    def build_registry(self) -> None:
        from hassette.types.value_converters import BaseValueConverter

        queue: deque[type[BaseValueConverter]] = deque(BaseValueConverter.__subclasses__())
        seen: set[type[BaseValueConverter]] = set()

        while queue:
            state_cls = queue.popleft()
            if state_cls in seen:
                continue
            seen.add(state_cls)

            for sub in state_cls.__subclasses__():
                queue.append(sub)

            state_cls.register(self)
            self.logger.debug("Registered StateValue %s", state_cls.__name__)

    def convert(self, value: BaseValueConverter, to_type: type[Any]) -> Any:
        """Convert a StateValue to a target Python type.

        Args:
            value: The StateValue instance to convert.
            to_type: The target Python type.

        Returns:
            The converted value.
        """
        key = (type(value), to_type)

        if to_type is type(value):
            return value

        if value is None:
            return value

        try:
            fn = self.conversion_map[key]
        except KeyError as e:
            raise TypeError(f"No conversion registered from {type(value).__name__} to {to_type!r}") from e

        # convert to the state value type so we can pass to the conversion function
        if not isinstance(value, BaseValueConverter):
            value = BaseValueConverter.from_raw(value)

        try:
            return fn(value)
        except Exception as e:
            raise RuntimeError(f"Error converting {value!r} ({type(value).__name__}) to {to_type.__name__}") from e

    def register[T: BaseValueConverter](
        self, value_converter: type[T], to_type: type[Any], conversion_method: Callable[[T], Any]
    ) -> None:
        """Register a conversion from a StateValue subclass to a target Python type.

        Args:
            value_converter: The ValueConverter subclass.
            to_type: The target Python type.
            conversion_method: The method to convert from the ValueConverter subclass to the target type.

        Examples:
            ```python
            registry.register(BoolStateValue, str, BoolStateValue.to_string)
            ```
        """

        self.conversion_map[(value_converter, to_type)] = conversion_method  # pyright: ignore[reportArgumentType]

        value_converter.known_types.add(to_type)

        self.logger.debug("Registered conversion from %s to %s", value_converter.__name__, to_type.__name__)
