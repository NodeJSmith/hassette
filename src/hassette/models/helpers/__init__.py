"""Pydantic models for Home Assistant helper CRUD.

Each helper domain exposes three models:

- ``{Domain}Record`` — stored helper config returned by HA (``extra="allow"``).
- ``Create{Domain}Params`` — parameters accepted by ``{domain}/create``.
- ``Update{Domain}Params`` — parameters accepted by ``{domain}/update``
  (``extra="ignore"`` to permit round-tripping Records that carry fields
  Hassette does not yet model).
"""

from .counter import CounterRecord, CreateCounterParams, UpdateCounterParams
from .input_boolean import CreateInputBooleanParams, InputBooleanRecord, UpdateInputBooleanParams
from .input_button import CreateInputButtonParams, InputButtonRecord, UpdateInputButtonParams
from .input_datetime import CreateInputDatetimeParams, InputDatetimeRecord, UpdateInputDatetimeParams
from .input_number import CreateInputNumberParams, InputNumberRecord, UpdateInputNumberParams
from .input_select import CreateInputSelectParams, InputSelectRecord, UpdateInputSelectParams
from .input_text import CreateInputTextParams, InputTextRecord, UpdateInputTextParams
from .timer import CreateTimerParams, TimerRecord, UpdateTimerParams

__all__ = [
    "CounterRecord",
    "CreateCounterParams",
    "CreateInputBooleanParams",
    "CreateInputButtonParams",
    "CreateInputDatetimeParams",
    "CreateInputNumberParams",
    "CreateInputSelectParams",
    "CreateInputTextParams",
    "CreateTimerParams",
    "InputBooleanRecord",
    "InputButtonRecord",
    "InputDatetimeRecord",
    "InputNumberRecord",
    "InputSelectRecord",
    "InputTextRecord",
    "TimerRecord",
    "UpdateCounterParams",
    "UpdateInputBooleanParams",
    "UpdateInputButtonParams",
    "UpdateInputDatetimeParams",
    "UpdateInputNumberParams",
    "UpdateInputSelectParams",
    "UpdateInputTextParams",
    "UpdateTimerParams",
]
