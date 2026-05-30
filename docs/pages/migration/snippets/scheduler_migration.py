from hassette import App


class MySchedulerApp(App):
    async def on_initialize(self):
        await self.scheduler.run_in(self.delayed_task, delay=60)
        await self.scheduler.run_daily(self.morning_task, at="07:30")
        job = await self.scheduler.run_every(self.periodic_task, seconds=300)

    async def delayed_task(self):
        pass

    async def morning_task(self):
        pass

    async def periodic_task(self):
        pass
