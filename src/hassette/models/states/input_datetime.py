from typing import Literal

from pydantic import Field
from whenever import Date, Instant, PlainDateTime, SystemDateTime

from .base import AttributesBase, BaseState


class InputDatetimeState(BaseState[Instant | PlainDateTime | Date | None]):
    class Attributes(AttributesBase):
        has_date: bool | None = Field(default=None)
        has_time: bool | None = Field(default=None)
        editable: bool | None = Field(default=None)
        year: int | None = Field(default=None)
        month: int | None = Field(default=None)
        day: int | None = Field(default=None)
        hour: int | None = Field(default=None)
        minute: int | None = Field(default=None)
        second: int | None = Field(default=None)
        timestamp: float | None = Field(default=None)

        @property
        def timestamp_as_instant(self) -> Instant | PlainDateTime | None:
            if self.timestamp is None:
                return None
            return Instant.from_timestamp(self.timestamp)

        @property
        def timestamp_as_system_datetime(self) -> SystemDateTime | None:
            if self.timestamp is None:
                return None
            return SystemDateTime.from_timestamp(self.timestamp)

    domain: Literal["input_datetime"]

    attributes: Attributes | None = Field(default=None)
