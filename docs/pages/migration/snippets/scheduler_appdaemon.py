from datetime import time

from appdaemon.plugins.hass import Hass


class MySchedulerApp(Hass):
    def initialize(self):
        self.run_in(self.delayed_task, 60)
        self.run_daily(self.morning_task, time(7, 30))
        self.periodic_handle = self.run_every(
            self.periodic_task, "now", 300
        )

    def delayed_task(self, **kwargs):
        pass

    def morning_task(self, **kwargs):
        pass

    def periodic_task(self, **kwargs):
        pass
