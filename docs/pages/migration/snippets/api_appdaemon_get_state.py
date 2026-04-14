from appdaemon.plugins.hass import Hass


class StateGetter(Hass):
    def initialize(self):
        office_light_state = self.get_state("light.office_light_1", attribute="all")
        self.log(f"{office_light_state=}")
