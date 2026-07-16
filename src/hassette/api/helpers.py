"""Helper CRUD client for Home Assistant input_* / counter / timer entities.

`HelperClient` exposes 4 generic CRUD methods (`list`, `create`, `update`, `delete`) and 3 counter
shortcuts (`increment`, `decrement`, `reset`). Each CRUD method has 8 hand-maintained `@overload`
declarations — one per helper domain — so callers get fully typed inputs and outputs despite the
single generic implementation underneath.

Examples:
    ```python
    # List existing helpers
    records = await self.api.helpers.list("input_boolean")

    # Create a helper (typed params in, typed record out)
    record = await self.api.helpers.create(CreateInputBooleanParams(name="vacation_mode", initial=True))

    # Update a helper
    updated = await self.api.helpers.update(record.id, UpdateInputBooleanParams(initial=False))

    # Delete a helper
    await self.api.helpers.delete("input_boolean", record.id)

    # Counter shortcuts (operate on live entity state, not stored config)
    await self.api.helpers.increment("counter.motion_count")
    ```
"""

import typing
from typing import Any, Literal, overload

from pydantic import BaseModel

from hassette.models.helpers import (
    CounterRecord,
    CreateCounterParams,
    CreateInputBooleanParams,
    CreateInputButtonParams,
    CreateInputDatetimeParams,
    CreateInputNumberParams,
    CreateInputSelectParams,
    CreateInputTextParams,
    CreateTimerParams,
    InputBooleanRecord,
    InputButtonRecord,
    InputDatetimeRecord,
    InputNumberRecord,
    InputSelectRecord,
    InputTextRecord,
    TimerRecord,
    UpdateCounterParams,
    UpdateInputBooleanParams,
    UpdateInputButtonParams,
    UpdateInputDatetimeParams,
    UpdateInputNumberParams,
    UpdateInputSelectParams,
    UpdateInputTextParams,
    UpdateTimerParams,
)
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.types.types import LOG_LEVEL_TYPE

from .api import _expect_dict, _expect_list, _ws_helper_call

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.api.api import Api

HelperDomain = Literal[
    "input_boolean",
    "input_number",
    "input_text",
    "input_select",
    "input_datetime",
    "input_button",
    "counter",
    "timer",
]
"""Literal union of all helper domain strings supported by `HelperClient`."""

# Maps Create*Params type -> (domain_string, Record type, id_key_name)
CREATE_DISPATCH: dict[type[BaseModel], tuple[str, type[BaseModel], str]] = {
    CreateInputBooleanParams: ("input_boolean", InputBooleanRecord, "input_boolean_id"),
    CreateInputNumberParams: ("input_number", InputNumberRecord, "input_number_id"),
    CreateInputTextParams: ("input_text", InputTextRecord, "input_text_id"),
    CreateInputSelectParams: ("input_select", InputSelectRecord, "input_select_id"),
    CreateInputDatetimeParams: ("input_datetime", InputDatetimeRecord, "input_datetime_id"),
    CreateInputButtonParams: ("input_button", InputButtonRecord, "input_button_id"),
    CreateCounterParams: ("counter", CounterRecord, "counter_id"),
    CreateTimerParams: ("timer", TimerRecord, "timer_id"),
}

# Maps Update*Params type -> (domain_string, Record type, id_key_name)
UPDATE_DISPATCH: dict[type[BaseModel], tuple[str, type[BaseModel], str]] = {
    UpdateInputBooleanParams: ("input_boolean", InputBooleanRecord, "input_boolean_id"),
    UpdateInputNumberParams: ("input_number", InputNumberRecord, "input_number_id"),
    UpdateInputTextParams: ("input_text", InputTextRecord, "input_text_id"),
    UpdateInputSelectParams: ("input_select", InputSelectRecord, "input_select_id"),
    UpdateInputDatetimeParams: ("input_datetime", InputDatetimeRecord, "input_datetime_id"),
    UpdateInputButtonParams: ("input_button", InputButtonRecord, "input_button_id"),
    UpdateCounterParams: ("counter", CounterRecord, "counter_id"),
    UpdateTimerParams: ("timer", TimerRecord, "timer_id"),
}

# Maps domain string -> Record type (for list())
DOMAIN_DISPATCH: dict[str, type[BaseModel]] = {
    "input_boolean": InputBooleanRecord,
    "input_number": InputNumberRecord,
    "input_text": InputTextRecord,
    "input_select": InputSelectRecord,
    "input_datetime": InputDatetimeRecord,
    "input_button": InputButtonRecord,
    "counter": CounterRecord,
    "timer": TimerRecord,
}

