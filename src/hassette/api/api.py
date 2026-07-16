"""API interface for interacting with Home Assistant's REST and WebSocket APIs.

The Api provides both async and sync methods for all Home Assistant interactions including
state management, service calls, event firing, and data retrieval. Automatically handles
authentication, retries, and type conversion for a seamless developer experience.

Fire-and-forget methods (``call_service``, ``fire_event``, ``set_state``, ``turn_on``,
``turn_off``, ``toggle``) return a ``Coroutine`` and must be awaited.

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
    await self.api.call_service("light", "turn_on", target={"entity_id": "light.kitchen"})

    # Service call with data
    await self.api.call_service(
        "light",
        "turn_on",
        target={"entity_id": "light.living_room"},
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
    await self.api.toggle("switch.fan")
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
        entity_id="sensor.temperature",
        start_time=start_time,
        end_time=end_time
    )

    # Get logbook entries
    logbook = await self.api.get_logbook(
        start_time=start_time,
        end_time=end_time,
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
from collections.abc import Coroutine  # noqa: TC003 — needed at runtime for annotation inspection
from contextlib import suppress
from enum import StrEnum
from http import HTTPStatus
from typing import Any, Literal, overload

import aiohttp
from whenever import Date, PlainDateTime, ZonedDateTime

from hassette.const.misc import FalseySentinel
from hassette.event_handling.accessors import get_path
from hassette.exceptions import EntityNotFoundError, FailedMessageError, UnableToConvertStateError
from hassette.models.entities import BaseEntity
from hassette.models.history import HistoryEntry
from hassette.models.services import ServiceResponse
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.await_guard import guard_await
from hassette.utils.request_utils import format_time_param
from hassette.utils.source_capture import capture_source_location

from .sync import ApiSyncFacade


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


# Only imported by hassette.api.helpers (cross-module) — pyright's reportUnusedFunction does not
# credit a leading-underscore name's use in another module, so it flags this as unused without
# the suppression below.
async def _ws_helper_call(api: "Api", domain: str, operation: str, **data: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
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
    except FailedMessageError as exc:
        # Include only field names in the error message — values may contain
        # sensitive data (e.g., `input_text.initial` on a password-mode helper)
        # that would leak into application logs. Full payload is preserved on
        # `original_data` for debugging contexts that need it.
        field_names = sorted(data.keys())
        raise FailedMessageError(
            f"{domain}/{operation} failed (fields: {field_names}): {exc}",
            code=exc.code,
            original_data=exc.original_data,
        ) from exc


# Imported here (rather than with the other top-of-file imports) because `helpers.py` imports
# `_expect_list`, `_expect_dict`, and `_ws_helper_call` from this module — importing HelperClient
# any earlier would create a circular import that fails at runtime (those names would not yet be
# bound on this module when helpers.py's `from .api import ...` executes).
from hassette.api.helpers import HelperClient  # noqa: E402

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.api_resource import ApiResource
    from hassette.events import HassStateDict
    from hassette.models.entities import EntityT
    from hassette.models.states import BaseState


class Api(Resource):
    """API service for interacting with Home Assistant.

    This service provides methods to interact with the Home Assistant API, including making REST requests,
    managing WebSocket connections, and handling entity states.
    """

    sync: ApiSyncFacade
    """Synchronous facade for the API service."""

    helpers: HelperClient
    """Client for CRUD operations on Home Assistant helper entities."""

    _api_service: "ApiResource"
    """Internal API service instance."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._api_service = self.hassette.api_service
        self.sync = self.add_child(ApiSyncFacade, api=self)
        self.helpers = self.add_child(HelperClient, api=self)

    async def on_initialize(self) -> None:
        mark_ready(self, reason="API initialized")

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.logging.api

    async def ws_send_and_wait(self, **data: Any) -> Any:
        """Send a WebSocket message and wait for a response."""
        return await self._api_service.ws_conn.send_and_wait(**data)

    async def ws_send_json(self, **data: Any) -> None:
        """Send a WebSocket message without waiting for a response."""
        await self._api_service.ws_conn.send_json(**data)

    async def rest_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        suppress_error_message: bool = False,
        **kwargs: Any,
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
        return await self._api_service.rest_request(
            method, url, params=params, data=data, suppress_error_message=suppress_error_message, **kwargs
        )

    async def get_rest_request(
        self, url: str, params: dict[str, Any] | None = None, **kwargs: Any
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

    async def post_rest_request(
        self, url: str, data: dict[str, Any] | None = None, **kwargs: Any
    ) -> aiohttp.ClientResponse:
        """Make a POST request to the Home Assistant API.

        Args:
            url: The URL endpoint for the request.
            data: JSON payload for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            The response from the API.
        """
        return await self.rest_request("POST", url, data=data, **kwargs)

    async def delete_rest_request(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
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
        val = await self.ws_send_and_wait(type="get_states")
        return _expect_list(val, "get_states")

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

    async def get_config(self) -> dict[str, Any]:
        """Get the Home Assistant configuration.

        Returns:
            The configuration data.
        """
        val = await self.ws_send_and_wait(type="get_config")
        return _expect_dict(val, "get_config")

    async def get_services(self) -> dict[str, Any]:
        """Get the available services in Home Assistant.

        Returns:
            The services data.
        """
        val = await self.ws_send_and_wait(type="get_services")
        return _expect_dict(val, "get_services")

    async def get_panels(self) -> dict[str, Any]:
        """Get the available panels in Home Assistant.

        Returns:
            The panels data.
        """
        val = await self.ws_send_and_wait(type="get_panels")
        return _expect_dict(val, "get_panels")

    def fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, dict[str, Any]]":
        """Fire a custom event in Home Assistant.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            event_type: The type of the event to fire (e.g., "custom_event").
            event_data: Additional data to include with the event.

        Returns:
            The response from Home Assistant.
        """
        # Cheap path: no DB-record telemetry on api fire-and-forget methods
        # (unlike bus/scheduler listeners) — only warning attribution needs the location here.
        source_location = capture_source_location()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._fire_event(event_type, event_data),
            owner=self.parent,
            source_location=source_location,
            method_name="fire_event",
        )

    async def _fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Async body for fire_event."""
        event_data = event_data or {}

        data = {"type": "fire_event", "event_type": event_type, "event_data": event_data}
        if not event_data:
            data.pop("event_data")

        return await self.ws_send_and_wait(**data)

    # Overload order is load-bearing — Pyright matches top-to-bottom, first hit wins.
    # The None-returning (return_response not True) overload MUST come first so a call
    # that omits return_response resolves to it. The True overload needs a default
    # (target already has one, and a non-default arg can't follow a default arg), but
    # that default never makes it the chosen overload for an omitted return_response,
    # because the None overload above matches first. Reordering or dropping the default
    # silently flips the inferred return type — covered by tests/pyright_probes.
    @overload
    def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: typing.Literal[False] | None = None,
        **data: Any,
    ) -> "Coroutine[Any, Any, None]": ...

    @overload
    def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: Literal[True] = True,
        **data: Any,
    ) -> "Coroutine[Any, Any, ServiceResponse]": ...

    def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: bool | None = False,
        **data: Any,
    ) -> "Coroutine[Any, Any, ServiceResponse | None]":
        """Call a Home Assistant service.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            domain: The domain of the service (e.g., "light").
            service: The name of the service to call (e.g., "turn_on").
            target: Target entity IDs or areas.
            return_response: Whether to return the response from Home Assistant. Defaults to False.
            **data: Additional data to send with the service call.

        Returns:
            ServiceResponse | None: The response from Home Assistant if return_response is True. Otherwise None.
        """
        # Cheap path — see fire_event (same rationale for all api methods)
        source_location = capture_source_location()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._call_service(domain, service, target, return_response, **data),
            owner=self.parent,
            source_location=source_location,
            method_name="call_service",
        )

    async def _call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: bool | None = False,
        **data: Any,
    ) -> ServiceResponse | None:
        """Async body for call_service."""
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

    def turn_on(self, entity_id: str | StrEnum, domain: str | None = None, **data: Any) -> "Coroutine[Any, Any, None]":
        """Turn on a specific entity in Home Assistant.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            entity_id: The ID of the entity to turn on (e.g., "light.office").
            domain: The domain to use for the service call. Defaults to the entity's domain,
                derived from ``entity_id`` (e.g., ``"light.office"`` derives ``"light"``). Pass
                explicitly to override — for example, ``domain="homeassistant"`` to use the
                generic (deprecated) service.
            **data: Additional service data forwarded to the service call.

        """
        entity_id = str(entity_id)
        if domain is None:
            domain = entity_id.split(".", 1)[0]
        return self.call_service(domain=domain, service="turn_on", target={"entity_id": entity_id}, **data)

    def turn_off(self, entity_id: str | StrEnum, domain: str | None = None, **data: Any) -> "Coroutine[Any, Any, None]":
        """Turn off a specific entity in Home Assistant.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            entity_id: The ID of the entity to turn off (e.g., "light.office").
            domain: The domain to use for the service call. Defaults to the entity's domain,
                derived from ``entity_id`` (e.g., ``"light.office"`` derives ``"light"``). Pass
                explicitly to override — for example, ``domain="homeassistant"`` to use the
                generic (deprecated) service.
            **data: Additional service data forwarded to the service call.

        """
        entity_id = str(entity_id)
        if domain is None:
            domain = entity_id.split(".", 1)[0]
        return self.call_service(domain=domain, service="turn_off", target={"entity_id": entity_id}, **data)

    def toggle(self, entity_id: str | StrEnum, domain: str | None = None, **data: Any) -> "Coroutine[Any, Any, None]":
        """Toggle a specific entity in Home Assistant.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            entity_id: The ID of the entity to toggle (e.g., "light.office").
            domain: The domain to use for the service call. Defaults to the entity's domain,
                derived from ``entity_id`` (e.g., ``"light.office"`` derives ``"light"``). Pass
                explicitly to override — for example, ``domain="homeassistant"`` to use the
                generic (deprecated) service.
            **data: Additional service data forwarded to the service call.

        """
        entity_id = str(entity_id)
        if domain is None:
            domain = entity_id.split(".", 1)[0]
        return self.call_service(domain=domain, service="toggle", target={"entity_id": entity_id}, **data)

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
        except EntityNotFoundError:
            return None

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
        except EntityNotFoundError:
            return None

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

        entries = await self._api_service.get_history_raw(
            entity_id=entity_id,
            start_time=start_time,
            end_time=end_time,
            significant_changes_only=significant_changes_only,
            minimal_response=minimal_response,
            no_attributes=no_attributes,
        )

        if not entries:
            return []

        if len(entries) != 1:
            raise RuntimeError(f"Expected a single list of history entries from HA, got {len(entries)}")

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

        entries = await self._api_service.get_history_raw(
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
    ) -> list[dict[str, Any]]:
        """Get the logbook entries for a specific entity.

        Args:
            entity_id: The ID of the entity to get the logbook entries for.
            start_time: The start time for the logbook range.
            end_time: The end time for the logbook range.

        Returns:
            A list of logbook entries for the specified entity.
        """
        url = f"logbook/{format_time_param(start_time)}"
        params = {"entity": entity_id, "end_time": end_time}

        response = await self.get_rest_request(url, params=params)

        return await response.json()

    def set_state(
        self,
        entity_id: str | StrEnum,
        state: Any,
        attributes: dict[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, dict]":
        """Set the state of a specific entity.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            entity_id: The ID of the entity to set the state for.
            state: The new state value to set.
            attributes: Additional attributes to set for the entity.

        Returns:
            The response from Home Assistant after setting the state.
        """
        # Cheap path — see fire_event (same rationale for all api methods)
        source_location = capture_source_location()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._set_state(entity_id, state, attributes),
            owner=self.parent,
            source_location=source_location,
            method_name="set_state",
        )

    async def _set_state(
        self,
        entity_id: str | StrEnum,
        state: Any,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Async body for set_state."""
        entity_id = str(entity_id)

        attributes = attributes or {}
        curr_attributes = {}

        if await self.entity_exists(entity_id):
            curr_attributes = (await self.get_state_raw(entity_id)).get("attributes", {}) or {}

        # Merge current attributes with new attributes.
        # This client-side merge is load-bearing: HA's POST /api/states/{id} REPLACES the attribute
        # set rather than merging it (verified against a live instance 2026-06-21 — a partial POST
        # dropped the un-named attributes). Without this read-then-merge, every partial attribute
        # write would wipe the attributes it doesn't mention. See tests/system/test_api.py
        # ::test_set_state_preserves_unnamed_attributes.
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

    async def get_calendars(self) -> list[dict[str, Any]]:
        """Get the list of calendars."""
        url = "calendars"
        response = await self.get_rest_request(url)
        return await response.json()

    async def get_calendar_events(
        self,
        calendar_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str,
    ) -> list[dict[str, Any]]:
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
        variables: dict[str, Any] | None = None,
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

        if response.status != HTTPStatus.NO_CONTENT:
            raise RuntimeError(f"Failed to delete entity {entity_id}: {response.status} - {response.reason}")
