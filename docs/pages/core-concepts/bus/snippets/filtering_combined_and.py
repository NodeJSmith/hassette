from typing import Annotated

from hassette import A, App, C, P


class DoorApp(App):
    async def on_initialize(self):
        # Logical AND (Implicit in list)
        # Triggers if:
        # - brightness > 254 AND
        # - rgb_color != [0, 0, 0]
        self.bus.on_state_change(
            "light.office",
            handler=self.on_light_change,
            where=[
                P.AttrTo("brightness", C.Comparison(op=">", value=254)),
                P.AttrTo("rgb_color", C.Comparison(op="!=", value=[0, 0, 0])),
            ],
            # NOTE: changed=False is required if we want this to fire even when only attributes change
            changed=False,
        )

    async def on_light_change(self, brightness: Annotated[int, A.get_attr_new("brightness")]):
        self.logger.info("Light changed with brightness %d", brightness)
