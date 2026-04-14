from typing import Literal

from hassette import App
from hassette.models.states.base import StringBaseState


class MyCustomState(StringBaseState):
    domain: Literal["my_custom_domain"]


class MyApp(App):
    async def on_initialize(self):
        # Custom domains (use states[<class>] for typing)
        custom_states = self.states[MyCustomState]
        for entity_id, state in custom_states:
            print(state.value)
