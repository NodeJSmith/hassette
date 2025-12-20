from typing import Annotated, Any

from hassette import accessors as A


# define your own conversion method
def converter(value: Any) -> int:
    return int(value) if value else 0


async def handler(
    # Pass `converter` after extractor function
    brightness: Annotated[int, A.get_attr_new("brightness"), converter],
):
    assert isinstance(brightness, int)
