from typing import Literal

from pydantic import Field

from .base import AttributesBase, NumericBaseState


class CounterAttributes(AttributesBase):
    initial: int | None = Field(default=None)
    minimum: int | None = Field(default=None)
    maximum: int | None = Field(default=None)
    step: int | None = Field(default=None)
    restore: bool | None = Field(default=None)
    editable: bool | None = Field(default=None)


class CounterState(NumericBaseState):
    """Representation of a Home Assistant counter state.

    See: https://www.home-assistant.io/integrations/counter/

    Note:
        ``CounterState`` represents the *live runtime value* of a counter
        entity. For the stored configuration (``initial``, ``minimum``,
        ``maximum``, ``step``, ``restore``), use
        :class:`hassette.models.helpers.CounterRecord` via
        ``Api.list_counters``/``create_counter``/``update_counter``.
    """

    domain: Literal["counter"]

    attributes: CounterAttributes
