from typing import Annotated

from hassette import A, App, C, P


class LightApp(App):
    async def on_initialize(self):
        # Logical OR (AnyOf)
        # Triggers if ANY of the conditions match
        await self.bus.on_state_change(
            "light.office",
            handler=self.on_light_change,
            where=P.AnyOf(
                (
                    P.AttrTo("rgb_color", C.Comparison(op="eq", value=[255, 255, 255])),
                    P.AttrTo("brightness", C.Comparison(op=">=", value=200)),
                )
            ),
            changed=False,
            name="office_bright_or_white",
        )

    async def on_light_change(
        self,
        brightness: Annotated[int, A.get_attr_new("brightness")],
        rgb_color: Annotated[list[int], A.get_attr_new("rgb_color")],
    ):
        self.logger.info("Light changed with brightness %d", brightness)
        self.logger.info("Light changed with rgb_color %s", rgb_color)
