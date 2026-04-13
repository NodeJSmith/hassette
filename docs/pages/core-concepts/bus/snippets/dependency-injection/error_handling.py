from typing import Annotated

from hassette import A, App


class ErrorApp(App):
    async def handler(self, value: Annotated[int, A.get_attr_new("invalid_field")]):
        pass

    # Listener error (topic=hass.event.state_changed): Handler 'my_project.main.ErrorApp.handler' -
    # failed to convert parameter 'value' of type 'FalseySentinel' to type 'int': Unable to convert
    # <MISSING_VALUE> to <class 'int'>
