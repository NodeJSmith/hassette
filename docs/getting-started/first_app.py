from hassette import App, AppConfig, StateChangeEvent, states


class MyConfig(AppConfig):
    pass


class MyApp(App[MyConfig]):
    async def on_initialize(self):
        self.logger.info("Getting started with Hassette!")
        self.scheduler.run_in(self.print_states_on_startup, delay=1)
        self.bus.on_state_change("sun.*", handler=self.changed)
        self.scheduler.run_minutely(self.log_heartbeat)

    async def print_states_on_startup(self):
        states = await self.api.get_states()
        for state in states[:2]:
            self.logger.info("State: %s = %s", state.entity_id, state.value)

        self.logger.info("...")

        for state in states[-2:]:
            self.logger.info("State: %s = %s", state.entity_id, state.value)

    async def changed(self, event: StateChangeEvent[states.SunState]):
        self.logger.info("Sun changed: %s", event.payload.data)

    async def log_heartbeat(self):
        self.logger.info("Heartbeat")
