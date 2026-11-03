from hassette import App
from hassette.models.states import LightEntityFeature


class FeatureCheckApp(App):
    async def on_initialize(self):
        light = self.states.light.get("light.kitchen")
        if light is None:
            return
        if light.attributes.has_feature(LightEntityFeature.TRANSITION):
            self.logger.info("Kitchen light supports transitions")
