from hassette import App


class MinutelyApp(App):
    async def on_initialize(self):
        # Every minute
        self.scheduler.run_minutely(self.task)

        # Every 5 minutes
        self.scheduler.run_minutely(self.task, minutes=5)

    async def task(self):
        pass
