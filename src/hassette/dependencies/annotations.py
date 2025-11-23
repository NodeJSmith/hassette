# ruff: noqa: UP040

# disabling UP040 - the TypeAlias definitions here are useful because we can use StateT and StateValueT
# to provide better type hints in handlers that use these dependencies.

# the new `type` doesn't work quite as well for this purpose

from collections.abc import Callable
from typing import Annotated, Any, TypeAlias

from hassette.bus import accessors as A
from hassette.const.misc import MISSING_VALUE, FalseySentinel
from hassette.events import HassContext
from hassette.exceptions import InvalidDependencyReturnTypeError
from hassette.models.states import StateT, StateValueT


def ensure_present(accessor: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """Wrap an accessor to raise if it returns None or MISSING_VALUE.

    Args:
        accessor: The accessor function to wrap

    Returns:
        Wrapped accessor that validates the return value
    """

    def wrapper(event):
        result = accessor(event)

        # Check if the result is None or MISSING_VALUE
        if result is None or result is MISSING_VALUE:
            raise InvalidDependencyReturnTypeError(type(result))

        # Check if the result is a tuple containing None or MISSING_VALUE
        if isinstance(result, tuple) and any(r is None or r is MISSING_VALUE for r in result):
            raise InvalidDependencyReturnTypeError(type(result))

        return result

    return wrapper


StateNew: TypeAlias = Annotated[StateT, ensure_present(A.get_state_object_new)]
"""Extract the new state object from a StateChangeEvent.

Example:
```python
async def handler(new_state: D.StateNew[states.LightState]):
    brightness = new_state.attributes.brightness
```
"""

MaybeStateNew: TypeAlias = Annotated[StateT | None, A.get_state_object_new]
"""Extract the new state object from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(new_state: D.MaybeStateNew[states.LightState]):
    if new_state:
        brightness = new_state.attributes.brightness
```
"""


StateOld: TypeAlias = Annotated[StateT, ensure_present(A.get_state_object_old)]
"""Extract the old state object from a StateChangeEvent.

Example:
```python
async def handler(old_state: D.StateOld[states.LightState]):
    if old_state:
        previous_brightness = old_state.attributes.brightness
```
"""

MaybeStateOld: TypeAlias = Annotated[StateT | None, A.get_state_object_old]
"""Extract the old state object from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(old_state: D.MaybeStateOld[states.LightState]):
    if old_state:
        previous_brightness = old_state.attributes.brightness
```
"""


StateOldAndNew: TypeAlias = Annotated[tuple[StateT, StateT], ensure_present(A.get_state_object_old_new)]
"""Extract both old and new state objects from a StateChangeEvent.

Example:
```python
async def handler(states: D.StateOldAndNew[states.LightState]):
    old_state, new_state = states
    if old_state:
        brightness_changed = old_state.attributes.brightness != new_state.attributes.brightness
```
"""

MaybeStateOldAndNew: TypeAlias = Annotated[tuple[StateT | None, StateT | None], A.get_state_object_old_new]
"""Extract both old and new state objects from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(states: D.MaybeStateOldAndNew[states.LightState]):
    old_state, new_state = states
    if old_state:
        brightness_changed = old_state.attributes.brightness != new_state.attributes.brightness
    if new_state:
        current_brightness = new_state.attributes.brightness
```
"""


StateValueNew: TypeAlias = Annotated[StateValueT, A.get_state_value_new]
"""Extract the new state value from a StateChangeEvent.

The state value is the string representation of the state (e.g., "on", "off", "25.5").

Example:
```python
async def handler(new_value: D.StateValueNew[str]):
    self.logger.info("New state value: %s", new_value)
```
"""


StateValueOld: TypeAlias = Annotated[StateValueT, A.get_state_value_old]
"""Extract the old state value from a StateChangeEvent.

The state value is the string representation of the state (e.g., "on", "off", "25.5").

Example:
```python
async def handler(old_value: D.StateValueOld[str]):
    if old_value:
        self.logger.info("Previous state value: %s", old_value)
```
"""

StateValueOldAndNew: TypeAlias = Annotated[tuple[StateValueT, StateValueT], A.get_state_value_old_new]
"""Extract both old and new state values from a StateChangeEvent.

The state values are the string representations of the states (e.g., "on", "off", "25.5").

Example:
```python
async def handler(values: D.StateValueOldAndNew[str]):
    old_value, new_value = values
    if old_value and old_value != new_value:
        self.logger.info("Changed from %s to %s", old_value, new_value)
```
"""

EntityId: TypeAlias = Annotated[str, ensure_present(A.get_entity_id)]
"""Extract the entity_id from a HassEvent.

Returns the entity ID string (e.g., "light.bedroom").

Example:
```python
async def handler(entity_id: D.EntityId):
    self.logger.info("Entity: %s", entity_id)
```
"""

MaybeEntityId: TypeAlias = Annotated[str | FalseySentinel, A.get_entity_id]
"""Extract the entity_id from a HassEvent, returning MISSING_VALUE sentinel if not present."""

Domain: TypeAlias = Annotated[str, ensure_present(A.get_domain)]
"""Extract the domain from a HassEvent.

Returns the domain string (e.g., "light", "sensor") from the event payload or entity_id.

Example:
```python

async def handler(domain: D.Domain):
    if domain == "light":
        self.logger.info("Light entity event")
```
"""

MaybeDomain: TypeAlias = Annotated[str | FalseySentinel, A.get_domain]
"""Extract the domain from a HassEvent, returning MISSING_VALUE sentinel if not present."""

Service: TypeAlias = Annotated[str, ensure_present(A.get_service)]
"""Extract the service name from a CallServiceEvent.

Returns the service name string (e.g., "turn_on", "turn_off").

Example:
```python
async def handler(service: D.Service):
    if service == "turn_on":
        self.logger.info("Light turned on")
```
"""

MaybeService: TypeAlias = Annotated[str | FalseySentinel, A.get_service]
"""Extract the service name from a CallServiceEvent, returning MISSING_VALUE sentinel if not present."""

ServiceData: TypeAlias = Annotated[dict[str, Any], A.get_service_data]
"""Extract the service_data dictionary from a CallServiceEvent.

Returns the service data dictionary containing parameters passed to the service call.
Returns an empty dict if no service_data is present.

Example:
```python
async def handler(service_data: D.ServiceData):
    brightness = service_data.get("brightness")
    if brightness:
        self.logger.info("Brightness set to %s", brightness)
```
"""

EventContext: TypeAlias = Annotated[HassContext, A.get_context]
"""Extract the context object from a HassEvent.

Returns the Home Assistant context object containing metadata about the event
origin (user_id, parent_id, etc.).

Example:
```python
async def handler(context: D.EventContext):
    if context.user_id:
        self.logger.info("Triggered by user: %s", context.user_id)
```
"""

AttrNew = A.get_attr_new
"""Factory for creating annotated types to extract specific attributes from the new state.

Usage:
```python
from typing import Annotated
from hassette import dependencies as D

async def handler(
    brightness: Annotated[int | None, D.AttrNew("brightness")],
):
    pass
```
"""

AttrOld = A.get_attr_old
"""Factory for creating annotated types to extract specific attributes from the old state.

Usage:
```python
from typing import Annotated
from hassette import dependencies as D

async def handler(
    brightness: Annotated[int | None, D.AttrOld("brightness")],
):
    pass
```
"""

AttrOldAndNew = A.get_attr_old_new
"""Factory for creating annotated types to extract specific attributes from both old and new states.

Usage:
```python
from typing import Annotated
from hassette import dependencies as D

async def handler(
    brightness: Annotated[tuple[int | None, int | None], D.AttrOldAndNew("brightness")],
):
    pass
```
"""
