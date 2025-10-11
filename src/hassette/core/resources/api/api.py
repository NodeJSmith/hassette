import typing
from enum import StrEnum
from typing import Any, Literal, overload

import aiohttp
from whenever import Date, PlainDateTime, SystemDateTime

from hassette.core.resources.api.sync import ApiSyncFacade
from hassette.core.resources.base import Resource
from hassette.exceptions import EntityNotFoundError
from hassette.models.entities import BaseEntity, EntityT
from hassette.models.history import HistoryEntry
from hassette.models.services import ServiceResponse
from hassette.models.states import BaseState, StateT, StateUnion, StateValueT, try_convert_state

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.services.api_service import _ApiService
    from hassette.events import HassStateDict


class Api(Resource):
    """API service for interacting with Home Assistant.

    This service provides methods to interact with the Home Assistant API, including making REST requests,
    managing WebSocket connections, and handling entity states.
    """

    sync: ApiSyncFacade
    """Synchronous facade for the API service."""

    _api_service: "_ApiService"
    """Internal API service instance."""

    @classmethod
    def create(cls, hassette: "Hassette", parent: "Resource"):
        inst = cls(hassette=hassette, parent=parent)
        inst._api_service = inst.hassette._api_service
        inst.sync = inst.add_child(ApiSyncFacade, api=inst)
        inst.mark_ready(reason="API initialized")
        return inst

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.log_level

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
            method (str): The HTTP method to use (e.g., "GET", "POST").
            url (str): The URL endpoint for the request.
            params (dict[str, Any], optional): Query parameters for the request.
            data (dict[str, Any], optional): JSON payload for the request.
            suppress_error_message (bool, optional): Whether to suppress error messages.

        Returns:
            aiohttp.ClientResponse: The response from the API.
        """
        return await self._api_service._rest_request(
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

    async def get_states_raw(self) -> list["HassStateDict"]:
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
        """
        Call a Home Assistant service.

        Args:
            domain (str): The domain of the service (e.g., "light").
            service (str): The name of the service to call (e.g., "turn_on").
            target (dict[str, str], optional): Target entity IDs or areas.
            return_response (bool, optional): Whether to return the response from Home Assistant. Defaults to False.
            **kwargs: Additional data to send with the service call.

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
        """
        Turn on a specific entity in Home Assistant.

        Args:
            entity_id (str): The ID of the entity to turn on (e.g., "light.office").
            domain (str): The domain of the entity (default: "homeassistant").

        Returns:
            None
        """
        entity_id = str(entity_id)

        self.logger.debug("Turning on entity %s", entity_id)
        return await self.call_service(domain=domain, service="turn_on", target={"entity_id": entity_id}, **data)

    async def turn_off(self, entity_id: str, domain: str = "homeassistant"):
        """
        Turn off a specific entity in Home Assistant.

        Args:
            entity_id (str): The ID of the entity to turn off (e.g., "light.office").
            domain (str): The domain of the entity (default: "homeassistant").

        Returns:
            None
        """
        self.logger.debug("Turning off entity %s", entity_id)
        return await self.call_service(domain=domain, service="turn_off", target={"entity_id": entity_id})

    async def toggle_service(self, entity_id: str, domain: str = "homeassistant"):
        """
        Toggle a specific entity in Home Assistant.

        Args:
            entity_id (str): The ID of the entity to toggle (e.g., "light.office").
            domain (str): The domain of the entity (default: "homeassistant").

        Returns:
            None
        """
        self.logger.debug("Toggling entity %s", entity_id)
        return await self.call_service(domain=domain, service="toggle", target={"entity_id": entity_id})

    async def get_state_raw(self, entity_id: str) -> "HassStateDict":
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
        start_time: PlainDateTime | SystemDateTime | Date | str,
        end_time: PlainDateTime | SystemDateTime | Date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> list[HistoryEntry]:
        """Get the history of a specific entity.

        Args:
            entity_id (str): The ID of the entity to get the history for.
            start_time (PlainDateTime | SystemDateTime | Date | str):
                The start time for the history range.
            end_time (PlainDateTime | SystemDateTime | Date | str | None, optional):
                The end time for the history range.
            significant_changes_only (bool, optional): Whether to only include significant changes.
            minimal_response (bool, optional): Whether to request a minimal response.
            no_attributes (bool, optional): Whether to exclude attributes from the response.

        Returns:
            list[HistoryEntry]: A list of history entries for the specified entity.
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
        start_time: PlainDateTime | SystemDateTime | Date | str,
        end_time: PlainDateTime | SystemDateTime | Date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> dict[str, list[HistoryEntry]]:
        """Get the history for multiple entities.

        Args:
            entity_ids (list[str]): The IDs of the entities to get the history for.
            start_time (PlainDateTime | SystemDateTime | Date | str):
                The start time for the history range.
            end_time (PlainDateTime | SystemDateTime | Date | str | None, optional):
                The end time for the history range.
            significant_changes_only (bool, optional): Whether to only include significant changes.
            minimal_response (bool, optional): Whether to request a minimal response.
            no_attributes (bool, optional): Whether to exclude attributes from the response.

        Returns:
            dict[str, list[HistoryEntry]]: A dictionary mapping entity IDs to their respective history entries.
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
        start_time: PlainDateTime | SystemDateTime | Date | str,
        end_time: PlainDateTime | SystemDateTime | Date | str,
    ) -> list[dict]:
        """Get the logbook entries for a specific entity.

        Args:
            entity_id (str): The ID of the entity to get the logbook entries for.
            start_time (PlainDateTime | SystemDateTime | Date | str): The start time for the logbook range.
            end_time (PlainDateTime | SystemDateTime | Date | str): The end time for the logbook range.

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
        timestamp: PlainDateTime | SystemDateTime | Date | str | None = None,
    ) -> bytes:
        """Get the latest camera image for a specific entity.

        Args:
            entity_id (str): The ID of the camera entity to get the image for.
            timestamp (PlainDateTime | SystemDateTime | Date | str | None, optional):
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
        start_time: PlainDateTime | SystemDateTime | Date | str,
        end_time: PlainDateTime | SystemDateTime | Date | str,
    ) -> list[dict]:
        """Get events from a specific calendar.

        Args:
            calendar_id (str): The ID of the calendar to get events from.
            start_time (PlainDateTime | SystemDateTime | Date | str): The start time for the event range.
            end_time (PlainDateTime | SystemDateTime | Date | str): The end time for the event range.

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
