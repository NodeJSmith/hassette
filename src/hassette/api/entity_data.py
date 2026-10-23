"""Entity state, history, and REST data methods of :class:`~hassette.api.api.Api`."""

import typing
from collections.abc import Coroutine  # noqa: TC003 — needed at runtime for annotation inspection
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from whenever import Date, PlainDateTime, ZonedDateTime

from hassette.const.misc import FalseySentinel
from hassette.event_handling.accessors import get_path
from hassette.exceptions import EntityNotFoundError
from hassette.models.entities import BaseEntity
from hassette.models.history import HistoryEntry
from hassette.utils.await_guard import guard_await
from hassette.utils.request_utils import format_time_param
from hassette.utils.source_capture import capture_source_location

if typing.TYPE_CHECKING:
    import aiohttp

    from hassette import Hassette
    from hassette.core.api_resource import ApiResource
    from hassette.events import HassStateDict
    from hassette.models.entities import EntityT
    from hassette.models.states import BaseState
    from hassette.resources.base import Resource


class ApiEntityDataMixin:
    """Entity state, history, logbook, calendar, and template methods on :class:`~hassette.api.api.Api`."""

    # Provided by Resource / Api; declared here for type narrowing within the mixin.
    hassette: "Hassette"
    parent: "Resource | None"
    _api_service: "ApiResource"

    if typing.TYPE_CHECKING:

        async def rest_request(
            self,
            method: str,
            url: str,
            params: dict[str, Any] | None = None,
            data: dict[str, Any] | None = None,
            suppress_error_message: bool = False,
            **kwargs: Any,
        ) -> aiohttp.ClientResponse:
            """Type-checking stub for :meth:`Api.rest_request`, which sends a REST request to Home Assistant."""
            ...

        async def get_rest_request(
            self, url: str, params: dict[str, Any] | None = None, **kwargs: Any
        ) -> aiohttp.ClientResponse:
            """Type-checking stub for :meth:`Api.get_rest_request`, which sends a GET request."""
            ...

        async def post_rest_request(
            self, url: str, data: dict[str, Any] | None = None, **kwargs: Any
        ) -> aiohttp.ClientResponse:
            """Type-checking stub for :meth:`Api.post_rest_request`, which sends a POST request."""
            ...

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
