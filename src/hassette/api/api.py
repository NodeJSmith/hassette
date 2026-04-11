"""
API interface for interacting with Home Assistant's REST and WebSocket APIs.

The Api provides both async and sync methods for all Home Assistant interactions including
state management, service calls, event firing, and data retrieval. Automatically handles
authentication, retries, and type conversion for a seamless developer experience.

Examples:
    Getting entity states

    ```python
    # Get all states (typed)
    states = await self.api.get_states()

    # Get specific entity state with type hint
    light_state: states.LightState = await self.api.get_state("light.kitchen")
    brightness = light_state.attributes.brightness

    # Get raw state data
    raw_state = await self.api.get_state_raw("sensor.temperature")
    ```

    Calling services

    ```python
    # Basic service call
    await self.api.call_service("light", "turn_on", entity_id="light.kitchen")

    # Service call with data
    await self.api.call_service(
        "light",
        "turn_on",
        entity_id="light.living_room",
        brightness=200,
        color_name="blue"
    )

    # Using target parameter for multiple entities
    await self.api.call_service(
        "light",
        "turn_off",
        target={"entity_id": ["light.kitchen", "light.living_room"]}
    )
    ```

    Convenience methods

    ```python
    # Turn entities on/off
    await self.api.turn_on("light.kitchen", brightness=150)
    await self.api.turn_off("light.living_room")
    await self.api.toggle_service("switch.fan")
    ```

    Setting states

    ```python
    # Set entity state with attributes
    await self.api.set_state("sensor.custom", "active", {"last_update": "now"})

    # Set state with updated attributes
    await self.api.set_state("sensor.custom", "active", {"battery": 85})
    ```

    Firing custom events

    ```python
    # Simple event
    await self.api.fire_event("custom_event", {"message": "Hello"})

    # Complex event data
    await self.api.fire_event(
        "automation_triggered",
        {
            "automation": "morning_routine",
            "trigger": "time",
            "timestamp": self.now().format_iso()
        }
    )
    ```

    Template rendering

    ```python
    # Render Jinja2 templates
    result = await self.api.render_template("{{ states('sensor.temperature') }}")

    # Complex template with context
    template = "{% if states('light.kitchen') == 'on' %}on{% else %}off{% endif %}"
    status = await self.api.render_template(template)
    ```

    History and logbook data

    ```python
    from datetime import datetime, timedelta

    # Get entity history
    end_time = self.now()
    start_time = end_time.subtract(hours=24)

    history = await self.api.get_history(
        entity_ids=["sensor.temperature"],
        start_time=start_time,
        end_time=end_time
    )

    # Get logbook entries
    logbook = await self.api.get_logbook(
        start_time=start_time,
        entity_id="light.kitchen"
    )
    ```

    Using the sync facade

    ```python
    # For sync apps or when async is not available
    states = self.api.sync.get_states()
    self.api.sync.call_service("light", "turn_on", entity_id="light.kitchen")
    ```

    WebSocket direct access

    ```python
    # Send WebSocket message and wait for response
    result = await self.api.ws_send_and_wait(
        type="config/device_registry/list"
    )

    # Send WebSocket message without waiting
    await self.api.ws_send_json(
        type="subscribe_events",
        event_type="state_changed"
    )
    ```

    Handling missing entities

    ```python
    from hassette.exceptions import EntityNotFoundError
    from hassette import states

    try:
        state: states.LightState = await self.api.get_state("light.missing_light")
    except EntityNotFoundError:
        self.logger.warning("Entity not found")

    # or

    state: states.LightState | None = await self.api.get_state_or_none("light.missing_light")
    if state is None:
        self.logger.warning("Entity not found")
    ```

"""

import typing
from collections.abc import Generator
from contextlib import suppress
from enum import StrEnum
from typing import Any, Literal, overload

import aiohttp
from whenever import Date, PlainDateTime, ZonedDateTime

from hassette.const.misc import FalseySentinel
from hassette.event_handling.accessors import get_path
from hassette.exceptions import EntityNotFoundError, FailedMessageError, UnableToConvertStateError
from hassette.models.entities import BaseEntity
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
from hassette.models.history import HistoryEntry
from hassette.models.services import ServiceResponse
from hassette.resources.base import Resource
from hassette.types.types import LOG_LEVEL_TYPE

from .sync import ApiSyncFacade

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.api_resource import ApiResource
    from hassette.events import HassStateDict
    from hassette.models.entities import EntityT
    from hassette.models.states import BaseState


# ---------------------------------------------------------------------------
# Module-level helpers — placed BEFORE the Api class so the sync facade
# generator does NOT emit them as public sync methods on ApiSyncFacade.
# ---------------------------------------------------------------------------


def _expect_list(val: Any, context: str) -> list:
    """Assert that *val* is a list, raising TypeError with context if not.

    Uses TypeError instead of AssertionError so callers can catch it
    meaningfully, and so it survives ``python -O`` (which strips ``assert``).
    """
    if not isinstance(val, list):
        raise TypeError(f"Expected list from {context}, got {type(val).__name__}: {val!r}")
    return val


