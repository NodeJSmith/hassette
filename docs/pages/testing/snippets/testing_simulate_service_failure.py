from hassette.app import App, AppConfig
from hassette.test_utils import AppTestHarness
from hassette.types.enums import ResourceStatus


class WatchdogConfig(AppConfig):
    pass


class WatchdogApp(App[WatchdogConfig]):
    async def on_initialize(self):
        self.bus.on_hassette_service_failed(handler=self.on_service_failed)

    async def on_service_failed(self) -> None:
        await self.api.call_service(
            "notify", "send_message", message="Service failed"
        )


async def test_service_failure_triggers_notification():
    async with AppTestHarness(WatchdogApp, config={}) as harness:
        await harness.simulate_hassette_service_failed("WebSocketService")
        harness.api_recorder.assert_called(
            "call_service",
            domain="notify",
            service="send_message",
            message="Service failed",
        )


async def test_granular_service_status():
    """You can also simulate specific status transitions."""
    async with AppTestHarness(WatchdogApp, config={}) as harness:
        await harness.simulate_hassette_service_status(
            "SchedulerService",
            ResourceStatus.FAILED,
            previous_status=ResourceStatus.RUNNING,
            exception=ConnectionError("connection lost"),
        )
        harness.api_recorder.assert_called(
            "call_service",
            domain="notify",
            service="send_message",
            message="Service failed",
        )
