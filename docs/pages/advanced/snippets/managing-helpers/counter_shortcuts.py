from hassette import App, AppConfig
from hassette.models.helpers import CreateCounterParams


class MotionCycleApp(App[AppConfig]):
    cycle_counter_id: str = "motionapp_cycles"

    async def on_initialize(self) -> None:
        await self.ensure_cycle_counter()
        self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_motion,
        )

    async def on_motion(self) -> None:
        await self.api.increment_counter(f"counter.{self.cycle_counter_id}")

    async def ensure_cycle_counter(self) -> None:
        for record in await self.api.list_counters():
            if record.id == self.cycle_counter_id:
                return
        await self.api.create_counter(
            CreateCounterParams(name="motionapp_cycles", initial=0)
        )
