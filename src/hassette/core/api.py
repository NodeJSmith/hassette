import logging
import typing
from collections.abc import Iterable, Mapping
from contextlib import AsyncExitStack
from datetime import date, datetime
from enum import StrEnum
from logging import getLogger
from typing import Any

import aiohttp
import orjson
from tenacity import before_sleep_log, retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential_jitter
from whenever import Date, Instant, PlainDateTime, ZonedDateTime

from hassette.core.classes import Resource
from hassette.core.events import HassContext, HassStateDict
from hassette.exceptions import ConnectionClosedError, EntityNotFoundError, InvalidAuthError
from hassette.models.entities import BaseEntity, EntityT
from hassette.models.history import HistoryEntry, normalize_history
from hassette.models.states import BaseState, StateT, StateUnion, StateValueT, try_convert_state

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette
    from hassette.core.websocket import _Websocket

LOGGER = getLogger(__name__)


class _Api(Resource):
    def __init__(self, hassette: "Hassette"):
        super().__init__(hassette)

        self.started = False
        self._stack = AsyncExitStack()

    async def initialize(self):
        """
        Start the API service.
        """
        await super().initialize()

        if self.started:
            return self

        self.logger.debug("Starting '%s' service", self.class_name)

        await self._stack.__aenter__()
        self._session = await self._stack.enter_async_context(
            aiohttp.ClientSession(headers=self._headers, base_url=self._rest_url)
        )

        self.started = True
        return self

    async def shutdown(self, *args, **kwargs) -> None:
        self.started = False
        await self._stack.aclose()
        await super().shutdown()

    @property
    def _headers(self) -> dict[str, str]:
        """Get the headers for this API instance."""
        return self.hassette.config.headers

    @property
    def _rest_url(self) -> str:
        """Get the REST URL for this API instance."""
        return self.hassette.config.rest_url

    @property
    def _ws_conn(self) -> "_Websocket":
        """Get the WebSocket connection for this API instance."""
        return self.hassette._websocket

    @retry(
        retry=retry_if_not_exception_type(
            (EntityNotFoundError, InvalidAuthError, RuntimeError, ConnectionClosedError, TypeError, AttributeError)
        ),
        wait=wait_exponential_jitter(),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(LOGGER, logging.WARNING),
        reraise=True,
    )
    async def _rest_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        suppress_error_message: bool = False,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        """Make a REST request to the Home Assistant API."""

        if self._session is None:
            raise RuntimeError("Client session is not connected")

        params = clean_kwargs(**(params or {}))
        str_data = orjson_dump(data or {})

        request_kwargs = {}

        if str_data:
            request_kwargs["data"] = str_data
            request_kwargs["headers"] = {"Content-Type": "application/json"}

        if params:
            request_kwargs["params"] = params

        try:
            response = await self._session.request(method, url, **request_kwargs, **kwargs)
            self.logger.debug("Making %s request to %s with data %s", method, response.real_url, str_data)
            response.raise_for_status()

            return response
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                if not suppress_error_message:
                    self.logger.error("Error occurred while making %s request to %s: %s", method, url, e, stacklevel=2)

                raise EntityNotFoundError(f"Entity not found: {url}") from None
            raise

        except aiohttp.ClientError as e:
            if not suppress_error_message:
                self.logger.error("Error occurred while making %s request to %s: %s", method, url, e, stacklevel=2)

            raise

    async def _get_history_raw(
        self,
        entity_id: str,
        start_time: PlainDateTime | Date | datetime | date | str,
        end_time: PlainDateTime | Date | datetime | date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> list[list[dict[str, Any]]]:
        """Get the history of a specific entity."""

        url = f"history/period/{start_time}"

        params = {
            "filter_entity_id": entity_id,
            "end_time": end_time,
            "significant_changes_only": significant_changes_only,
            "minimal_response": minimal_response,
            "no_attributes": no_attributes,
        }
        # having parameters like `minimal_response` in the parameters changes the response format
        # regardless of whether they are set to True or False
        # so we remove them if they are False
        params = {k: v for k, v in params.items() if v is not False}

        response = await self._rest_request("GET", url, params=params)

        entries = await response.json()

        normalized = normalize_history(entries)

        return normalized


class Api(Resource):
    """API service for interacting with Home Assistant.

    This service provides methods to interact with the Home Assistant API, including making REST requests,
    managing WebSocket connections, and handling entity states.
    """

    def __init__(self, hassette: "Hassette", _api: _Api) -> None:
        super().__init__(hassette)
        self._api = _api
        self.sync = ApiSyncFacade(self)

    async def ws_send_and_wait(self, **data: Any) -> Any:
        """Send a WebSocket message and wait for a response."""
        return await self._api._ws_conn.send_and_wait(**data)

    async def ws_send_json(self, **data: Any) -> None:
        """Send a WebSocket message without waiting for a response."""
        await self._api._ws_conn.send_json(**data)

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
            method (str): The HTTP method to use (e.g., "GET", "POST").
            url (str): The URL endpoint for the request.
            params (dict[str, Any], optional): Query parameters for the request.
            data (dict[str, Any], optional): JSON payload for the request.
            suppress_error_message (bool, optional): Whether to suppress error messages.

        Returns:
            aiohttp.ClientResponse: The response from the API.
        """
        return await self._api._rest_request(
            method, url, params=params, data=data, suppress_error_message=suppress_error_message, **kwargs
        )

    async def get_rest_request(
        self, url: str, params: dict[str, Any] | None = None, **kwargs
    ) -> aiohttp.ClientResponse:
        """Make a GET request to the Home Assistant API.

        Args:
            url (str): The URL endpoint for the request.
            params (dict[str, Any], optional): Query parameters for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            aiohttp.ClientResponse: The response from the API.
        """
        return await self.rest_request("GET", url, params=params, **kwargs)

    async def post_rest_request(self, url: str, data: dict[str, Any] | None = None, **kwargs) -> aiohttp.ClientResponse:
        """Make a POST request to the Home Assistant API.

        Args:
            url (str): The URL endpoint for the request.
            data (dict[str, Any], optional): JSON payload for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            aiohttp.ClientResponse: The response from the API.
        """
        return await self.rest_request("POST", url, data=data, **kwargs)

    async def delete_rest_request(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make a DELETE request to the Home Assistant API.

        Args:
            url (str): The URL endpoint for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            aiohttp.ClientResponse: The response from the API.
        """
        return await self.rest_request("DELETE", url, **kwargs)

    async def get_states_raw(self) -> list[HassStateDict]:
        """Get all entities in Home Assistant as raw dictionaries.

        Returns:
            list[HassStateDict]: A list of states as dictionaries.
        """
        val: list[HassStateDict] = await self.ws_send_and_wait(type="get_states")  # type: ignore
        assert isinstance(val, list), "Expected a list of states"
        return val

    async def get_states(self) -> list[StateUnion]:
        """Get all entities in Home Assistant.

        Returns:
            list[StateUnion]: A list of states, either as dictionaries or converted to state objects.
        """
        val = await self.get_states_raw()

        self.logger.debug("Converting states to specific state types")
        return list(filter(bool, [try_convert_state(state) for state in val]))

    async def get_config(self) -> dict[str, Any]:
        """
        Get the Home Assistant configuration.

        Returns:
            dict: The configuration data.
        """
        val = await self.ws_send_and_wait(type="get_config")
        assert isinstance(val, dict), "Expected a dictionary of configuration data"
        return val

    async def get_services(self) -> dict[str, Any]:
        """
        Get the available services in Home Assistant.

        Returns:
            dict: The services data.
        """
        val = await self.ws_send_and_wait(type="get_services")
        assert isinstance(val, dict), "Expected a dictionary of services"
        return val

    async def get_panels(self) -> dict[str, Any]:
        """
        Get the available panels in Home Assistant.

        Returns:
            dict: The panels data.
        """
        val = await self.ws_send_and_wait(type="get_panels")
        assert isinstance(val, dict), "Expected a dictionary of panels"
        return val

    async def fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Fire a custom event in Home Assistant.

        Args:
            event_type (str): The type of the event to fire (e.g., "custom_event").
            event_data (dict[str, Any], optional): Additional data to include with the event.

        Returns:
            dict: The response from Home Assistant.
        """
        event_data = event_data or {}

        data = {"type": "fire_event", "event_type": event_type, "event_data": event_data}
        if not event_data:
            data.pop("event_data")

        return await self.ws_send_and_wait(**data)

    async def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: bool | None = None,
        **data,
    ) -> HassContext | None:
        """
        Call a Home Assistant service.

        Args:
            domain (str): The domain of the service (e.g., "light").
            service (str): The name of the service to call (e.g., "turn_on").
            target (dict[str, str], optional): Target entity IDs or areas.
            **kwargs: Additional data to send with the service call.

        Returns:
            HassContext | None: The response from Home Assistant if return_response is True. Otherwise, returns None.
        """
        payload = {
            "type": "call_service",
            "domain": domain,
            "service": service,
            "target": target,
        }

        payload = {k: v for k, v in payload.items() if v is not None}

        if data:
            data = {k: v for k, v in data.items() if v is not None}
            self.logger.debug("Adding extra data to service call: %s", data)
            payload |= {"service_data": data}

        if return_response:
            resp = await self.ws_send_and_wait(**payload)
            return HassContext(**resp.get("context", {}))

        await self.ws_send_json(**payload)
        return None

    async def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data):
        """
        Turn on a specific entity in Home Assistant.

        Args:
            entity_id (str): The ID of the entity to turn on (e.g., "light.office").
            domain (str): The domain of the entity (default: "homeassistant").

        Returns:
            HassContext: The response context from Home Assistant.
        """
        entity_id = str(entity_id)

        self.logger.debug("Turning on entity %s", entity_id)
        return await self.call_service(
            domain=domain,
            service="turn_on",
            target={"entity_id": entity_id},
            return_response=True,
            **data,
        )

    async def turn_off(self, entity_id: str, domain: str = "homeassistant"):
        """
        Turn off a specific entity in Home Assistant.

        Args:
            entity_id (str): The ID of the entity to turn off (e.g., "light.office").
            domain (str): The domain of the entity (default: "homeassistant").

        Returns:
            HassContext: The response context from Home Assistant.
        """
        self.logger.debug("Turning off entity %s", entity_id)
        return await self.call_service(
            domain=domain,
            service="turn_off",
            target={"entity_id": entity_id},
            return_response=True,
        )

    async def toggle_service(self, entity_id: str, domain: str = "homeassistant"):
        """
        Toggle a specific entity in Home Assistant.

        Args:
            entity_id (str): The ID of the entity to toggle (e.g., "light.office").
            domain (str): The domain of the entity (default: "homeassistant").

        Returns:
            HassContext: The response context from Home Assistant.
        """
        self.logger.debug("Toggling entity %s", entity_id)
        return await self.call_service(
            domain=domain,
            service="toggle",
            target={"entity_id": entity_id},
            return_response=True,
        )

    async def get_state_raw(self, entity_id: str) -> HassStateDict:
        """Get the state of a specific entity.

        Args:
            entity_id (str): The ID of the entity to get the state for.

        Returns:
            HassStateDict: The state of the entity as raw data.
        """

        url = f"states/{entity_id}"
        response = await self.get_rest_request(url)
        return await response.json()

    async def entity_exists(self, entity_id: str) -> bool:
        """Check if a specific entity exists.

        Args:
            entity_id (str): The ID of the entity to check.

        Returns:
            bool: True if the entity exists, False otherwise.
        """

        try:
            url = f"states/{entity_id}"
            response = await self.rest_request("GET", url, suppress_error_message=True)
            await response.json()
            return True
        except EntityNotFoundError:
            return False

    async def get_entity(self, entity_id: str, model: type[EntityT]) -> EntityT:
        """Get an entity object for a specific entity.

        Args:
            entity_id (str): The ID of the entity to get.
            model (type[EntityT]): The model class to use for the entity.

        Returns:
            EntityT: The entity object.

        Note:
            This is not the same as calling get_state: get_state returns a BaseState subclass.
            This call returns an EntityState subclass, which wraps the state object and provides
            api methods for interacting with the entity.

        """
        if not issubclass(model, BaseEntity):  # runtime check
            raise TypeError(f"Model {model!r} is not a valid BaseEntity subclass")

        raw = await self.get_state_raw(entity_id)

        return model.model_validate({"state": raw})

    async def get_entity_or_none(self, entity_id: str, model: type[EntityT]) -> EntityT | None:
        """Get an entity object for a specific entity, or None if it does not exist.

        Args:
            entity_id (str): The ID of the entity to get.
            model (type[EntityT]): The model class to use for the entity.

        Returns:
            EntityT | None: The entity object, or None if it does not exist.
        """
        try:
            return await self.get_entity(entity_id, model)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise

    async def get_state(self, entity_id: str, model: type[StateT]) -> StateT:
        """Get the state of a specific entity.

        Args:
            entity_id (str): The ID of the entity to get the state for.
            model (type[StateT]): The model type to convert the state to.

        Returns:
            StateT: The state of the entity converted to the specified model type.
        """

        if not issubclass(model, BaseState):  # runtime check
            raise TypeError(f"Model {model!r} is not a valid StateType subclass")

        raw = await self.get_state_raw(entity_id)

        return model.model_validate(raw)

    async def get_state_value(self, entity_id: str) -> str:
        """Get the state of a specific entity without converting it to a state object.

        Args:
            entity_id (str): The ID of the entity to get the state for.

        Returns:
            str: The state of the entity as raw data.

        Note:
            While most default methods in this library work with state objects for
            strong typing, this method is designed to return the raw state value,
            as it is likely overkill to convert it to a state object for simple state value retrieval.
        """

        entity = await self.get_state_raw(entity_id)
        state = entity.get("state")
        if not isinstance(state, str):
            self.logger.info(
                "Entity %s state is not a string (%s), return type annotation should be updated",
                entity_id,
                type(state).__name__,
            )

        return state  # pyright: ignore[reportReturnType]

    async def get_state_value_typed(self, entity_id: str, model: type[BaseState[StateValueT]]) -> StateValueT:
        """Get the state of a specific entity as a converted state object.

        Args:
            entity_id (str): The ID of the entity to get the state for.
            model (type[BaseState[StateValueT]]): The model type to convert the state to.

        Returns:
            StateValueT: The state of the entity converted to the specified model type.

        Raises:
            TypeError: If the model is not a valid StateType subclass.

        Note:
            Instead of the default way of calling `get_state` involving a type, we assume that the
            average user only needs the raw value of the state value, without type safety.
        """

        state = await self.get_state(entity_id, model)
        return state.value

    async def get_attribute(self, entity_id: str, attribute: str) -> Any | None:
        """Get a specific attribute of an entity.

        Args:
            entity_id (str): The ID of the entity to get the attribute for.
            attribute (str): The name of the attribute to retrieve.

        Returns:
            Any: The value of the specified attribute, or None if it does not exist.
        """

        entity = await self.get_state_raw(entity_id)
        return (entity.get("attributes", {}) or {}).get(attribute)

    async def get_history(
        self,
        entity_id: str,
        start_time: PlainDateTime | Date | datetime | date | str,
        end_time: PlainDateTime | Date | datetime | date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> list[HistoryEntry]:
        """Get the history of a specific entity.

        Args:
            entity_id (str): The ID of the entity to get the history for.
            start_time (PlainDateTime | Date | datetime | date | str):
                The start time for the history range.
            end_time (PlainDateTime | Date | datetime | date | str | None, optional):
                The end time for the history range.
            significant_changes_only (bool, optional): Whether to only include significant changes.
            minimal_response (bool, optional): Whether to request a minimal response.
            no_attributes (bool, optional): Whether to exclude attributes from the response.

        Returns:
            list[HistoryEntry]: A list of history entries for the specified entity.
        """
        if "," in entity_id:
            raise ValueError("Entity ID should not contain commas. Use `get_histories` for multiple entities.")

        entries = await self._api._get_history_raw(
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
        start_time: PlainDateTime | Date | datetime | date | str,
        end_time: PlainDateTime | Date | datetime | date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> dict[str, list[HistoryEntry]]:
        """Get the history for multiple entities.

        Args:
            entity_ids (list[str]): The IDs of the entities to get the history for.
            start_time (PlainDateTime | Date | datetime | date | str):
                The start time for the history range.
            end_time (PlainDateTime | Date | datetime | date | str | None, optional):
                The end time for the history range.
            significant_changes_only (bool, optional): Whether to only include significant changes.
            minimal_response (bool, optional): Whether to request a minimal response.
            no_attributes (bool, optional): Whether to exclude attributes from the response.

        Returns:
            dict[str, list[HistoryEntry]]: A dictionary mapping entity IDs to their respective history entries.
        """
        entity_id = ",".join(entity_ids)

        entries = await self._api._get_history_raw(
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
        start_time: PlainDateTime | Date | datetime | date | str,
        end_time: PlainDateTime | Date | datetime | date | str,
    ) -> list[dict]:
        """Get the logbook entries for a specific entity.

        Args:
            entity_id (str): The ID of the entity to get the logbook entries for.
            start_time (PlainDateTime | Date | datetime | date | str): The start time for the logbook range.
            end_time (PlainDateTime | Date | datetime | date | str): The end time for the logbook range.

        Returns:
            list[dict]: A list of logbook entries for the specified entity.
        """

        url = f"logbook/{start_time}"
        params = {"entity": entity_id, "end_time": end_time}

        response = await self.get_rest_request(url, params=params)

        return await response.json()

    async def set_state(
        self,
        entity_id: str | StrEnum,
        state: str,
        attributes: dict[str, Any] | None = None,
    ) -> dict:
        """Set the state of a specific entity.

        Args:
            entity_id (str | StrEnum): The ID of the entity to set the state for.
            state (str): The new state value to set.
            attributes (dict[str, Any], optional): Additional attributes to set for the entity.

        Returns:
            dict: The response from Home Assistant after setting the state.
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
        timestamp: ZonedDateTime | PlainDateTime | Date | datetime | date | str | None = None,
    ) -> bytes:
        """Get the latest camera image for a specific entity.

        Args:
            entity_id (str): The ID of the camera entity to get the image for.
            timestamp (ZonedDateTime | PlainDateTime | Date | datetime | date | str | None, optional):
                The timestamp for the image. If None, the latest image is returned.

        Returns:
            bytes: The camera image data.
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
        start_time: PlainDateTime | Date | datetime | date | str,
        end_time: PlainDateTime | Date | datetime | date | str,
    ) -> list[dict]:
        """Get events from a specific calendar.

        Args:
            calendar_id (str): The ID of the calendar to get events from.
            start_time (PlainDateTime | Date | datetime | date | str): The start time for the event range.
            end_time (PlainDateTime | Date | datetime | date | str): The end time for the event range.

        Returns:
            list[dict]: A list of calendar events.
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
            template (str): The template string to render.
            variables (dict, optional): Variables to use in the template.

        Returns:
            str: The rendered template result.
        """

        url = "template"
        data = {"template": template, "variables": variables or {}}

        response = await self.post_rest_request(url, data=data)
        return await response.text()

    async def delete_entity(self, entity_id: str) -> None:
        """Delete a specific entity.

        Args:
            entity_id (str): The ID of the entity to delete.

        Raises:
            RuntimeError: If the deletion fails.
        """

        url = f"states/{entity_id}"

        response = await self.rest_request("DELETE", url)

        if response.status != 204:
            raise RuntimeError(f"Failed to delete entity {entity_id}: {response.status} - {response.reason}")


class ApiSyncFacade(Resource):
    """Synchronous facade for the API service.

    This class provides synchronous methods that wrap the asynchronous methods of the Api class,
    allowing for blocking calls in a synchronous context.

    It is important to note that these methods should not be called from within an existing event loop,
    as they will raise a RuntimeError in such cases. Use the asynchronous methods directly when operating
    within an event loop.
    """

    def __init__(self, api: Api):
        super().__init__(api.hassette)
        self._api = api

    def ws_send_and_wait(self, **data: Any):
        """Send a WebSocket message and wait for a response."""
        return self.hassette.run_sync(self._api.ws_send_and_wait(**data))

    def ws_send_json(self, **data: Any):
        """Send a WebSocket message without waiting for a response."""
        return self.hassette.run_sync(self._api.ws_send_json(**data))

    def rest_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        suppress_error_message: bool = False,
        **kwargs,
    ):
        """Make a REST request to the Home Assistant API.

        Args:
            method (str): The HTTP method to use (e.g., "GET", "POST").
            url (str): The URL endpoint for the request.
            params (dict[str, Any], optional): Query parameters for the request.
            data (dict[str, Any], optional): JSON payload for the request.
            suppress_error_message (bool, optional): Whether to suppress error messages.

        Returns:
            aiohttp.ClientResponse: The response from the API.
        """
        return self.hassette.run_sync(
            self._api.rest_request(
                method, url, params=params, data=data, suppress_error_message=suppress_error_message, **kwargs
            )
        )

    def get_rest_request(self, url: str, params: dict[str, Any] | None = None, **kwargs):
        """Make a GET request to the Home Assistant API.

        Args:
            url (str): The URL endpoint for the request.
            params (dict[str, Any], optional): Query parameters for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            aiohttp.ClientResponse: The response from the API.
        """
        return self.hassette.run_sync(self._api.get_rest_request(url, params=params, **kwargs))

    def post_rest_request(self, url: str, data: dict[str, Any] | None = None, **kwargs):
        """Make a POST request to the Home Assistant API.

        Args:
            url (str): The URL endpoint for the request.
            data (dict[str, Any], optional): JSON payload for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            aiohttp.ClientResponse: The response from the API.
        """
        return self.hassette.run_sync(self._api.post_rest_request(url, data=data, **kwargs))

    def delete_rest_request(self, url: str, **kwargs):
        """Make a DELETE request to the Home Assistant API.

        Args:
            url (str): The URL endpoint for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            aiohttp.ClientResponse: The response from the API.
        """
        return self.hassette.run_sync(self._api.delete_rest_request(url, **kwargs))

    def get_states_raw(self):
        """Get all entities in Home Assistant as raw dictionaries.

        Returns:
            list[HassStateDict]: A list of states as dictionaries.
        """
        return self.hassette.run_sync(self._api.get_states_raw())

    def get_states(self):
        """Get all entities in Home Assistant.

        Returns:
            list[StateUnion]: A list of states, either as dictionaries or converted to state objects.
        """
        return self.hassette.run_sync(self._api.get_states())

    def get_config(self):
        """
        Get the Home Assistant configuration.

        Returns:
            dict: The configuration data.
        """
        return self.hassette.run_sync(self._api.get_config())

    def get_services(self):
        """
        Get the available services in Home Assistant.

        Returns:
            dict: The services data.
        """
        return self.hassette.run_sync(self._api.get_services())

    def get_panels(self):
        """
        Get the available panels in Home Assistant.

        Returns:
            dict: The panels data.
        """
        return self.hassette.run_sync(self._api.get_panels())

    def fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ):
        """
        Fire a custom event in Home Assistant.

        Args:
            event_type (str): The type of the event to fire (e.g., "custom_event").
            event_data (dict[str, Any], optional): Additional data to include with the event.

        Returns:
            dict: The response from Home Assistant.
        """
        return self.hassette.run_sync(self._api.fire_event(event_type, event_data))

    def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: bool = True,
        **data,
    ):
        """
        Call a Home Assistant service.

        Args:
            domain (str): The domain of the service (e.g., "light").
            service (str): The name of the service to call (e.g., "turn_on").
            target (dict[str, str], optional): Target entity IDs or areas.
            **kwargs: Additional data to send with the service call.

        Returns:
            HassContext | None: The response from Home Assistant if return_response is True.
                Otherwise, returns None.
        """
        return self.hassette.run_sync(self._api.call_service(domain, service, target, return_response, **data))

    def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data):
        """
        Turn on a specific entity in Home Assistant.

        Args:
            entity_id (str): The ID of the entity to turn on (e.g., "light.office").
            domain (str): The domain of the entity (default: "homeassistant").

        Returns:
            HassContext: The response context from Home Assistant.
        """
        return self.hassette.run_sync(self._api.turn_on(entity_id, domain, **data))

    def turn_off(self, entity_id: str, domain: str = "homeassistant"):
        """
        Turn off a specific entity in Home Assistant.

        Args:
            entity_id (str): The ID of the entity to turn off (e.g., "light.office").
            domain (str): The domain of the entity (default: "homeassistant").

        Returns:
            HassContext: The response context from Home Assistant.
        """
        return self.hassette.run_sync(self._api.turn_off(entity_id, domain))

    def toggle_service(self, entity_id: str, domain: str = "homeassistant"):
        """
        Toggle a specific entity in Home Assistant.

        Args:
            entity_id (str): The ID of the entity to toggle (e.g., "light.office").
            domain (str): The domain of the entity (default: "homeassistant").

        Returns:
            HassContext: The response context from Home Assistant.
        """
        return self.hassette.run_sync(self._api.toggle_service(entity_id, domain))

    def get_state_raw(self, entity_id: str):
        """Get the state of a specific entity.

        Args:
            entity_id (str): The ID of the entity to get the state for.

        Returns:
            HassStateDict: The state of the entity as raw data.
        """
        return self.hassette.run_sync(self._api.get_state_raw(entity_id))

    def entity_exists(self, entity_id: str):
        """Check if a specific entity exists.

        Args:
            entity_id (str): The ID of the entity to check.

        Returns:
            bool: True if the entity exists, False otherwise.
        """

        return self.hassette.run_sync(self._api.entity_exists(entity_id))

    def get_entity(self, entity_id: str, model: type[EntityT]):
        """Get an entity object for a specific entity.

        Args:
            entity_id (str): The ID of the entity to get.
            model (type[EntityT]): The model class to use for the entity.

        Returns:
            EntityT: The entity object.

        Note:
            This is not the same as calling get_state: get_state returns a BaseState subclass.
            This call returns an EntityState subclass, which wraps the state object and provides
            api methods for interacting with the entity.
        """
        return self.hassette.run_sync(self._api.get_entity(entity_id, model))

    def get_entity_or_none(self, entity_id: str, model: type[EntityT]):
        """Get an entity object for a specific entity, or None if it does not exist.

        Args:
            entity_id (str): The ID of the entity to get.
            model (type[EntityT]): The model class to use for the entity.

        Returns:
            EntityT | None: The entity object, or None if it does not exist.
        """
        return self.hassette.run_sync(self._api.get_entity_or_none(entity_id, model))

    def get_state(self, entity_id: str, model: type[StateT]):
        """Get the state of a specific entity.

        Args:
            entity_id (str): The ID of the entity to get the state for.
            model (type[StateT]): The model type to convert the state to.

        Returns:
            StateT: The state of the entity converted to the specified model type.
        """
        return self.hassette.run_sync(self._api.get_state(entity_id, model))

    def get_state_value(self, entity_id: str):
        """Get the state of a specific entity without converting it to a state object.

        Args:
            entity_id (str): The ID of the entity to get the state for.

        Returns:
            str: The state of the entity as raw data.

        Note:
            While most default methods in this library work with state objects for
            strong typing, this method is designed to return the raw state value,
            as it is likely overkill to convert it to a state object for simple state value retrieval.
        """
        return self.hassette.run_sync(self._api.get_state_value(entity_id))

    def get_state_value_typed(self, entity_id: str, model: type[BaseState[StateValueT]]):
        """Get the state of a specific entity as a converted state object.

        Args:
            entity_id (str): The ID of the entity to get the state for.
            model (type[BaseState[StateValueT]]): The model type to convert the state to.

        Returns:
            StateValueT: The state of the entity converted to the specified model type.

        Raises:
            TypeError: If the model is not a valid StateType subclass.

        Note:
            Instead of the default way of calling `get_state` involving a type, we assume that the
            average user only needs the raw value of the state value, without type safety.
        """

        return self.hassette.run_sync(self._api.get_state_value_typed(entity_id, model))

    def get_attribute(self, entity_id: str, attribute: str):
        """Get a specific attribute of an entity.

        Args:
            entity_id (str): The ID of the entity to get the attribute for.
            attribute (str): The name of the attribute to retrieve.

        Returns:
            Any: The value of the specified attribute, or None if it does not exist.
        """

        return self.hassette.run_sync(self._api.get_attribute(entity_id, attribute))

    def get_history(
        self,
        entity_id: str,
        start_time: PlainDateTime | Date | datetime | date | str,
        end_time: PlainDateTime | Date | datetime | date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ):
        """Get the history of a specific entity.

        Args:
            entity_id (str): The ID of the entity to get the history for.
            start_time (PlainDateTime | Date | datetime | date | str):
                The start time for the history range.
            end_time (PlainDateTime | Date | datetime | date | str | None, optional):
                The end time for the history range.
            significant_changes_only (bool, optional): Whether to only include significant changes.
            minimal_response (bool, optional): Whether to request a minimal response.
            no_attributes (bool, optional): Whether to exclude attributes from the response.

        Returns:
            list[HistoryEntry]: A list of history entries for the specified entity.
        """
        return self.hassette.run_sync(
            self._api.get_history(
                entity_id=entity_id,
                start_time=start_time,
                end_time=end_time,
                significant_changes_only=significant_changes_only,
                minimal_response=minimal_response,
                no_attributes=no_attributes,
            )
        )

    def get_histories(
        self,
        entity_ids: list[str],
        start_time: PlainDateTime | Date | datetime | date | str,
        end_time: PlainDateTime | Date | datetime | date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ):
        """Get the history for multiple entities.

        Args:
            entity_ids (list[str]): The IDs of the entities to get the history for.
            start_time (PlainDateTime | Date | datetime | date | str):
                The start time for the history range.
            end_time (PlainDateTime | Date | datetime | date | str | None, optional):
                The end time for the history range.
            significant_changes_only (bool, optional): Whether to only include significant changes.
            minimal_response (bool, optional): Whether to request a minimal response.
            no_attributes (bool, optional): Whether to exclude attributes from the response.

        Returns:
            dict[str, list[HistoryEntry]]: A dictionary mapping entity IDs to their respective history entries.
        """
        return self.hassette.run_sync(
            self._api.get_histories(
                entity_ids=entity_ids,
                start_time=start_time,
                end_time=end_time,
                significant_changes_only=significant_changes_only,
                minimal_response=minimal_response,
                no_attributes=no_attributes,
            )
        )

    def get_logbook(
        self,
        entity_id: str,
        start_time: PlainDateTime | Date | datetime | date | str,
        end_time: PlainDateTime | Date | datetime | date | str,
    ):
        """Get the logbook entries for a specific entity.

        Args:
            entity_id (str): The ID of the entity to get the logbook entries for.
            start_time (PlainDateTime | Date | datetime | date | str): The start time for the logbook range.
            end_time (PlainDateTime | Date | datetime | date | str): The end time for the logbook range.

        Returns:
            list[dict]: A list of logbook entries for the specified entity.
        """

        return self.hassette.run_sync(self._api.get_logbook(entity_id, start_time, end_time))

    def set_state(
        self,
        entity_id: str | StrEnum,
        state: str,
        attributes: dict[str, Any] | None = None,
    ):
        """Set the state of a specific entity.

        Args:
            entity_id (str | StrEnum): The ID of the entity to set the state for.
            state (str): The new state value to set.
            attributes (dict[str, Any], optional): Additional attributes to set for the entity.

        Returns:
            dict: The response from Home Assistant after setting the state.
        """

        return self.hassette.run_sync(self._api.set_state(entity_id, state, attributes))

    def get_camera_image(
        self,
        entity_id: str,
        timestamp: ZonedDateTime | PlainDateTime | Date | datetime | date | str | None = None,
    ):
        """Get the latest camera image for a specific entity.

        Args:
            entity_id (str): The ID of the camera entity to get the image for.
            timestamp (ZonedDateTime | PlainDateTime | Date | datetime | date | str | None, optional):
                The timestamp for the image. If None, the latest image is returned.

        Returns:
            bytes: The camera image data.
        """

        return self.hassette.run_sync(self._api.get_camera_image(entity_id, timestamp))

    def get_calendars(self):
        """Get the list of calendars.

        Returns:
            list[dict]: The calendars configured in Home Assistant.
        """

        return self.hassette.run_sync(self._api.get_calendars())

    def get_calendar_events(
        self,
        calendar_id: str,
        start_time: PlainDateTime | Date | datetime | date | str,
        end_time: PlainDateTime | Date | datetime | date | str,
    ):
        """Get events from a specific calendar.

        Args:
            calendar_id (str): The ID of the calendar to get events from.
            start_time (PlainDateTime | Date | datetime | date | str): The start time for the event range.
            end_time (PlainDateTime | Date | datetime | date | str): The end time for the event range.

        Returns:
            list[dict]: A list of calendar events.
        """

        return self.hassette.run_sync(
            self._api.get_calendar_events(
                calendar_id=calendar_id,
                start_time=start_time,
                end_time=end_time,
            )
        )

    def render_template(
        self,
        template: str,
        variables: dict | None = None,
    ):
        """Render a template with given variables.

        Args:
            template (str): The template string to render.
            variables (dict, optional): Variables to use in the template.

        Returns:
            str: The rendered template result.
        """
        return self.hassette.run_sync(self._api.render_template(template, variables))

    def delete_entity(self, entity_id: str):
        """Delete a specific entity.

        Args:
            entity_id (str): The ID of the entity to delete.

        Raises:
            RuntimeError: If the deletion fails.
        """

        self.hassette.run_sync(self._api.delete_entity(entity_id))


def orjson_dump(data: Any) -> str:
    return orjson.dumps(data, default=str).decode("utf-8")


def clean_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Converts values to strings where needed and removes keys with None values."""

    def clean_value(val: Any) -> Any:
        if val is None:
            return None

        if isinstance(val, bool):
            return str(val).lower()

        if isinstance(val, (PlainDateTime | ZonedDateTime | Instant | Date)):
            return val.format_common_iso()

        if isinstance(val, (int | float | str)):
            if isinstance(val, str) and not val.strip():
                return None
            return val

        if isinstance(val, datetime):
            return val.isoformat()

        if isinstance(val, Mapping):
            return {k: clean_value(v) for k, v in val.items() if v is not None}

        if isinstance(val, Iterable) and not isinstance(val, str | bytes):
            return [clean_value(v) for v in val if v is not None]

        return str(val)

    return {k: cleaned for k, v in kwargs.items() if (cleaned := clean_value(v)) is not None}
