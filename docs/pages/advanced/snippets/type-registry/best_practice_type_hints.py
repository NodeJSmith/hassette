from typing import Annotated

from hassette import A


# TypeRegistry converts automatically based on type hint
async def handler(
    temperature: Annotated[float, A.get_attr_new("temperature")],
    humidity: Annotated[int, A.get_attr_new("humidity")],
):
    # temperature and humidity are already the correct types
    pass
