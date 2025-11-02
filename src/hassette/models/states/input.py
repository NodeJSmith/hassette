from typing import Any, Literal

from pydantic import Field
from whenever import Instant, ZonedDateTime

from hassette.utils.date_utils import convert_utc_timestamp_to_system_tz

from .base import AttributesBase, BoolBaseState, DateTimeBaseState, NumericBaseState, StringBaseState


class InputAttributesBase(AttributesBase):
    """Base attributes class for all input states."""

    editable: bool | None = Field(default=None)


class InputBooleanState(BoolBaseState):
    """Representation of a Home Assistant input_boolean state.

    See: https://www.home-assistant.io/integrations/input_boolean/
    """

    domain: Literal["input_boolean"]

    attributes: InputAttributesBase


class InputButtonState(DateTimeBaseState):
    """Representation of a Home Assistant input_button state.

    See: https://www.home-assistant.io/integrations/input_button/
    """

    domain: Literal["input_button"]

    attributes: InputAttributesBase


class InputDatetimeState(DateTimeBaseState):
    """Representation of a Home Assistant input_datetime state.

    See: https://www.home-assistant.io/integrations/input_datetime/
    """

    class Attributes(InputAttributesBase):
        has_date: bool | None = Field(default=None)
        has_time: bool | None = Field(default=None)
        year: int | None = Field(default=None)
        month: int | None = Field(default=None)
        day: int | None = Field(default=None)
        hour: int | None = Field(default=None)
        minute: int | None = Field(default=None)
        second: int | None = Field(default=None)
        timestamp: float | None = Field(default=None)

        @property
        def timestamp_as_instant(self) -> Instant | None:
            if self.timestamp is None:
                return None
            return Instant.from_timestamp(self.timestamp)

        @property
        def timestamp_as_system_datetime(self) -> ZonedDateTime | None:
            if self.timestamp is None:
                return None
            return convert_utc_timestamp_to_system_tz(self.timestamp)

    domain: Literal["input_datetime"]

    attributes: Attributes


class InputNumberState(NumericBaseState):
    """Representation of a Home Assistant input_number state.

    See: https://www.home-assistant.io/integrations/input_number/
    """

    class Attributes(InputAttributesBase):
        max: float | None = Field(default=None)
        initial: float | None = Field(default=None)
        step: int | float | None = Field(default=None)
        mode: str | None = Field(default=None)
        min: int | float | None = Field(default=None)

    domain: Literal["input_number"]

    attributes: Attributes


class InputSelectState(StringBaseState):
    """Representation of a Home Assistant input_select state.

    See: https://www.home-assistant.io/integrations/input_select/
    """

    class Attributes(InputAttributesBase):
        options: list[str] = Field(default_factory=list)

    domain: Literal["input_select"]

    attributes: Attributes


class InputTextState(StringBaseState):
    """Representation of a Home Assistant input_text state.

    See: https://www.home-assistant.io/integrations/input_text/
    """

    class Attributes(InputAttributesBase):
        min: int | float | None = Field(default=None)
        max: int | float | None = Field(default=None)
        pattern: Any | None = Field(default=None)
        mode: str | None = Field(default=None)

    domain: Literal["input_text"]

    attributes: Attributes
