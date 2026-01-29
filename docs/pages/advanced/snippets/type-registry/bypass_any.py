from typing import Annotated, Any

from hassette import accessors as A


async def handler(
    # No automatic conversion - accepts whatever type is returned
    brightness_raw: Annotated[Any, A.get_attr_new("brightness")],
):
    # Handle conversion yourself
    int(brightness_raw) if brightness_raw else None
