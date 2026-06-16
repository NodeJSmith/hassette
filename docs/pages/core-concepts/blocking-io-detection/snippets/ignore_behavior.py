from hassette import App, AppConfig
from hassette.types.enums import BlockingIOBehavior


class LegacyAppConfig(AppConfig):
    app_key: str = "legacy_app"
    # Suppress detection for this app while migration is in progress.
    blocking_io_behavior: BlockingIOBehavior | None = BlockingIOBehavior.IGNORE


class LegacyApp(App[LegacyAppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_door,
            name="front_door_open",
        )

    async def on_door(self) -> None:
        # Synchronous file read — currently suppressed while migrating.
        with open("/data/door_log.txt", "a") as f:  # noqa: ASYNC230
            f.write("door opened\n")
