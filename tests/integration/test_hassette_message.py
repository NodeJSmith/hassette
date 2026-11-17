"""hass-hassette messages reach `on_hassette_message` handlers with `D.MessageData[T]` validated."""

from dataclasses import dataclass

from hassette import D
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.testing import AppTestHarness


@dataclass
class TrackerDone:
    room: str
    count: int = 0


class TrackerApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        self.received: list[TrackerDone] = []
        await self.bus.on_hassette_message("tracker_done", handler=self.on_tracker_done, name="tracker.done")

    async def on_tracker_done(self, data: D.MessageData[TrackerDone]) -> None:
        self.received.append(data)


async def test_message_data_validates_into_the_annotated_type():
    """A matching message's `data` arrives as the annotated dataclass, with lax coercion."""
    async with AppTestHarness(TrackerApp, config={"instance_name": "tracker"}) as harness:
        await harness.simulate_hassette_message("tracker_done", {"room": "kitchen", "count": "2"})

        assert harness.app.received == [TrackerDone(room="kitchen", count=2)]


async def test_message_filter_ignores_other_names():
    """`on_hassette_message("tracker_done")` doesn't fire for a message with another name."""
    async with AppTestHarness(TrackerApp, config={"instance_name": "tracker"}) as harness:
        await harness.simulate_hassette_message("something_else", {"room": "kitchen"})

        assert harness.app.received == []


async def test_message_without_data_fails_a_required_field():
    """A message sent without `data` validates `{}`, so a required field skips the handler."""
    async with AppTestHarness(TrackerApp, config={"instance_name": "tracker"}) as harness:
        await harness.simulate_hassette_message("tracker_done")

        assert harness.app.received == []
