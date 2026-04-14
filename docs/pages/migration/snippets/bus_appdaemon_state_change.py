from appdaemon.plugins.hass import Hass


class ButtonPressed(Hass):
    def initialize(self):
        self.listen_state(self.button_pressed, "input_button.test_button", arg1=123)

    def button_pressed(self, entity, attribute, old, new, arg1, **kwargs):
        self.log(f"{entity=} {attribute=} {old=} {new=} {arg1=}")
