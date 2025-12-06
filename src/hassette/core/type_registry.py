import typing
from collections import deque
from collections.abc import Callable
from typing import Any

from hassette.resources.base import Resource
from hassette.types.state_value import BaseStateValue

if typing.TYPE_CHECKING:
    from hassette import Hassette


class TypeRegistry(Resource):
    """Registry for state types and their conversions.

    The type registry manages the mapping between raw state values (e.g. "on", "off", 23.5, 1764976201), their
    corresponding state classes, and conversion between these and python representations.
    """

    conversion_map: dict[tuple[type[BaseStateValue], type[Any]], Callable[[BaseStateValue], Any]]

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
        from hassette.types.state_value import BaseStateValue

        queue: deque[type[BaseStateValue]] = deque(BaseStateValue.__subclasses__())
        seen: set[type[BaseStateValue]] = set()

        while queue:
            state_cls = queue.popleft()
            if state_cls in seen:
                continue
            seen.add(state_cls)

            for sub in state_cls.__subclasses__():
                queue.append(sub)

            state_cls.register(self)
            self.logger.debug("Registered StateValue %s", state_cls.__name__)

    def convert(self, value: BaseStateValue, to_type: type[Any]) -> Any:
        key = (to_type, type(value))

        if to_type is type(value):
            return value

        if value is None:
            return value

        try:
            fn = self.conversion_map[key]
        except KeyError as e:
            raise TypeError(f"No conversion registered from {type(value).__name__} to {to_type!r}") from e

        # convert to the state value type so we can pass to the conversion function
        if not isinstance(value, BaseStateValue):
            value = BaseStateValue.from_raw(value)

        try:
            return fn(value)
        except Exception as e:
            raise RuntimeError(f"Error converting {value!r} ({type(value).__name__}) to {to_type.__name__}") from e

    def register[T: BaseStateValue](
        self, state_value_cls: type[T], to_type: type[Any], conversion_method: Callable[[T], Any]
    ) -> None:
        """Register a conversion from a StateValue subclass to a target Python type.

        Args:
            state_value_cls: The StateValue subclass.
            to_type: The target Python type.
            conversion_method: The method to convert from the StateValue subclass to the target type.

        Examples:
            ```python
            registry.register(BoolStateValue, str, BoolStateValue.to_string)
            ```
        """

        self.conversion_map[(state_value_cls, to_type)] = conversion_method  # pyright: ignore[reportArgumentType]

        self.logger.info("Registered conversion from %s to %s", state_value_cls.__name__, to_type.__name__)
