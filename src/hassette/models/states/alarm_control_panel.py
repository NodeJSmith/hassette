from typing import Any, Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class AlarmControlPanelState(StringBaseState):
    """Representation of a Home Assistant alarm_control_panel state.

    See: https://www.home-assistant.io/integrations/alarm_control_panel/
    """

    class Attributes(AttributesBase):
        code_format: str | None = Field(default=None)
        changed_by: Any | None = Field(default=None)
        code_arm_required: bool | None = Field(default=None)
        previous_state: Any | None = Field(default=None)
        next_state: Any | None = Field(default=None)

    domain: Literal["alarm_control_panel"]

    attributes: Attributes
