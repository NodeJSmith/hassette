from typing import Annotated, Any, TypeAlias

from typing_extensions import Sentinel

from hassette.bus import accessors as A
from hassette.events import HassContext
from hassette.models.states import StateT, StateValueT

StateNew: TypeAlias = Annotated[StateT, A.get_state_object_new]
"""Extract the new state object from a StateChangeEvent.

Example:
```python
async def handler(new_state: D.StateNew[states.LightState]):
    brightness = new_state.attributes.brightness
```
"""

StateOld: TypeAlias = Annotated[StateT, A.get_state_object_old]
"""Extract the old state object from a StateChangeEvent.

Example:
```python
async def handler(old_state: D.StateOld[states.LightState]):
    if old_state:
        previous_brightness = old_state.attributes.brightness
```
"""

StateOldAndNew: TypeAlias = Annotated[tuple[StateT, StateT], A.get_state_object_old_new]
"""Extract both old and new state objects from a StateChangeEvent.

Example:
```python
async def handler(states: D.StateOldAndNew[states.LightState]):
    old_state, new_state = states
    if old_state:
        brightness_changed = old_state.attributes.brightness != new_state.attributes.brightness
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

EntityId: TypeAlias = Annotated[str | Sentinel, A.get_entity_id]
"""Extract the entity_id from a HassEvent.

Returns the entity ID string (e.g., "light.bedroom"), or `MISSING_VALUE` sentinel
if the event does not contain an entity_id field.

Example:
```python
from hassette.types import MISSING_VALUE

async def handler(entity_id: D.EntityId):
    if entity_id is not MISSING_VALUE:
        self.logger.info("Entity: %s", entity_id)
```
"""

Domain: TypeAlias = Annotated[str | Sentinel, A.get_domain]
"""Extract the domain from a HassEvent.

Returns the domain string (e.g., "light", "sensor"), or `MISSING_VALUE` sentinel
if the event does not contain a domain field. Extracted from the entity_id.

Example:
```python
from hassette.types import MISSING_VALUE

async def handler(domain: D.Domain):
    if domain == "light":
        self.logger.info("Light entity event")
```
"""

Service: TypeAlias = Annotated[str | Sentinel, A.get_service]
"""Extract the service name from a CallServiceEvent.

Returns the service name string (e.g., "turn_on", "turn_off"), or `MISSING_VALUE`
sentinel if the event does not contain a service field.

Example:
```python
async def handler(service: D.Service):
    if service == "turn_on":
        self.logger.info("Light turned on")
```
"""

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
