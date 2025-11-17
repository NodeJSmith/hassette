import typing
from typing import Any

from hassette.bus import accessors as A

if typing.TYPE_CHECKING:
    from hassette.events import Event, StateChangeEvent


class Depends:
    """Base class for dependencies."""

    def __call__(self, event: "Event") -> Any:
        raise NotImplementedError()


class _StateNewExtractor(Depends):
    """Internal extractor for new state object from a StateChangeEvent."""

    def __call__(self, event: "StateChangeEvent") -> Any:
        return A.get_state_object_new(event)


class _StateOldExtractor(Depends):
    """Internal extractor for old state object from a StateChangeEvent."""

    def __call__(self, event: "StateChangeEvent") -> Any:
        return A.get_state_object_old(event)


class _StateOldAndNewExtractor(Depends):
    """Internal extractor for both old and new state objects from a StateChangeEvent."""

    def __call__(self, event: "StateChangeEvent") -> tuple[Any, Any]:
        return (
            A.get_state_object_old(event),
            A.get_state_object_new(event),
        )


# Pre-instantiated singletons for use in Annotated types
StateNew = _StateNewExtractor()
"""Dependency for extracting the new state object from a StateChangeEvent.

Usage:
    ```python
    from typing import Annotated
    from hassette import dependencies as D
    from hassette import states

    async def handler(new_state: Annotated[states.LightState, D.StateNew]):
        # new_state is typed as states.LightState and extracted from event
        print(new_state.state)
    ```
"""

StateOld = _StateOldExtractor()
"""Dependency for extracting the old state object from a StateChangeEvent.

Usage:
    ```python
    from typing import Annotated
    from hassette import dependencies as D
    from hassette import states

    async def handler(old_state: Annotated[states.LightState, D.StateOld]):
        print(old_state.state)
    ```
"""

StateOldAndNew = _StateOldAndNewExtractor()
"""Dependency for extracting both old and new state objects from a StateChangeEvent.

Usage:
    ```python
    from typing import Annotated
    from hassette import dependencies as D
    from hassette import states

    async def handler(states_tuple: Annotated[tuple[states.LightState, states.LightState], D.StateOldAndNew]):
        old_state, new_state = states_tuple
        print(f"Changed from {old_state.state} to {new_state.state}")
    ```
"""


class AttrNew(Depends):
    """Annotated type for extracting a specific attribute from the new state in a StateChangeEvent."""

    def __init__(self, attr_name: str):
        self.attr_name = attr_name

    def __call__(self, event: "StateChangeEvent") -> Any:
        return A.get_attr_new(self.attr_name)(event)


class AttrOld(Depends):
    """Annotated type for extracting a specific attribute from the old state in a StateChangeEvent."""

    def __init__(self, attr_name: str):
        self.attr_name = attr_name

    def __call__(self, event: "StateChangeEvent") -> Any:
        return A.get_attr_old(self.attr_name)(event)


class AttrOldAndNew(Depends):
    """Annotated type for extracting a specific attribute from both old and new states in a StateChangeEvent."""

    def __init__(self, attr_name: str):
        self.attr_name = attr_name

    def __call__(self, event: "StateChangeEvent") -> tuple[Any, Any]:
        return (
            A.get_attr_old(self.attr_name)(event),
            A.get_attr_new(self.attr_name)(event),
        )


StateValueNew = A.get_state_value_new
"""Annotated type for extracting the new state value from a StateChangeEvent."""

StateValueOld = A.get_state_value_old
"""Annotated type for extracting the old state value from a StateChangeEvent."""

StateValueOldAndNew = A.get_state_value_old_new
"""Annotated type for extracting the old and new state values from a StateChangeEvent."""

EntityId = A.get_entity_id
"""Annotated type for extracting the entity_id from a HassEvent."""

Domain = A.get_domain
"""Annotated type for extracting the domain from a HassEvent."""

Service = A.get_service
"""Annotated type for extracting the service from a CallServiceEvent."""

ServiceData = A.get_service_data
"""Annotated type for extracting the service_data from a CallServiceEvent."""

EventContext = A.get_context
"""Annotated type for extracting the context dict from a HassEvent."""