# Maps domain string -> WS id key name (for update()/delete()). Uniform pattern: "{domain}_id".
ID_KEYS: dict[str, str] = {
    "input_boolean": "input_boolean_id",
    "input_number": "input_number_id",
    "input_text": "input_text_id",
    "input_select": "input_select_id",
    "input_datetime": "input_datetime_id",
    "input_button": "input_button_id",
    "counter": "counter_id",
    "timer": "timer_id",
}


class HelperClient(Resource):
    """Client for CRUD operations on Home Assistant helper entities.

    Exposes 4 generic methods (`list`, `create`, `update`, `delete`) covering all 8 helper domains
    (`input_boolean`, `input_number`, `input_text`, `input_select`, `input_datetime`,
    `input_button`, `counter`, `timer`), plus 3 counter shortcuts (`increment`, `decrement`,
    `reset`). Each CRUD method dispatches to the correct HA WebSocket command and record type via
    a lookup table, with hand-maintained `@overload` declarations providing full static typing.
    """

    _api: "Api"

    def __init__(self, hassette: "Hassette", *, api: "Api", parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._api = api

    async def on_initialize(self) -> None:
        mark_ready(self, reason="Helper client initialized")

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.logging.api

    # list dispatches on a Literal domain string

    @overload
    async def list(self, domain: Literal["input_boolean"]) -> list[InputBooleanRecord]: ...
    @overload
    async def list(self, domain: Literal["input_number"]) -> list[InputNumberRecord]: ...
    @overload
    async def list(self, domain: Literal["input_text"]) -> list[InputTextRecord]: ...
    @overload
    async def list(self, domain: Literal["input_select"]) -> list[InputSelectRecord]: ...
    @overload
    async def list(self, domain: Literal["input_datetime"]) -> list[InputDatetimeRecord]: ...
    @overload
    async def list(self, domain: Literal["input_button"]) -> list[InputButtonRecord]: ...
    @overload
    async def list(self, domain: Literal["counter"]) -> list[CounterRecord]: ...
    @overload
    async def list(self, domain: Literal["timer"]) -> list[TimerRecord]: ...

    async def list(self, domain: HelperDomain) -> list[Any]:
        """List all stored helpers for a given domain.

        Args:
            domain: The helper domain to list (e.g. "input_boolean", "counter").

        Returns:
            List of domain-specific Record instances representing stored configs.
        """
        record_type = DOMAIN_DISPATCH[domain]
        val = await _ws_helper_call(self._api, domain, "list")
        items = _expect_list(val, f"{domain}/list")
        self.logger.debug("Listed %d %s helpers", len(items), domain)
        return [record_type.model_validate(item) for item in items]

    # create dispatches on type(params)

    @overload
    async def create(self, params: CreateInputBooleanParams) -> InputBooleanRecord: ...
    @overload
    async def create(self, params: CreateInputNumberParams) -> InputNumberRecord: ...
    @overload
    async def create(self, params: CreateInputTextParams) -> InputTextRecord: ...
    @overload
    async def create(self, params: CreateInputSelectParams) -> InputSelectRecord: ...
    @overload
    async def create(self, params: CreateInputDatetimeParams) -> InputDatetimeRecord: ...
    @overload
    async def create(self, params: CreateInputButtonParams) -> InputButtonRecord: ...
    @overload
    async def create(self, params: CreateCounterParams) -> CounterRecord: ...
    @overload
    async def create(self, params: CreateTimerParams) -> TimerRecord: ...

    async def create(self, params: BaseModel) -> BaseModel:
        """Create a new helper.

        Args:
            params: Parameters for the new helper. The concrete type determines the domain
                and the return type via overload resolution.

        Returns:
            The stored record returned by Home Assistant.
        """
        domain, record_type, _id_key = CREATE_DISPATCH[type(params)]
        val = await _ws_helper_call(self._api, domain, "create", **params.model_dump(exclude_unset=True))
        record = record_type.model_validate(_expect_dict(val, f"{domain}/create"))
        self.logger.info("Created %s helper %r", domain, record.id)  # pyright: ignore[reportAttributeAccessIssue]
        return record

    # update dispatches on type(params)

    @overload
    async def update(self, helper_id: str, params: UpdateInputBooleanParams) -> InputBooleanRecord: ...
    @overload
    async def update(self, helper_id: str, params: UpdateInputNumberParams) -> InputNumberRecord: ...
    @overload
    async def update(self, helper_id: str, params: UpdateInputTextParams) -> InputTextRecord: ...
    @overload
    async def update(self, helper_id: str, params: UpdateInputSelectParams) -> InputSelectRecord: ...
    @overload
    async def update(self, helper_id: str, params: UpdateInputDatetimeParams) -> InputDatetimeRecord: ...
    @overload
    async def update(self, helper_id: str, params: UpdateInputButtonParams) -> InputButtonRecord: ...
    @overload
    async def update(self, helper_id: str, params: UpdateCounterParams) -> CounterRecord: ...
    @overload
    async def update(self, helper_id: str, params: UpdateTimerParams) -> TimerRecord: ...

    async def update(self, helper_id: str, params: BaseModel) -> BaseModel:
        """Update an existing helper.

        Args:
            helper_id: The ID of the helper to update.
            params: Fields to update (unset fields are left unchanged). The concrete type
                determines the domain and the return type via overload resolution.

        Returns:
            The updated stored record.
        """
        domain, record_type, id_key = UPDATE_DISPATCH[type(params)]
        val = await _ws_helper_call(
            self._api, domain, "update", **{id_key: helper_id}, **params.model_dump(exclude_unset=True)
        )
        record = record_type.model_validate(_expect_dict(val, f"{domain}/update"))
        self.logger.debug("Updated %s helper %r", domain, helper_id)
        return record

    # delete dispatches on a Literal domain string

    @overload
    async def delete(self, domain: Literal["input_boolean"], helper_id: str) -> None: ...
    @overload
    async def delete(self, domain: Literal["input_number"], helper_id: str) -> None: ...
    @overload
    async def delete(self, domain: Literal["input_text"], helper_id: str) -> None: ...
    @overload
    async def delete(self, domain: Literal["input_select"], helper_id: str) -> None: ...
    @overload
    async def delete(self, domain: Literal["input_datetime"], helper_id: str) -> None: ...
    @overload
    async def delete(self, domain: Literal["input_button"], helper_id: str) -> None: ...
    @overload
    async def delete(self, domain: Literal["counter"], helper_id: str) -> None: ...
    @overload
    async def delete(self, domain: Literal["timer"], helper_id: str) -> None: ...

    async def delete(self, domain: HelperDomain, helper_id: str) -> None:
        """Delete a helper.

        Args:
            domain: The helper domain (e.g. "input_boolean", "counter").
            helper_id: The ID of the helper to delete.
        """
        id_key = ID_KEYS[domain]
        await _ws_helper_call(self._api, domain, "delete", **{id_key: helper_id})
        self.logger.debug("Deleted %s helper %r", domain, helper_id)

    # counter shortcuts
    # Counter service-call shortcuts (operate on live entity state, not stored
    # config). Use update() to change the stored initial/minimum/maximum.
    #
    # timer.start / timer.pause / timer.cancel are deliberately excluded: timer
    # service actions are one-off calls that benefit from the full call_service()
    # signature. Counter actions get wrappers because the pattern "increment on
    # every event" is common enough to warrant a two-word call site.

    async def increment(self, entity_id: str) -> None:
        """Increment a counter entity's current value (live state, not stored config).

        Args:
            entity_id: The entity ID of the counter (e.g. ``"counter.motion_count"``).
        """
        await self._api.call_service(
            "counter",
            "increment",
            target={"entity_id": entity_id},
            return_response=True,  # surfaces HA errors instead of fire-and-forget
        )
        self.logger.debug("Incremented counter %r", entity_id)

    async def decrement(self, entity_id: str) -> None:
        """Decrement a counter entity's current value (live state, not stored config).

        Args:
            entity_id: The entity ID of the counter (e.g. ``"counter.motion_count"``).
        """
        await self._api.call_service(
            "counter",
            "decrement",
            target={"entity_id": entity_id},
            return_response=True,
        )
        self.logger.debug("Decremented counter %r", entity_id)

    async def reset(self, entity_id: str) -> None:
        """Reset a counter entity's value to its configured initial (live state, not stored config).

        Args:
            entity_id: The entity ID of the counter (e.g. ``"counter.motion_count"``).
        """
        await self._api.call_service(
            "counter",
            "reset",
            target={"entity_id": entity_id},
            return_response=True,
        )
        self.logger.debug("Reset counter %r", entity_id)