def _expect_dict(val: Any, context: str) -> dict:
    """Assert that *val* is a dict, raising TypeError with context if not."""
    if not isinstance(val, dict):
        raise TypeError(f"Expected dict from {context}, got {type(val).__name__}: {val!r}")
    return val


async def _ws_helper_call(api: "Api", domain: str, operation: str, **data: Any) -> Any:
    """Call ws_send_and_wait with domain/operation context on failure.

    Preserves ``code`` and ``original_data`` from the original FailedMessageError
    so callers can inspect them via ``except FailedMessageError as e: e.code``.
    Chains through ``raise ... from e`` so the original traceback is retained.

    Note: a WebSocket disconnect during the call raises
    ``RetryableConnectionClosedError``, which propagates through this wrapper
    unwrapped. Callers that need uniform exception handling should catch both
    ``FailedMessageError`` and ``RetryableConnectionClosedError``.
    """
    try:
        return await api.ws_send_and_wait(type=f"{domain}/{operation}", **data)
    except FailedMessageError as e:
        # Include only field names in the error message — values may contain
        # sensitive data (e.g., `input_text.initial` on a password-mode helper)
        # that would leak into application logs. Full payload is preserved on
        # `original_data` for debugging contexts that need it.
        field_names = sorted(data.keys())
        raise FailedMessageError(
            f"{domain}/{operation} failed (fields: {field_names}): {e}",
            code=e.code,
            original_data=e.original_data,
        ) from e


