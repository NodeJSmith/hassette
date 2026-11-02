"""App-level error handlers and listener keys registered in an app's init hooks survive startup.

An app's own hooks run before its Bus and Scheduler children initialize, so those children must not
reset anything during their own initialization.
"""

import pytest

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.bus.error_context import BusErrorContext
from hassette.exceptions import DuplicateListenerError
from hassette.scheduler.error_context import SchedulerErrorContext
from hassette.testing import AppTestHarness, wait_for
from hassette.types.types import IfExistsPolicy
from tests.support.scheduler_dispatch_helpers import get_job_by_name

HOOK_APP_CONFIG = {"instance_name": "hook_app"}


class ErrorHandlerApp(App[AppConfig]):
    """Registers app-level error handlers, a failing listener, and a failing job from `register()`."""

    bus_errors: list[BusErrorContext]
    scheduler_errors: list[SchedulerErrorContext]

    async def register(self) -> None:
        self.bus_errors = []
        self.scheduler_errors = []
        self.bus.on_error(self.record_bus_error)
        self.scheduler.on_error(self.record_scheduler_error)
        await self.bus.on_state_change("light.kitchen", handler=self.failing_handler, name="failing_listener")
        await self.scheduler.run_in(self.failing_job, 60, name="failing_job")

    async def failing_handler(self) -> None:
        raise RuntimeError("handler failed")

    async def failing_job(self) -> None:
        raise RuntimeError("job failed")

    async def record_bus_error(self, ctx: BusErrorContext) -> None:
        self.bus_errors.append(ctx)

    async def record_scheduler_error(self, ctx: SchedulerErrorContext) -> None:
        self.scheduler_errors.append(ctx)


class RegistersInBeforeInitialize(ErrorHandlerApp):
    async def before_initialize(self) -> None:
        await self.register()


class RegistersInOnInitialize(ErrorHandlerApp):
    async def on_initialize(self) -> None:
        await self.register()


class RegistersInAfterInitialize(ErrorHandlerApp):
    async def after_initialize(self) -> None:
        await self.register()


HOOK_APPS = [RegistersInBeforeInitialize, RegistersInOnInitialize, RegistersInAfterInitialize]


@pytest.mark.parametrize("app_cls", HOOK_APPS)
async def test_bus_on_error_from_init_hook_fires(app_cls: type[ErrorHandlerApp]) -> None:
    """A bus.on_error handler registered in an init hook receives a listener's exception."""
    async with AppTestHarness(app_cls, config=HOOK_APP_CONFIG) as harness:
        await harness.set_state("light.kitchen", "off")

        await harness.simulate_state_change("light.kitchen", old_value="off", new_value="on")

        await wait_for(lambda: len(harness.app.bus_errors) == 1, desc="bus on_error handler fired")
        assert str(harness.app.bus_errors[0].exception) == "handler failed"


@pytest.mark.parametrize("app_cls", HOOK_APPS)
async def test_scheduler_on_error_from_init_hook_fires(app_cls: type[ErrorHandlerApp]) -> None:
    """A scheduler.on_error handler registered in an init hook receives a job's exception."""
    async with AppTestHarness(app_cls, config=HOOK_APP_CONFIG) as harness:
        job = await get_job_by_name(harness, "failing_job")
        assert job.next_run is not None
        harness.freeze_time(job.next_run.add(seconds=1))

        await harness.trigger_due_jobs()

        await wait_for(lambda: len(harness.app.scheduler_errors) == 1, desc="scheduler on_error handler fired")
        assert str(harness.app.scheduler_errors[0].exception) == "job failed"


@pytest.mark.parametrize("app_cls", HOOK_APPS)
async def test_listener_key_from_init_hook_survives_startup(app_cls: type[ErrorHandlerApp]) -> None:
    """A listener registered in an init hook keeps its natural key once startup finishes."""
    async with AppTestHarness(app_cls, config=HOOK_APP_CONFIG) as harness:
        assert [key[2] for key in harness.app.bus._registered_listeners] == ["failing_listener"]


async def test_duplicate_name_after_startup_raises_by_default() -> None:
    """Re-registering a hook's listener name after startup raises instead of adding a second listener."""
    async with AppTestHarness(RegistersInOnInitialize, config=HOOK_APP_CONFIG) as harness:
        app = harness.app

        with pytest.raises(DuplicateListenerError):
            await app.bus.on_state_change("light.kitchen", handler=app.failing_handler, name="failing_listener")

        assert len(app.bus.get_listeners()) == 1


@pytest.mark.parametrize("if_exists", ["skip", "replace"])
async def test_if_exists_after_startup_sees_listener_from_init_hook(if_exists: IfExistsPolicy) -> None:
    """`skip` and `replace` act on a hook's listener after startup, leaving one listener rather than two."""
    async with AppTestHarness(RegistersInOnInitialize, config=HOOK_APP_CONFIG) as harness:
        app = harness.app

        await app.bus.on_state_change(
            "light.kitchen",
            handler=app.failing_handler,
            name="failing_listener",
            if_exists=if_exists,
        )

        assert len(app.bus.get_listeners()) == 1
