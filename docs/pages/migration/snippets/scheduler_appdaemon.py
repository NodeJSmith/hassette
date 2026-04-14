from appdaemon.plugins.hass import Hass


class NightLight(Hass):
    # function which will be called at startup and reload
    def initialize(self):
        # Schedule a daily callback that will call run_daily_callback() at 7pm every night
        self.run_daily(self.run_daily_callback, "19:00:00")

    # Our callback function will be called by the scheduler every day at 7pm
    def run_daily_callback(self, **kwargs):
        # Call to Home Assistant to turn the porch light on
        self.turn_on("light.porch")