class Api(Resource):
    """API service for interacting with Home Assistant.

    This service provides methods to interact with the Home Assistant API, including making REST requests,
    managing WebSocket connections, and handling entity states.
    """

    sync: ApiSyncFacade
    """Synchronous facade for the API service."""

    _api_service: "ApiResource"
    """Internal API service instance."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._api_service = self.hassette._api_service
        self.sync = self.add_child(ApiSyncFacade, api=self)

    async def on_initialize(self) -> None:
        self.mark_ready(reason="API initialized")

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.api_log_level

    async def ws_send_and_wait(self, **data: Any) -> Any:
        """Send a WebSocket message and wait for a response."""
        return await self._api_service._ws_conn.send_and_wait(**data)

    async def ws_send_json(self, **data: Any) -> None:
        """Send a WebSocket message without waiting for a response."""
        await self._api_service._ws_conn.send_json(**data)

    async def rest_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        suppress_error_message: bool = False,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        """Make a REST request to the Home Assistant API.

        Args:
            method: The HTTP method to use (e.g., "GET", "POST").
            url: The URL endpoint for the request.
            params: Query parameters for the request.
            data: JSON payload for the request.
            suppress_error_message: Whether to suppress error messages.

        Returns:
            The response from the API.
        """
        return await self._api_service._rest_request(
            method, url, params=params, data=data, suppress_error_message=suppress_error_message, **kwargs
        )

    async def get_rest_request(
        self, url: str, params: dict[str, Any] | None = None, **kwargs
    ) -> aiohttp.ClientResponse:
        """Make a GET request to the Home Assistant API.

        Args:
            url: The URL endpoint for the request.
            params: Query parameters for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            The response from the API.
        """
        return await self.rest_request("GET", url, params=params, **kwargs)

    async def post_rest_request(self, url: str, data: dict[str, Any] | None = None, **kwargs) -> aiohttp.ClientResponse:
        """Make a POST request to the Home Assistant API.

        Args:
            url: The URL endpoint for the request.
            data: JSON payload for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            The response from the API.
        """
        return await self.rest_request("POST", url, data=data, **kwargs)

    async def delete_rest_request(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make a DELETE request to the Home Assistant API.

        Args:
            url: The URL endpoint for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            The response from the API.
        """
        return await self.rest_request("DELETE", url, **kwargs)

    async def get_states_raw(self) -> list["HassStateDict"]:
        """Get all entities in Home Assistant as raw dictionaries.

        Returns:
            A list of states as dictionaries.
        """
        val: list[HassStateDict] = await self.ws_send_and_wait(type="get_states")  # pyright: ignore[reportAssignmentType]
        assert isinstance(val, list), "Expected a list of states"
        return val

    async def get_states(self) -> list["BaseState"]:
        """Get all entities in Home Assistant, converted to their appropriate state types.

        If a state fails to convert, it is skipped with an error logged. If there is no registered
        state class for a domain, the generic BaseState is used.

        Returns:
            A list of states, converted to their appropriate state types.
        """
        val = await self.get_states_raw()

        self.logger.debug("Converting states to specific state types")
        converted: list[BaseState] = []

        for raw_state in val:
            # the conversion method will handle logging any conversion errors
            with suppress(UnableToConvertStateError):
                state = self.hassette.state_registry.try_convert_state(raw_state)
                converted.append(state)

        return converted

    async def get_states_iterator(self) -> Generator["BaseState[Any]", Any, None]:
        """Get a generator to iterate over all entities in Home Assistant, converted to their appropriate state types.

        The returned generator yields properly typed state objects based on their domains. If
        a state fails to convert, it is skipped with an error logged. If there is no registered
        state class for a domain, the generic BaseState is used.

        Returns:
            A generator yielding typed state objects.
        """

        raw_states = await self.get_states_raw()

        def yield_states():
            nonlocal raw_states

            for state_data in raw_states:
                # the conversion method will handle logging any conversion errors
                with suppress(UnableToConvertStateError):
                    yield self.hassette.state_registry.try_convert_state(state_data)

        return yield_states()

    async def get_config(self) -> dict[str, Any]:
        """Get the Home Assistant configuration.

        Returns:
            The configuration data.
        """
        val = await self.ws_send_and_wait(type="get_config")
        assert isinstance(val, dict), "Expected a dictionary of configuration data"
        return val

    async def get_services(self) -> dict[str, Any]:
        """Get the available services in Home Assistant.

        Returns:
            The services data.
        """
        val = await self.ws_send_and_wait(type="get_services")
        assert isinstance(val, dict), "Expected a dictionary of services"
        return val

    async def get_panels(self) -> dict[str, Any]:
        """Get the available panels in Home Assistant.

        Returns:
            The panels data.
        """
        val = await self.ws_send_and_wait(type="get_panels")
        assert isinstance(val, dict), "Expected a dictionary of panels"
        return val

    async def fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fire a custom event in Home Assistant.

        Args:
            event_type: The type of the event to fire (e.g., "custom_event").
            event_data: Additional data to include with the event.

        Returns:
            The response from Home Assistant.
        """
        event_data = event_data or {}

        data = {"type": "fire_event", "event_type": event_type, "event_data": event_data}
        if not event_data:
            data.pop("event_data")

        return await self.ws_send_and_wait(**data)

    @overload
    async def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None,
        return_response: Literal[True],
        **data,
    ) -> ServiceResponse: ...

    @overload
    async def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: typing.Literal[False] | None = None,
        **data,
    ) -> None: ...

    async def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: bool | None = False,
        **data,
    ) -> ServiceResponse | None:
        """Call a Home Assistant service.

        Args:
            domain: The domain of the service (e.g., "light").
            service: The name of the service to call (e.g., "turn_on").
            target: Target entity IDs or areas.
            return_response: Whether to return the response from Home Assistant. Defaults to False.
            **data: Additional data to send with the service call.

        Returns:
            ServiceResponse | None: The response from Home Assistant if return_response is True. Otherwise None.
        """
        payload = {
            "type": "call_service",
            "domain": domain,
            "service": service,
            "target": target,
            "return_response": return_response,
        }

        payload = {k: v for k, v in payload.items() if v is not None}
        data = {k: v for k, v in data.items() if v is not None}

        if data:
            self.logger.debug("Adding extra data to service call: %s", data)
            payload["service_data"] = data

        if return_response:
            resp = await self.ws_send_and_wait(**payload)
            return ServiceResponse(**resp)

        await self.ws_send_json(**payload)
        return None

    async def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data) -> None:
        """Turn on a specific entity in Home Assistant.

        Args:
            entity_id: The ID of the entity to turn on (e.g., "light.office").
            domain: The domain of the entity (default: "homeassistant").

        """
        entity_id = str(entity_id)

        self.logger.debug("Turning on entity %s", entity_id)
        return await self.call_service(domain=domain, service="turn_on", target={"entity_id": entity_id}, **data)

    async def turn_off(self, entity_id: str | StrEnum, domain: str = "homeassistant"):
        """Turn off a specific entity in Home Assistant.

        Args:
            entity_id: The ID of the entity to turn off (e.g., "light.office").
            domain: The domain of the entity (default: "homeassistant").

        """
        entity_id = str(entity_id)
        self.logger.debug("Turning off entity %s", entity_id)
        return await self.call_service(domain=domain, service="turn_off", target={"entity_id": entity_id})

    async def toggle_service(self, entity_id: str | StrEnum, domain: str = "homeassistant"):
        """Toggle a specific entity in Home Assistant.

        Args:
            entity_id: The ID of the entity to toggle (e.g., "light.office").
            domain: The domain of the entity (default: "homeassistant").

        """
        entity_id = str(entity_id)
        self.logger.debug("Toggling entity %s", entity_id)
        return await self.call_service(domain=domain, service="toggle", target={"entity_id": entity_id})

    async def get_state_raw(self, entity_id: str) -> "HassStateDict":
        """Get the state of a specific entity.

        Args:
            entity_id: The ID of the entity to get the state for.

        Returns:
            The state of the entity as raw data.
        """

        url = f"states/{entity_id}"
        response = await self.get_rest_request(url)
        return await response.json()

    async def entity_exists(self, entity_id: str) -> bool:
        """Check if a specific entity exists.

        Args:
            entity_id: The ID of the entity to check.

        Returns:
            True if the entity exists, False otherwise.
        """

        try:
            url = f"states/{entity_id}"
            response = await self.rest_request("GET", url, suppress_error_message=True)
            await response.json()
            return True
        except EntityNotFoundError:
            return False

    async def get_entity(self, entity_id: str, model: type["EntityT"]) -> "EntityT":
        """Get an entity object for a specific entity.

        Args:
            entity_id: The ID of the entity to get.
            model: The model class to use for the entity.

        Returns:
            The entity object.
        """
        if not issubclass(model, BaseEntity):  # runtime check
            raise TypeError(f"Model {model!r} is not a valid BaseEntity subclass")

        raw = await self.get_state_raw(entity_id)

        return model.model_validate({"state": raw})

    async def get_entity_or_none(self, entity_id: str, model: type["EntityT"]) -> "EntityT | None":
        """Get an entity object for a specific entity, or None if it does not exist.

        Args:
            entity_id: The ID of the entity to get.
            model: The model class to use for the entity.

        Returns:
            The entity object, or None if it does not exist.
        """
        try:
            return await self.get_entity(entity_id, model)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise

    async def get_state(self, entity_id: str) -> "BaseState":
        """Get the state of a specific entity.

        Args:
            entity_id: The ID of the entity to get the state for.

        Returns:
            The state of the entity converted to the specified model type.
        """

        raw = await self.get_state_raw(entity_id)
        return self.hassette.state_registry.try_convert_state(raw, entity_id)

    async def get_state_or_none(self, entity_id: str) -> "BaseState | None":
        """Get the state of a specific entity, or None if it does not exist.

        Args:
            entity_id: The ID of the entity to get the state for.

        Returns:
            The state of the entity converted to the specified model type, or None if it does not exist.
        """
        try:
            return await self.get_state(entity_id)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise

    async def get_state_value(self, entity_id: str) -> Any:
        """Get the state of a specific entity without converting it to a state object.

        Args:
            entity_id: The ID of the entity to get the state for.

        Returns:
            The state of the entity as raw data.

        Note:
            While most default methods in this library work with state objects for
            strong typing, this method is designed to return the raw state value,
            as it is likely overkill to convert it to a state object for simple state value retrieval.
        """

        entity = await self.get_state_raw(entity_id)
        state = entity.get("state")
        return state

    async def get_state_value_typed(self, entity_id: str) -> "Any":
        """Get the value of a specific entity's state, converted to the correct type for that state.

        The return type here is Any due to the dynamic nature of this conversion, but the return type
        at runtime will match the expected value type for the specific state class of the entity.

        Args:
            entity_id: The ID of the entity to get the state for.

        Returns:
            The state of the entity converted to the specified model type.

        Raises:
            TypeError: If the model is not a valid StateType subclass.

        Example:
            ```python
            date: ZonedDateTime = await self.api.get_state_value_typed("input_datetime.test")
            ```

        Warning:
            For states like `SensorState` the value type in Hassette is `str`, even if the sensor represents a number,
            as we cannot be sure of the actual type without additional context. For these cases, you are responsible
            for converting the string to the desired type.
        """
        state_raw = await self.get_state_raw(entity_id)
        state = state_raw.get("state")

        model = self.hassette.state_registry.resolve(domain=entity_id.split(".")[0])
        if not model:
            return state
        return self.hassette.type_registry.convert(state, model.value_type)

    async def get_attribute(self, entity_id: str, attribute: str) -> Any | FalseySentinel:
        """Get a specific attribute of an entity.

        Args:
            entity_id: The ID of the entity to get the attribute for.
            attribute: The name of the attribute to retrieve. Can be a dot-separated path for nested attributes.

        Returns:
            The value of the specified attribute, or MISSING_VALUE sentinel if the attribute does not exist.
        """

        entity = await self.get_state(entity_id)
        return get_path(attribute)(entity.attributes)

    async def get_history(
        self,
        entity_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> list[HistoryEntry]:
        """Get the history of a specific entity.

        Args:
            entity_id: The ID of the entity to get the history for.
            start_time: The start time for the history range.
            end_time: The end time for the history range.
            significant_changes_only: Whether to only include significant changes.
            minimal_response: Whether to request a minimal response.
            no_attributes: Whether to exclude attributes from the response.

        Returns:
            A list of history entries for the specified entity.
        """
        if "," in entity_id:
            raise ValueError("Entity ID should not contain commas. Use `get_histories` for multiple entities.")

        entries = await self._api_service._get_history_raw(
            entity_id=entity_id,
            start_time=start_time,
            end_time=end_time,
            significant_changes_only=significant_changes_only,
            minimal_response=minimal_response,
            no_attributes=no_attributes,
        )

        if not entries:
            return []

        assert len(entries) == 1, "Expected a single list of history entries"

        converted = [HistoryEntry.model_validate(entry) for entry in entries[0]]

        return converted

    async def get_histories(
        self,
        entity_ids: list[str],
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> dict[str, list[HistoryEntry]]:
        """Get the history for multiple entities.

        Args:
            entity_ids: The IDs of the entities to get the history for.
            start_time: The start time for the history range.
            end_time: The end time for the history range.
            significant_changes_only: Whether to only include significant changes.
            minimal_response: Whether to request a minimal response.
            no_attributes: Whether to exclude attributes from the response.

        Returns:
            A dictionary mapping entity IDs to their respective history entries.
        """
        entity_id = ",".join(entity_ids)

        entries = await self._api_service._get_history_raw(
            entity_id=entity_id,
            start_time=start_time,
            end_time=end_time,
            significant_changes_only=significant_changes_only,
            minimal_response=minimal_response,
            no_attributes=no_attributes,
        )

        if not entries:
            return {}

        converted = {}
        for history_list in entries:
            converted[history_list[0]["entity_id"]] = [HistoryEntry.model_validate(entry) for entry in history_list]

        return converted

    async def get_logbook(
        self,
        entity_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str,
    ) -> list[dict]:
        """Get the logbook entries for a specific entity.

        Args:
            entity_id: The ID of the entity to get the logbook entries for.
            start_time: The start time for the logbook range.
            end_time: The end time for the logbook range.

        Returns:
            A list of logbook entries for the specified entity.
        """

        url = f"logbook/{start_time}"
        params = {"entity": entity_id, "end_time": end_time}

        response = await self.get_rest_request(url, params=params)

        return await response.json()

    async def set_state(
        self,
        entity_id: str | StrEnum,
        state: Any,
        attributes: dict[str, Any] | None = None,
    ) -> dict:
        """Set the state of a specific entity.

        Args:
            entity_id: The ID of the entity to set the state for.
            state: The new state value to set.
            attributes: Additional attributes to set for the entity.

        Returns:
            The response from Home Assistant after setting the state.
        """

        entity_id = str(entity_id)

        attributes = attributes or {}
        curr_attributes = {}

        if await self.entity_exists(entity_id):
            curr_attributes = (await self.get_state_raw(entity_id)).get("attributes", {}) or {}

        # Merge current attributes with new attributes
        new_attributes = curr_attributes | attributes

        url = f"states/{entity_id}"
        data = {"state": state, "attributes": new_attributes}

        response = await self.post_rest_request(url, data=data)
        return await response.json()

    async def get_camera_image(
        self,
        entity_id: str,
        timestamp: PlainDateTime | ZonedDateTime | Date | str | None = None,
    ) -> bytes:
        """Get the latest camera image for a specific entity.

        Args:
            entity_id: The ID of the camera entity to get the image for.
            timestamp: The timestamp for the image. If None, the latest image is returned.

        Returns:
            The camera image data.
        """

        url = f"camera_proxy/{entity_id}"
        params = {}
        if timestamp:
            params["timestamp"] = timestamp

        response = await self.get_rest_request(url, params=params)

        return await response.read()

    async def get_calendars(self) -> list[dict]:
        """Get the list of calendars."""

        url = "calendars"
        response = await self.get_rest_request(url)
        return await response.json()

    async def get_calendar_events(
        self,
        calendar_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str,
    ) -> list[dict]:
        """Get events from a specific calendar.

        Args:
            calendar_id: The ID of the calendar to get events from.
            start_time: The start time for the event range.
            end_time: The end time for the event range.

        Returns:
            A list of calendar events.
        """

        url = f"calendars/{calendar_id}/events"
        params = {"start": start_time, "end": end_time}

        response = await self.get_rest_request(url, params=params)
        return await response.json()

    async def render_template(
        self,
        template: str,
        variables: dict | None = None,
    ) -> str:
        """Render a template with given variables.

        Args:
            template: The template string to render.
            variables: Variables to use in the template.

        Returns:
            The rendered template result.
        """

        url = "template"
        data = {"template": template, "variables": variables or {}}

        response = await self.post_rest_request(url, data=data)
        return await response.text()

    async def delete_entity(self, entity_id: str) -> None:
        """Delete a specific entity.

        Args:
            entity_id: The ID of the entity to delete.

        Raises:
            RuntimeError: If the deletion fails.
        """

        url = f"states/{entity_id}"

        response = await self.rest_request("DELETE", url)

        if response.status != 204:
            raise RuntimeError(f"Failed to delete entity {entity_id}: {response.status} - {response.reason}")

    # ---------------------------------------------------------------------------
    # Helper CRUD methods — persistent stored-config management via HA WebSocket.
    # All 32 methods use _ws_helper_call for consistent error context.
    # Command pattern: {domain}/{list|create|update|delete}
    # ID key pattern:  {domain}_id  (uniform across all 8 domains — see design.md
    #                  § HA WebSocket Commands / Shared infrastructure)
    # ---------------------------------------------------------------------------

    # --- input_boolean ---

    async def list_input_booleans(self) -> list[InputBooleanRecord]:
        """List all stored input_boolean helpers.

        Returns:
            List of InputBooleanRecord instances representing stored configs.
        """
        val = await _ws_helper_call(self, "input_boolean", "list")
        items = _expect_list(val, "input_boolean/list")
        self.logger.debug("Listed %d input_boolean helpers", len(items))
        return [InputBooleanRecord.model_validate(item) for item in items]

    async def create_input_boolean(self, params: CreateInputBooleanParams) -> InputBooleanRecord:
        """Create a new input_boolean helper.

        Args:
            params: Parameters for the new helper.

        Returns:
            The stored record returned by Home Assistant.
        """
        val = await _ws_helper_call(self, "input_boolean", "create", **params.model_dump(exclude_unset=True))
        record = InputBooleanRecord.model_validate(_expect_dict(val, "input_boolean/create"))
        self.logger.info("Created input_boolean helper %r", record.id)
        return record

    async def update_input_boolean(self, helper_id: str, params: UpdateInputBooleanParams) -> InputBooleanRecord:
        """Update an existing input_boolean helper.

        Args:
            helper_id: The ID of the helper to update.
            params: Fields to update (unset fields are left unchanged).

        Returns:
            The updated stored record.
        """
        val = await _ws_helper_call(
            self,
            "input_boolean",
            "update",
            input_boolean_id=helper_id,
            **params.model_dump(exclude_unset=True),
        )
        record = InputBooleanRecord.model_validate(_expect_dict(val, "input_boolean/update"))
        self.logger.debug("Updated input_boolean helper %r", helper_id)
        return record

    async def delete_input_boolean(self, helper_id: str) -> None:
        """Delete an input_boolean helper.

        Args:
            helper_id: The ID of the helper to delete.
        """
        await _ws_helper_call(self, "input_boolean", "delete", input_boolean_id=helper_id)
        self.logger.debug("Deleted input_boolean helper %r", helper_id)

    # --- input_number ---

    async def list_input_numbers(self) -> list[InputNumberRecord]:
        """List all stored input_number helpers.

        Returns:
            List of InputNumberRecord instances representing stored configs.
        """
        val = await _ws_helper_call(self, "input_number", "list")
        items = _expect_list(val, "input_number/list")
        self.logger.debug("Listed %d input_number helpers", len(items))
        return [InputNumberRecord.model_validate(item) for item in items]

    async def create_input_number(self, params: CreateInputNumberParams) -> InputNumberRecord:
        """Create a new input_number helper.

        Args:
            params: Parameters for the new helper.

        Returns:
            The stored record returned by Home Assistant.
        """
        val = await _ws_helper_call(self, "input_number", "create", **params.model_dump(exclude_unset=True))
        record = InputNumberRecord.model_validate(_expect_dict(val, "input_number/create"))
        self.logger.info("Created input_number helper %r", record.id)
        return record

    async def update_input_number(self, helper_id: str, params: UpdateInputNumberParams) -> InputNumberRecord:
        """Update an existing input_number helper.

        Args:
            helper_id: The ID of the helper to update.
            params: Fields to update (unset fields are left unchanged).

        Returns:
            The updated stored record.
        """
        val = await _ws_helper_call(
            self,
            "input_number",
            "update",
            input_number_id=helper_id,
            **params.model_dump(exclude_unset=True),
        )
        record = InputNumberRecord.model_validate(_expect_dict(val, "input_number/update"))
        self.logger.debug("Updated input_number helper %r", helper_id)
        return record

    async def delete_input_number(self, helper_id: str) -> None:
        """Delete an input_number helper.

        Args:
            helper_id: The ID of the helper to delete.
        """
        await _ws_helper_call(self, "input_number", "delete", input_number_id=helper_id)
        self.logger.debug("Deleted input_number helper %r", helper_id)

    # --- input_text ---

    async def list_input_texts(self) -> list[InputTextRecord]:
        """List all stored input_text helpers.

        Returns:
            List of InputTextRecord instances representing stored configs.
        """
        val = await _ws_helper_call(self, "input_text", "list")
        items = _expect_list(val, "input_text/list")
        self.logger.debug("Listed %d input_text helpers", len(items))
        return [InputTextRecord.model_validate(item) for item in items]

    async def create_input_text(self, params: CreateInputTextParams) -> InputTextRecord:
        """Create a new input_text helper.

        Args:
            params: Parameters for the new helper.

        Returns:
            The stored record returned by Home Assistant.
        """
        val = await _ws_helper_call(self, "input_text", "create", **params.model_dump(exclude_unset=True))
        record = InputTextRecord.model_validate(_expect_dict(val, "input_text/create"))
        self.logger.info("Created input_text helper %r", record.id)
        return record

    async def update_input_text(self, helper_id: str, params: UpdateInputTextParams) -> InputTextRecord:
        """Update an existing input_text helper.

        Args:
            helper_id: The ID of the helper to update.
            params: Fields to update (unset fields are left unchanged).

        Returns:
            The updated stored record.
        """
        val = await _ws_helper_call(
            self,
            "input_text",
            "update",
            input_text_id=helper_id,
            **params.model_dump(exclude_unset=True),
        )
        record = InputTextRecord.model_validate(_expect_dict(val, "input_text/update"))
        self.logger.debug("Updated input_text helper %r", helper_id)
        return record

    async def delete_input_text(self, helper_id: str) -> None:
        """Delete an input_text helper.

        Args:
            helper_id: The ID of the helper to delete.
        """
        await _ws_helper_call(self, "input_text", "delete", input_text_id=helper_id)
        self.logger.debug("Deleted input_text helper %r", helper_id)

    # --- input_select ---

    async def list_input_selects(self) -> list[InputSelectRecord]:
        """List all stored input_select helpers.

        Returns:
            List of InputSelectRecord instances representing stored configs.
        """
        val = await _ws_helper_call(self, "input_select", "list")
        items = _expect_list(val, "input_select/list")
        self.logger.debug("Listed %d input_select helpers", len(items))
        return [InputSelectRecord.model_validate(item) for item in items]

    async def create_input_select(self, params: CreateInputSelectParams) -> InputSelectRecord:
        """Create a new input_select helper.

        Args:
            params: Parameters for the new helper.

        Returns:
            The stored record returned by Home Assistant.
        """
        val = await _ws_helper_call(self, "input_select", "create", **params.model_dump(exclude_unset=True))
        record = InputSelectRecord.model_validate(_expect_dict(val, "input_select/create"))
        self.logger.info("Created input_select helper %r", record.id)
        return record

    async def update_input_select(self, helper_id: str, params: UpdateInputSelectParams) -> InputSelectRecord:
        """Update an existing input_select helper.

        Args:
            helper_id: The ID of the helper to update.
            params: Fields to update (unset fields are left unchanged).

        Returns:
            The updated stored record.
        """
        val = await _ws_helper_call(
            self,
            "input_select",
            "update",
            input_select_id=helper_id,
            **params.model_dump(exclude_unset=True),
        )
        record = InputSelectRecord.model_validate(_expect_dict(val, "input_select/update"))
        self.logger.debug("Updated input_select helper %r", helper_id)
        return record

    async def delete_input_select(self, helper_id: str) -> None:
        """Delete an input_select helper.

        Args:
            helper_id: The ID of the helper to delete.
        """
        await _ws_helper_call(self, "input_select", "delete", input_select_id=helper_id)
        self.logger.debug("Deleted input_select helper %r", helper_id)

    # --- input_datetime ---

    async def list_input_datetimes(self) -> list[InputDatetimeRecord]:
        """List all stored input_datetime helpers.

        Returns:
            List of InputDatetimeRecord instances representing stored configs.
        """
        val = await _ws_helper_call(self, "input_datetime", "list")
        items = _expect_list(val, "input_datetime/list")
        self.logger.debug("Listed %d input_datetime helpers", len(items))
        return [InputDatetimeRecord.model_validate(item) for item in items]

    async def create_input_datetime(self, params: CreateInputDatetimeParams) -> InputDatetimeRecord:
        """Create a new input_datetime helper.

        Args:
            params: Parameters for the new helper.

        Returns:
            The stored record returned by Home Assistant.
        """
        val = await _ws_helper_call(self, "input_datetime", "create", **params.model_dump(exclude_unset=True))
        record = InputDatetimeRecord.model_validate(_expect_dict(val, "input_datetime/create"))
        self.logger.info("Created input_datetime helper %r", record.id)
        return record

    async def update_input_datetime(self, helper_id: str, params: UpdateInputDatetimeParams) -> InputDatetimeRecord:
        """Update an existing input_datetime helper.

        Args:
            helper_id: The ID of the helper to update.
            params: Fields to update (unset fields are left unchanged).

        Returns:
            The updated stored record.
        """
        val = await _ws_helper_call(
            self,
            "input_datetime",
            "update",
            input_datetime_id=helper_id,
            **params.model_dump(exclude_unset=True),
        )
        record = InputDatetimeRecord.model_validate(_expect_dict(val, "input_datetime/update"))
        self.logger.debug("Updated input_datetime helper %r", helper_id)
        return record

    async def delete_input_datetime(self, helper_id: str) -> None:
        """Delete an input_datetime helper.

        Args:
            helper_id: The ID of the helper to delete.
        """
        await _ws_helper_call(self, "input_datetime", "delete", input_datetime_id=helper_id)
        self.logger.debug("Deleted input_datetime helper %r", helper_id)

    # --- input_button ---

    async def list_input_buttons(self) -> list[InputButtonRecord]:
        """List all stored input_button helpers.

        Returns:
            List of InputButtonRecord instances representing stored configs.
        """
        val = await _ws_helper_call(self, "input_button", "list")
        items = _expect_list(val, "input_button/list")
        self.logger.debug("Listed %d input_button helpers", len(items))
        return [InputButtonRecord.model_validate(item) for item in items]

    async def create_input_button(self, params: CreateInputButtonParams) -> InputButtonRecord:
        """Create a new input_button helper.

        Args:
            params: Parameters for the new helper.

        Returns:
            The stored record returned by Home Assistant.
        """
        val = await _ws_helper_call(self, "input_button", "create", **params.model_dump(exclude_unset=True))
        record = InputButtonRecord.model_validate(_expect_dict(val, "input_button/create"))
        self.logger.info("Created input_button helper %r", record.id)
        return record

    async def update_input_button(self, helper_id: str, params: UpdateInputButtonParams) -> InputButtonRecord:
        """Update an existing input_button helper.

        Args:
            helper_id: The ID of the helper to update.
            params: Fields to update (unset fields are left unchanged).

        Returns:
            The updated stored record.
        """
        val = await _ws_helper_call(
            self,
            "input_button",
            "update",
            input_button_id=helper_id,
            **params.model_dump(exclude_unset=True),
        )
        record = InputButtonRecord.model_validate(_expect_dict(val, "input_button/update"))
        self.logger.debug("Updated input_button helper %r", helper_id)
        return record

    async def delete_input_button(self, helper_id: str) -> None:
        """Delete an input_button helper.

        Args:
            helper_id: The ID of the helper to delete.
        """
        await _ws_helper_call(self, "input_button", "delete", input_button_id=helper_id)
        self.logger.debug("Deleted input_button helper %r", helper_id)

    # --- counter ---

    async def list_counters(self) -> list[CounterRecord]:
        """List all stored counter helpers.

        Returns:
            List of CounterRecord instances representing stored configs.
        """
        val = await _ws_helper_call(self, "counter", "list")
        items = _expect_list(val, "counter/list")
        self.logger.debug("Listed %d counter helpers", len(items))
        return [CounterRecord.model_validate(item) for item in items]

    async def create_counter(self, params: CreateCounterParams) -> CounterRecord:
        """Create a new counter helper.

        Args:
            params: Parameters for the new helper.

        Returns:
            The stored record returned by Home Assistant.
        """
        val = await _ws_helper_call(self, "counter", "create", **params.model_dump(exclude_unset=True))
        record = CounterRecord.model_validate(_expect_dict(val, "counter/create"))
        self.logger.info("Created counter helper %r", record.id)
        return record

    async def update_counter(self, helper_id: str, params: UpdateCounterParams) -> CounterRecord:
        """Update an existing counter helper (stored config, not live value).

        Args:
            helper_id: The ID of the helper to update.
            params: Fields to update (unset fields are left unchanged).

        Returns:
            The updated stored record.
        """
        val = await _ws_helper_call(
            self,
            "counter",
            "update",
            counter_id=helper_id,
            **params.model_dump(exclude_unset=True),
        )
        record = CounterRecord.model_validate(_expect_dict(val, "counter/update"))
        self.logger.debug("Updated counter helper %r", helper_id)
        return record

    async def delete_counter(self, helper_id: str) -> None:
        """Delete a counter helper.

        Args:
            helper_id: The ID of the helper to delete.
        """
        await _ws_helper_call(self, "counter", "delete", counter_id=helper_id)
        self.logger.debug("Deleted counter helper %r", helper_id)

    # --- timer ---

    async def list_timers(self) -> list[TimerRecord]:
        """List all stored timer helpers.

        Returns:
            List of TimerRecord instances representing stored configs.
        """
        val = await _ws_helper_call(self, "timer", "list")
        items = _expect_list(val, "timer/list")
        self.logger.debug("Listed %d timer helpers", len(items))
        return [TimerRecord.model_validate(item) for item in items]

    async def create_timer(self, params: CreateTimerParams) -> TimerRecord:
        """Create a new timer helper.

        Args:
            params: Parameters for the new helper.

        Returns:
            The stored record returned by Home Assistant.
        """
        val = await _ws_helper_call(self, "timer", "create", **params.model_dump(exclude_unset=True))
        record = TimerRecord.model_validate(_expect_dict(val, "timer/create"))
        self.logger.info("Created timer helper %r", record.id)
        return record

    async def update_timer(self, helper_id: str, params: UpdateTimerParams) -> TimerRecord:
        """Update an existing timer helper.

        Args:
            helper_id: The ID of the helper to update.
            params: Fields to update (unset fields are left unchanged).

        Returns:
            The updated stored record.
        """
        val = await _ws_helper_call(
            self,
            "timer",
            "update",
            timer_id=helper_id,
            **params.model_dump(exclude_unset=True),
        )
        record = TimerRecord.model_validate(_expect_dict(val, "timer/update"))
        self.logger.debug("Updated timer helper %r", helper_id)
        return record

    async def delete_timer(self, helper_id: str) -> None:
        """Delete a timer helper.

        Args:
            helper_id: The ID of the helper to delete.
        """
        await _ws_helper_call(self, "timer", "delete", timer_id=helper_id)
        self.logger.debug("Deleted timer helper %r", helper_id)

    # ---------------------------------------------------------------------------
    # Counter service-call shortcuts (operate on live entity state, not stored
    # config). Use update_counter() to change the stored initial/minimum/maximum.
    #
    # timer.start / timer.pause / timer.cancel are deliberately excluded: timer
    # service actions are one-off calls that benefit from the full call_service()
    # signature. Counter actions get wrappers because the pattern "increment on
    # every event" is common enough to warrant a two-word call site.
    # ---------------------------------------------------------------------------

    async def increment_counter(self, entity_id: str) -> None:
        """Increment a counter entity's current value (live state, not stored config).

        Args:
            entity_id: The entity ID of the counter (e.g. ``"counter.motion_count"``).
        """
        await self.call_service(
            "counter",
            "increment",
            target={"entity_id": entity_id},
            return_response=True,  # surfaces HA errors instead of fire-and-forget
        )
        self.logger.debug("Incremented counter %r", entity_id)

    async def decrement_counter(self, entity_id: str) -> None:
        """Decrement a counter entity's current value (live state, not stored config).

        Args:
            entity_id: The entity ID of the counter (e.g. ``"counter.motion_count"``).
        """
        await self.call_service(
            "counter",
            "decrement",
            target={"entity_id": entity_id},
            return_response=True,
        )
        self.logger.debug("Decremented counter %r", entity_id)

    async def reset_counter(self, entity_id: str) -> None:
        """Reset a counter entity's value to its configured initial (live state, not stored config).

        Args:
            entity_id: The entity ID of the counter (e.g. ``"counter.motion_count"``).
        """
        await self.call_service(
            "counter",
            "reset",
            target={"entity_id": entity_id},
            return_response=True,
        )
        self.logger.debug("Reset counter %r", entity_id)
