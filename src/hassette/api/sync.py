import typing
from enum import StrEnum
from typing import Any

from whenever import Date, PlainDateTime, ZonedDateTime

from hassette.models.entities import EntityT
from hassette.resources.base import Resource

if typing.TYPE_CHECKING:
    from hassette import Api, Hassette
    from hassette.models.states import BaseState, StateT, StateValueT


class ApiSyncFacade(Resource):
    """Synchronous facade for the API service.

    This class provides synchronous methods that wrap the asynchronous methods of the Api class,
    allowing for blocking calls in a synchronous context.

    It is important to note that these methods should not be called from within an existing event loop,
    as they will raise a RuntimeError in such cases. Use the asynchronous methods directly when operating
    within an event loop.
    """

    _api: "Api"

    @classmethod
    def create(cls, hassette: "Hassette", api: "Api"):
        inst = cls(hassette, parent=api)
        inst._api = api
        inst.mark_ready(reason="Synchronous API facade initialized")
        return inst

    def ws_send_and_wait(self, **data: Any):
        """Send a WebSocket message and wait for a response."""
        return self.task_bucket.run_sync(self._api.ws_send_and_wait(**data))

    def ws_send_json(self, **data: Any):
        """Send a WebSocket message without waiting for a response."""
        return self.task_bucket.run_sync(self._api.ws_send_json(**data))

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
            method: The HTTP method to use (e.g., "GET", "POST").
            url: The URL endpoint for the request.
            params: Query parameters for the request.
            data: JSON payload for the request.
            suppress_error_message: Whether to suppress error messages.

        Returns:
            The response from the API.
        """
        return self.task_bucket.run_sync(
            self._api.rest_request(
                method, url, params=params, data=data, suppress_error_message=suppress_error_message, **kwargs
            )
        )

    def get_rest_request(self, url: str, params: dict[str, Any] | None = None, **kwargs):
        """Make a GET request to the Home Assistant API.

        Args:
            url: The URL endpoint for the request.
            params: Query parameters for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            The response from the API.
        """
        return self.task_bucket.run_sync(self._api.get_rest_request(url, params=params, **kwargs))

    def post_rest_request(self, url: str, data: dict[str, Any] | None = None, **kwargs):
        """Make a POST request to the Home Assistant API.

        Args:
            url: The URL endpoint for the request.
            data: JSON payload for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            The response from the API.
        """
        return self.task_bucket.run_sync(self._api.post_rest_request(url, data=data, **kwargs))

    def delete_rest_request(self, url: str, **kwargs):
        """Make a DELETE request to the Home Assistant API.

        Args:
            url: The URL endpoint for the request.
            kwargs: Additional keyword arguments to pass to the request.

        Returns:
            The response from the API.
        """
        return self.task_bucket.run_sync(self._api.delete_rest_request(url, **kwargs))

    def get_states_raw(self):
        """Get all entities in Home Assistant as raw dictionaries.

        Returns:
            A list of states as dictionaries.
        """
        return self.task_bucket.run_sync(self._api.get_states_raw())

    def get_states(self):
        """Get all entities in Home Assistant.

        Returns:
            A list of states, either as dictionaries or converted to state objects.
        """
        return self.task_bucket.run_sync(self._api.get_states())

    def get_config(self):
        """Get the Home Assistant configuration.

        Returns:
            The configuration data.
        """
        return self.task_bucket.run_sync(self._api.get_config())

    def get_services(self):
        """Get the available services in Home Assistant.

        Returns:
            The services data.
        """
        return self.task_bucket.run_sync(self._api.get_services())

    def get_panels(self):
        """Get the available panels in Home Assistant.

        Returns:
            The panels data.
        """
        return self.task_bucket.run_sync(self._api.get_panels())

    def fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ):
        """Fire a custom event in Home Assistant.

        Args:
            event_type: The type of the event to fire (e.g., "custom_event").
            event_data: Additional data to include with the event.

        Returns:
            The response from Home Assistant.
        """
        return self.task_bucket.run_sync(self._api.fire_event(event_type, event_data))

    def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: bool | None = False,
        **data,
    ):
        """Call a Home Assistant service.

        Args:
            domain: The domain of the service (e.g., "light").
            service: The name of the service to call (e.g., "turn_on").
            target: Target entity IDs or areas.
            return_response: Whether to return the response from Home Assistant. Defaults to False.
            **kwargs: Additional data to send with the service call.

        Returns:
            The response from Home Assistant if return_response is True. Otherwise, returns None.
        """
        return self.task_bucket.run_sync(self._api.call_service(domain, service, target, return_response, **data))

    def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data):
        """Turn on a specific entity in Home Assistant.

        Args:
            entity_id: The ID of the entity to turn on (e.g., "light.office").
            domain: The domain of the entity (default: "homeassistant").
        """
        return self.task_bucket.run_sync(self._api.turn_on(entity_id, domain, **data))

    def turn_off(self, entity_id: str, domain: str = "homeassistant"):
        """Turn off a specific entity in Home Assistant.

        Args:
            entity_id: The ID of the entity to turn off (e.g., "light.office").
            domain: The domain of the entity (default: "homeassistant").

        """
        return self.task_bucket.run_sync(self._api.turn_off(entity_id, domain))

    def toggle_service(self, entity_id: str, domain: str = "homeassistant"):
        """Toggle a specific entity in Home Assistant.

        Args:
            entity_id: The ID of the entity to toggle (e.g., "light.office").
            domain: The domain of the entity (default: "homeassistant").

        """
        return self.task_bucket.run_sync(self._api.toggle_service(entity_id, domain))

    def get_state_raw(self, entity_id: str):
        """Get the state of a specific entity.

        Args:
            entity_id: The ID of the entity to get the state for.

        Returns:
            The state of the entity as raw data.
        """
        return self.task_bucket.run_sync(self._api.get_state_raw(entity_id))

    def entity_exists(self, entity_id: str):
        """Check if a specific entity exists.

        Args:
            entity_id: The ID of the entity to check.

        Returns:
            True if the entity exists, False otherwise.
        """

        return self.task_bucket.run_sync(self._api.entity_exists(entity_id))

    def get_entity(self, entity_id: str, model: type[EntityT]):
        """Get an entity object for a specific entity.

        Args:
            entity_id: The ID of the entity to get.
            model: The model class to use for the entity.

        Returns:
            The entity object.
        """
        return self.task_bucket.run_sync(self._api.get_entity(entity_id, model))

    def get_entity_or_none(self, entity_id: str, model: type[EntityT]):
        """Get an entity object for a specific entity, or None if it does not exist.

        Args:
            entity_id: The ID of the entity to get.
            model: The model class to use for the entity.

        Returns:
            The entity object, or None if it does not exist.
        """
        return self.task_bucket.run_sync(self._api.get_entity_or_none(entity_id, model))

    def get_state(self, entity_id: str, model: type["StateT"]):
        """Get the state of a specific entity.

        Args:
            entity_id: The ID of the entity to get the state for.
            model: The model type to convert the state to.

        Returns:
            The state of the entity converted to the specified model type.
        """
        return self.task_bucket.run_sync(self._api.get_state(entity_id, model))

    def get_state_value(self, entity_id: str):
        """Get the state of a specific entity without converting it to a state object.

        Args:
            entity_id: The ID of the entity to get the state for.

        Returns:
            The state of the entity as raw data.
        """
        return self.task_bucket.run_sync(self._api.get_state_value(entity_id))

    def get_state_value_typed(self, entity_id: str, model: type["BaseState[StateValueT]"]):
        """Get the state of a specific entity as a converted state object.

        Args:
            entity_id: The ID of the entity to get the state for.
            model: The model type to convert the state to.

        Returns:
            The state of the entity converted to the specified model type.

        Raises:
            TypeError: If the model is not a valid StateType subclass.
        """

        return self.task_bucket.run_sync(self._api.get_state_value_typed(entity_id, model))

    def get_attribute(self, entity_id: str, attribute: str):
        """Get a specific attribute of an entity.

        Args:
            entity_id: The ID of the entity to get the attribute for.
            attribute: The name of the attribute to retrieve.

        Returns:
            The value of the specified attribute, or None if it does not exist.
        """

        return self.task_bucket.run_sync(self._api.get_attribute(entity_id, attribute))

    def get_history(
        self,
        entity_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ):
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
        return self.task_bucket.run_sync(
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
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ):
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
        return self.task_bucket.run_sync(
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
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str,
    ):
        """Get the logbook entries for a specific entity.

        Args:
            entity_id: The ID of the entity to get the logbook entries for.
            start_time: The start time for the logbook range.
            end_time: The end time for the logbook range.

        Returns:
            A list of logbook entries for the specified entity.
        """

        return self.task_bucket.run_sync(self._api.get_logbook(entity_id, start_time, end_time))

    def set_state(
        self,
        entity_id: str | StrEnum,
        state: str,
        attributes: dict[str, Any] | None = None,
    ):
        """Set the state of a specific entity.

        Args:
            entity_id: The ID of the entity to set the state for.
            state: The new state value to set.
            attributes: Additional attributes to set for the entity.

        Returns:
            The response from Home Assistant after setting the state.
        """

        return self.task_bucket.run_sync(self._api.set_state(entity_id, state, attributes))

    def get_camera_image(
        self,
        entity_id: str,
        timestamp: PlainDateTime | ZonedDateTime | Date | str | None = None,
    ):
        """Get the latest camera image for a specific entity.

        Args:
            entity_id: The ID of the camera entity to get the image for.
            timestamp: The timestamp for the image. If None, the latest image is returned.

        Returns:
            The camera image data.
        """

        return self.task_bucket.run_sync(self._api.get_camera_image(entity_id, timestamp))

    def get_calendars(self):
        """Get the list of calendars.

        Returns:
            The calendars configured in Home Assistant.
        """

        return self.task_bucket.run_sync(self._api.get_calendars())

    def get_calendar_events(
        self,
        calendar_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str,
    ):
        """Get events from a specific calendar.

        Args:
            calendar_id: The ID of the calendar to get events from.
            start_time: The start time for the event range.
            end_time: The end time for the event range.

        Returns:
            A list of calendar events.
        """

        return self.task_bucket.run_sync(
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
            template: The template string to render.
            variables: Variables to use in the template.

        Returns:
            The rendered template result.
        """
        return self.task_bucket.run_sync(self._api.render_template(template, variables))

    def delete_entity(self, entity_id: str):
        """Delete a specific entity.

        Args:
            entity_id: The ID of the entity to delete.

        Raises:
            RuntimeError: If the deletion fails.
        """

        self.task_bucket.run_sync(self._api.delete_entity(entity_id))
