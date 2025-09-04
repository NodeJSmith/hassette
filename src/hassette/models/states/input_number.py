from typing import Literal

from pydantic import Field

from .base import AttributesBase, BaseState


class InputNumberState(BaseState[int | float | None]):
    class Attributes(AttributesBase):
        total_debt: float | None = Field(default=None)
        total_debt_change: float | None = Field(default=None)
        total_debt_percent_change: float | None = Field(default=None)
        total_debt_change_direction: str | None = Field(default=None)
        previous_total_debt: float | None = Field(default=None)
        max: float | None = Field(default=None)
        initial: float | None = Field(default=None)
        step: int | float | None = Field(default=None)
        mode: str | None = Field(default=None)
        min: int | float | None = Field(default=None)
        history_date: str | None = Field(default=None)
        total_credits: float | None = Field(default=None)
        total_debits: float | None = Field(default=None)
        history_balance: float | None = Field(default=None)
        diff: float | None = Field(default=None)
        percent_change: float | None = Field(default=None)
        change_direction: str | None = Field(default=None)
        apr: float | None = Field(default=None)

    domain: Literal["input_number"]

    attributes: Attributes
