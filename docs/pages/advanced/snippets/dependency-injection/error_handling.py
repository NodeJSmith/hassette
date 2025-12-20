from typing import Annotated

from hassette import App, accessors as A


class ErrorApp(App):
    # If "not_a_number" can't be converted to int
    async def handler(
        self,
        value: Annotated[int, A.get_attr_new("invalid_field")],
    ):
        pass

    # UnableToConvertValueError - Unable to convert 'heap' to ClimateValueType
