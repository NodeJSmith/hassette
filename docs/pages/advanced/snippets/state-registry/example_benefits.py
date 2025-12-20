from typing import Annotated

from hassette import STATE_REGISTRY, accessors as A

# StateRegistry determines this is a LightState
# light_state = STATE_REGISTRY.try_convert_state(light_dict) # light_dict not defined in context


# TypeRegistry also works in dependency injection
async def handler(
    # TypeRegistry converts attribute values too
    brightness: Annotated[int, A.get_attr_new("brightness")],
):
    # brightness is int, not string, thanks to TypeRegistry
    pass
