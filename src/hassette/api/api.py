"""API interface for interacting with Home Assistant's REST and WebSocket APIs.

The Api provides both async and sync methods for all Home Assistant interactions including
state management, service calls, event firing, and data retrieval. Automatically handles
authentication, retries, and type conversion for a seamless developer experience.

Fire-and-forget methods (``call_service``, ``fire_event``, ``set_state``, ``turn_on``,
``turn_off``, ``toggle``, ``notify``) return a ``Coroutine`` and must be awaited.

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

    # Send a notification through notify.<notifier>
    await self.api.notify("The garage door is still open", "mobile_app_phone")
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
from contextlib import suppress
from typing import Any

import aiohttp
from hassette_wire import LogLevel

from hassette.api.entity_data import ApiEntityDataMixin
from hassette.api.service_calls import ApiServiceCallsMixin
from hassette.exceptions import (
    WS_NOT_CONNECTED_MESSAGE,
    ConnectionClosedError,
    FailedMessageError,
    OutcomeUnknownError,
    UnableToConvertStateError,
)
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready


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
async def _ws_helper_call(  # pyright: ignore[reportUnusedFunction]
    api: "Api", domain: str, operation: str, *, retry_on_timeout: bool = True, **data: Any
) -> Any:
    """Call ws_send_and_wait with domain/operation context on failure.

    Preserves ``code`` and ``original_data`` from the original FailedMessageError
    so callers can inspect them via ``except FailedMessageError as e: e.code``.
    Chains through ``raise ... from e`` so the original traceback is retained.

    ``retry_on_timeout`` forwards to ``ws_send_and_wait``: writes pass False so a lost
    response can't apply them twice; ``list`` keeps the default. A disconnect raises
    ``ResponseLostError`` and a timeout raises ``ResponseTimeoutError``, both unwrapped
    with payload-free messages — catch ``OutcomeUnknownError`` for either.
    """
    try:
        return await api.ws_send_and_wait(type=f"{domain}/{operation}", retry_on_timeout=retry_on_timeout, **data)
    except OutcomeUnknownError:
        raise  # also a FailedMessageError; caught first so the rewrap below keeps its type
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

# Also deferred until after the helper functions above are defined: `sync.py` imports
# `sync_helpers.py`, which imports `helpers.py` (for `HelperDomain`) at runtime — the same
# transitive path as the `HelperClient` import above, so it is subject to the same ordering
# constraint.
from .sync import ApiSyncFacade  # noqa: E402

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.api_resource import ApiResource
    from hassette.events import HassStateDict
    from hassette.models.states import BaseState


class Api(ApiServiceCallsMixin, ApiEntityDataMixin, Resource):
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
        # helpers must be constructed before sync — ApiSyncFacade.__init__ reads
        # self._api.helpers to wire its own nested HelperClientSyncFacade.
        self.helpers = self.add_child(HelperClient, api=self)
        self.sync = self.add_child(ApiSyncFacade, api=self)

    async def on_initialize(self) -> None:
        """Mark the API ready; transport is delegated to ``hassette.api_service``, so there is nothing to set up."""
        mark_ready(self, reason="API initialized")

    @property
    def config_log_level(self) -> LogLevel:
        """Return the log level from the config for this resource."""
        return self.hassette.config.logging.api

    async def ws_send_and_wait(self, *, retry_on_timeout: bool = True, **data: Any) -> Any:
        """Send a WebSocket message and wait for a response.

        Args:
            retry_on_timeout: Whether a response timeout may be retried. Defaults to True.
                Pass False for a non-idempotent command — a retry re-sends it, duplicating a side
                effect Home Assistant may already have applied. A timeout then raises
                ``ResponseTimeoutError``. See :meth:`WebsocketService.send_and_wait`.
            **data: The data to send as a JSON payload. ``retry_on_timeout`` is client-side
                policy and is consumed here, so it is the one name this escape hatch cannot
                forward as a payload field.
        """
        if not self._api_service.ws_conn.is_connected:
            raise ConnectionClosedError(WS_NOT_CONNECTED_MESSAGE)
        return await self._api_service.ws_conn.send_and_wait(retry_on_timeout=retry_on_timeout, **data)

    async def ws_send_json(self, **data: Any) -> None:
        """Send a WebSocket message without waiting for a response."""
        if not self._api_service.ws_conn.is_connected:
            raise ConnectionClosedError(WS_NOT_CONNECTED_MESSAGE)
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
