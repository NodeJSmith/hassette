from hassette import App


class MySchedulerApp(App):
    async def on_initialize(self):
        await self.scheduler.run_in(
            self.delayed_task, delay=60, name="delayed_task"
        )
        await self.scheduler.run_daily(
            self.morning_task, at="07:30", name="morning_task"
        )
        job = await self.scheduler.run_every(
            self.periodic_task, seconds=300, name="periodic_task"
        )

    async def delayed_task(self):
        pass

    async def morning_task(self):
        pass

    async def periodic_task(self):
        pass
