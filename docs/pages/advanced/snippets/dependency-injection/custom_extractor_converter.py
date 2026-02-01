from datetime import datetime
from typing import Annotated

from hassette import App
from hassette.event_handling.dependencies import AnnotationDetails
from hassette.events import RawStateChangeEvent


def extract_timestamp(event: RawStateChangeEvent) -> str | None:
    """Extract last_changed timestamp from new state."""
    new_state = event.payload.data.new_state
    return new_state.get("last_changed", None) if new_state else None


def convert_to_datetime(value: str, _to_type: type) -> datetime:
    """Convert ISO string to datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


LastChanged = Annotated[
    datetime,
    AnnotationDetails(extractor=extract_timestamp, converter=convert_to_datetime),
]


class TimestampApp(App):
    async def on_state_change(
        self,
        changed_at: LastChanged,
    ):
        self.logger.info("State changed at: %s", changed_at)
