"""Dependencies are special annotated types that extract data from events.

These are designed to be used in event handlers to automatically extract commonly used
data from events without boilerplate code.

For example, instead of writing:

```python
async def handle_state_change(event: StateChangeEvent):
    new_state = event.payload.data.new_state
    # do something with new_state
```

You can use the `NewState` dependency:
```python
from hassette import dependencies as D
from hassette import states

async def handle_state_change(new_state: D.StateNew[states.ButtonState]):
    # do something with new_state
```

Hassette will automatically extract the value from the incoming event, cast it to the correct type,
and pass it to your handler.

If you need to write your own dependencies, you can easily do so by annotating
your parameter(s) with `Annotated` and either using an existing accessor from
[accessors][hassette.bus.accessors] or writing your own accessor function.

Examples:
    Extracting the new state object from a StateChangeEvent
    ```python
    from hassette import dependencies as D
    from hassette import states

    async def handle_state_change(new_state: D.StateNew[states.ButtonState]):
        # new_state is automatically extracted and typed as states.ButtonState
        print(new_state.state)
    ```

    Extracting the entity_id from any HassEvent
    ```python
    from hassette import dependencies as D

    async def handle_event(entity_id: D.EntityId):
        # entity_id is automatically extracted
        print(entity_id)
    ```

    Writing your own dependency
    ```python
    from pathlib import Path

    from typing import Annotated
    from hassette.bus import accessors as A

    async def handle_event(
        file_path: Annotated[Path, A.get_path("payload.data.changed_file_path")],
    ):
        # do something with file_path
    ```

"""

from .classes import (
    AttrNew,
    AttrOld,
    AttrOldAndNew,
    Domain,
    EntityId,
    EventContext,
    ServiceData,
    StateNew,
    StateOld,
    StateOldAndNew,
    StateValueNew,
    StateValueOld,
    StateValueOldAndNew,
)

__all__ = [
    "AttrNew",
    "AttrOld",
    "AttrOldAndNew",
    "Domain",
    "EntityId",
    "EventContext",
    "ServiceData",
    "StateNew",
    "StateOld",
    "StateOldAndNew",
    "StateValueNew",
    "StateValueOld",
    "StateValueOldAndNew",
]
