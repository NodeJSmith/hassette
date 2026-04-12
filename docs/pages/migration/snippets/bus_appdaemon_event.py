from datetime import datetime
from typing import Any

from appdaemon.adapi import ADAPI


class ButtonHandler(ADAPI):
    def initialize(self):
        # Listen for a button press event with a specific entity_id
        self.listen_event(
            self.minimal_callback,
            "call_service",
            service="press",
            entity_id="input_button.test_button",
        )

    def minimal_callback(self, event_name: str, event_data: dict[str, Any], **kwargs: Any) -> None:
        self.log(f"{event_name=}, {event_data=}, {kwargs=}")
