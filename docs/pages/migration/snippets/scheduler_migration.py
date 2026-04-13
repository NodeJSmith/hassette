from datetime import time

from hassette import App


class MySchedulerApp(App):
    async def on_initialize(self):
        self.scheduler.run_in(self.delayed_task, delay=60)
        self.scheduler.run_daily(self.morning_task, start=time(7, 30))
        job = self.scheduler.run_every(self.periodic_task, interval=300, start=self.now())

    async def delayed_task(self):
        pass

    async def morning_task(self):
        pass

    async def periodic_task(self):
        pass
