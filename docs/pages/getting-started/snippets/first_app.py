from hassette import App, AppConfig, states
from hassette import dependencies as D


class MyConfig(AppConfig):
    pass


class MyApp(App[MyConfig]):
    async def on_initialize(self):
        self.logger.info("Getting started with Hassette!")
        self.scheduler.run_in(self.print_states_on_startup, delay=1)
        self.bus.on_state_change("sun.*", handler=self.changed)
        self.scheduler.run_minutely(self.log_heartbeat)

    async def print_states_on_startup(self):
        # Use state cache for instant access to all entities
        all_states = self.states.all
        state_list = list(all_states.values())

        for state in state_list[:2]:
            self.logger.info("State: %s = %s", state.entity_id, state.value)

        self.logger.info("...")

        for state in state_list[-2:]:
            self.logger.info("State: %s = %s", state.entity_id, state.value)

        # Count entities by domain
        self.logger.info("Total lights: %d", len(self.states.light))
        self.logger.info("Total sensors: %d", len(self.states.sensor))

    async def changed(self, new_state: D.StateNew[states.SunState]):
        self.logger.info("Sun changed: %s", new_state.value)

    async def log_heartbeat(self):
        self.logger.info("Heartbeat")
