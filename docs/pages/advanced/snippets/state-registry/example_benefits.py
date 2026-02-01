from typing import Annotated

from hassette import A


# TypeRegistry also works in dependency injection
# and converts attribute values too
async def handler(brightness: Annotated[int, A.get_attr_new("brightness")]):
    # brightness is int, not string, thanks to TypeRegistry
    pass
