"""Sync recording facade for RecordingApi.

Provides synchronous versions of RecordingApi's write and read methods. Write
methods append to the parent RecordingApi's `calls` list; read methods delegate
to the state proxy synchronously. Unimplemented methods raise NotImplementedError
with tailored guidance.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from hassette.exceptions import EntityNotFoundError
from hassette.models.entities.base import BaseEntity
from hassette.models.services import ServiceResponse
from hassette.models.states.base import BaseState, Context
from hassette.test_utils.api_call import ApiCall

if TYPE_CHECKING:
    from hassette.test_utils.recording_api import RecordingApi


class _RecordingSyncFacade:
    """Synchronous recording facade for RecordingApi.

    Instances are created by RecordingApi.__init__ and share the parent's
    `calls` list via the `_parent` reference. Users access it via `harness.api_recorder.sync`
    (which is `RecordingApi.sync`).
    """

    _parent: "RecordingApi"

    def __init__(self, parent: "RecordingApi") -> None:
        self._parent = parent

    # ------------------------------------------------------------------
    # Write methods — append ApiCall synchronously to parent.calls
    # ------------------------------------------------------------------

    def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data) -> None:
        """Record a turn_on call synchronously."""
        entity_id = str(entity_id)
        self._parent.calls.append(
            ApiCall(
                method="turn_on",
                args=(entity_id,),
                kwargs={"entity_id": entity_id, "domain": domain, **data},
            )
        )

    def turn_off(self, entity_id: str | StrEnum, domain: str = "homeassistant") -> None:
        """Record a turn_off call synchronously."""
        entity_id = str(entity_id)
        self._parent.calls.append(
            ApiCall(
                method="turn_off",
                args=(entity_id,),
                kwargs={"entity_id": entity_id, "domain": domain},
            )
        )

    def toggle_service(self, entity_id: str | StrEnum, domain: str = "homeassistant") -> None:
        """Record a toggle_service call synchronously."""
        entity_id = str(entity_id)
        self._parent.calls.append(
            ApiCall(
                method="toggle_service",
                args=(entity_id,),
                kwargs={"entity_id": entity_id, "domain": domain},
            )
        )

    def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: bool | None = False,
        **data,
    ) -> ServiceResponse | None:
        """Record a call_service call synchronously. Returns stub ServiceResponse when return_response=True."""
        self._parent.calls.append(
            ApiCall(
                method="call_service",
                args=(domain, service),
                kwargs={
                    "domain": domain,
                    "service": service,
                    "target": target,
                    "return_response": return_response,
                    **data,
                },
            )
        )
        if return_response:
            return ServiceResponse(context=Context(id=None, parent_id=None, user_id=None))
        return None

    def set_state(
        self,
        entity_id: str | StrEnum,
        state: Any,
        attributes: dict[str, Any] | None = None,
    ) -> dict:
        """Record a set_state call synchronously. Returns an empty dict stub."""
        entity_id = str(entity_id)
        self._parent.calls.append(
            ApiCall(
                method="set_state",
                args=(entity_id, state),
                kwargs={"entity_id": entity_id, "state": state, "attributes": attributes},
            )
        )
        return {}

    def fire_event(self, event_type: str, event_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Record a fire_event call synchronously. Returns an empty dict stub."""
        self._parent.calls.append(
            ApiCall(
                method="fire_event",
                args=(event_type,),
                kwargs={"event_type": event_type, "event_data": event_data},
            )
        )
        return {}

    # ------------------------------------------------------------------
    # Read methods — delegate to parent's state-proxy helpers synchronously
    # ------------------------------------------------------------------

    def get_state(self, entity_id: str) -> BaseState:
        """Return the typed state for entity_id. Raises EntityNotFoundError if not seeded."""
        raw = self._parent._get_raw_state(entity_id)
        return self._parent._convert_state(raw, entity_id)

    def get_states(self) -> list[BaseState]:
        """Return typed states for all seeded entities."""
        items = list(self._parent._state_proxy.states.items())
        return [self._parent._convert_state(raw, eid) for eid, raw in items]

    def get_entity(self, entity_id: str, model: type[Any] = BaseState) -> BaseState:
        """Return the typed state for entity_id. Raises EntityNotFoundError if not seeded."""
        raw = self._parent._get_raw_state(entity_id)
        if model is not BaseState and issubclass(model, BaseEntity):
            return cast("BaseState", model.model_validate({"state": raw}))
        return self._parent._convert_state(raw, entity_id)

    def get_entity_or_none(self, entity_id: str, model: type[Any] = BaseState) -> BaseState | None:
        """Return the typed state for entity_id, or None if not seeded."""
        try:
            return self.get_entity(entity_id, model)
        except EntityNotFoundError:
            return None

    def entity_exists(self, entity_id: str) -> bool:
        """Return True if entity_id is seeded in the StateProxy."""
        return entity_id in self._parent._state_proxy.states

    def get_state_or_none(self, entity_id: str) -> BaseState | None:
        """Return the typed state for entity_id, or None if not seeded."""
        try:
            return self.get_state(entity_id)
        except EntityNotFoundError:
            return None

    # ------------------------------------------------------------------
    # State-conversion methods — raise NotImplementedError with tailored message
    # ------------------------------------------------------------------

    def get_state_value(self, entity_id: str) -> Any:
        """Not implemented — raises NotImplementedError with tailored guidance."""
        raise NotImplementedError(
            "RecordingApi.sync.get_state_value is not implemented on the test facade. "
            "Call `harness.api_recorder.sync.get_state(entity_id)` and read the returned state directly."
        )

    def get_state_value_typed(self, entity_id: str) -> Any:
        """Not implemented — raises NotImplementedError with tailored guidance."""
        raise NotImplementedError(
            "RecordingApi.sync.get_state_value_typed is not implemented on the test facade. "
            "Call `harness.api_recorder.sync.get_state(entity_id)` and read the returned state directly."
        )

    def get_attribute(self, entity_id: str, attribute: str) -> Any:
        """Not implemented — raises NotImplementedError with tailored guidance."""
        raise NotImplementedError(
            "RecordingApi.sync.get_attribute is not implemented on the test facade. "
            "Call `harness.api_recorder.sync.get_state(entity_id)` and read the returned state directly."
        )

    # ------------------------------------------------------------------
    # Remaining ApiSyncFacade public methods — raise NotImplementedError
    # These explicit stubs exist to satisfy the drift-detection test.
    # ------------------------------------------------------------------

    def ws_send_and_wait(self, **data: Any) -> Any:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.ws_send_and_wait is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def ws_send_json(self, **data: Any) -> None:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.ws_send_json is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def rest_request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.rest_request is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_rest_request(self, url: str, **kwargs: Any) -> Any:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_rest_request is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def post_rest_request(self, url: str, **kwargs: Any) -> Any:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.post_rest_request is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def delete_rest_request(self, url: str, **kwargs: Any) -> Any:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.delete_rest_request is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_states_raw(self) -> list[dict]:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_states_raw is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_states_iterator(self) -> Any:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_states_iterator is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_config(self) -> dict[str, Any]:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_config is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_services(self) -> dict[str, Any]:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_services is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_panels(self) -> dict[str, Any]:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_panels is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_state_raw(self, entity_id: str) -> dict:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_state_raw is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_history(self, entity_id: str, *args: Any, **kwargs: Any) -> list:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_history is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_histories(self, entity_ids: list[str], *args: Any, **kwargs: Any) -> dict:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_histories is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_logbook(self, entity_id: str, *args: Any, **kwargs: Any) -> list[dict]:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_logbook is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_camera_image(self, entity_id: str, *args: Any, **kwargs: Any) -> bytes:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_camera_image is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_calendars(self) -> list[dict]:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_calendars is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def get_calendar_events(self, calendar_id: str, *args: Any, **kwargs: Any) -> list[dict]:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.get_calendar_events is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def render_template(self, template: str, variables: dict | None = None) -> str:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.render_template is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    def delete_entity(self, entity_id: str) -> None:
        """Not implemented — raises NotImplementedError."""
        raise NotImplementedError(
            "RecordingApi.sync.delete_entity is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    # ------------------------------------------------------------------
    # Fallback for any future methods not yet explicitly stubbed
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """Raise NotImplementedError for public attributes not defined on _RecordingSyncFacade.

        Private attributes fall through to the default AttributeError so that Python
        machinery works correctly. All known public methods from ``ApiSyncFacade``
        are explicitly stubbed (see below) to satisfy the drift-detection test and
        provide per-method error messages. This fallback catches any public attribute
        that is not a stubbed method — typically a typo or a brand-new method on
        ``ApiSyncFacade`` that the drift test is about to flag.
        """
        if name.startswith("_"):
            raise AttributeError(name)

        raise NotImplementedError(
            f"RecordingApi.sync.{name} is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )
