"""RecordingApi — test double for hassette.api.Api.

Records write-method calls for test assertions. Delegates read methods to
StateProxy. Implements ApiProtocol for static conformance checking.

Intended for use with AppTestHarness. Users who need full HTTP-level
fidelity should use a full integration test with a live HA connection.
"""

import copy
from collections.abc import Generator
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, Never, Protocol, cast, runtime_checkable

import aiohttp
from slugify import slugify as _py_slugify
from whenever import Date, PlainDateTime, ZonedDateTime

from hassette.const.misc import FalseySentinel
from hassette.exceptions import EntityNotFoundError, FailedMessageError
from hassette.models.entities.base import BaseEntity
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
from hassette.models.states.base import BaseState, Context
from hassette.resources.base import Resource
from hassette.test_utils.api_call import ApiCall
from hassette.test_utils.sync_facade import _RecordingSyncFacade

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.state_proxy import StateProxy
    from hassette.events import HassStateDict


# ---------------------------------------------------------------------------
# Helper domain constants
# ---------------------------------------------------------------------------

_SUPPORTED_HELPER_DOMAINS: frozenset[str] = frozenset(
    {
        "input_boolean",
        "input_number",
        "input_text",
        "input_select",
        "input_datetime",
        "input_button",
        "counter",
        "timer",
    }
)

# Hand-maintained dispatch table mapping each Record class to (domain, deep_copy).
# Adding a 9th helper domain requires adding an entry here. A future refactor could
# add `domain: ClassVar[str]` to each Record model and auto-populate this dict, but
# that is out of scope for this PR.
#
# ``deep_copy`` — set to True for record types that contain nested mutable fields.
# Currently only ``InputSelectRecord`` requires deep copies: its ``options: list[str]``
# field would alias the stored record's list under a shallow copy, allowing a caller's
# ``record.options.append(...)`` to silently corrupt harness state. All other domains
# use scalar-only fields and are safe with shallow copies.
_RECORD_TYPE_TO_DOMAIN: dict[type, tuple[str, bool]] = {
    InputBooleanRecord: ("input_boolean", False),
    InputNumberRecord: ("input_number", False),
    InputTextRecord: ("input_text", False),
    InputSelectRecord: ("input_select", True),
    InputDatetimeRecord: ("input_datetime", False),
    InputButtonRecord: ("input_button", False),
    CounterRecord: ("counter", False),
    TimerRecord: ("timer", False),
}

if {domain for domain, _ in _RECORD_TYPE_TO_DOMAIN.values()} != _SUPPORTED_HELPER_DOMAINS:
    raise ValueError(
        "_RECORD_TYPE_TO_DOMAIN and _SUPPORTED_HELPER_DOMAINS must enumerate the same set of helper domains"
    )


def _slugify_helper_name(name: str | None) -> str:
    """Convert an HA helper name into its stored id, mirroring homeassistant.util.slugify.

    Three branches:

    - Returns ``""`` for ``None`` or empty-string input — matches HA, where
      an unnamed helper has no slug to derive an id from.
    - Returns ``"unknown"`` when a non-empty input slugifies to an empty
      string (e.g. ``"%%%"``) — matches HA's fallback in ``util.slugify``.
    - Otherwise returns the ``python-slugify`` output with ``separator="_"``.

    This is harness-only logic. Production ``Api.create_*`` methods do NOT
    call this; they let HA slugify server-side.
    """
    if name == "" or name is None:
        return ""
    slug = _py_slugify(name, separator="_")
    return "unknown" if slug == "" else slug


def _generate_helper_id(existing_ids: set[str], name: str) -> str:
    """Generate a unique helper ID, mirroring HA's IDManager.generate_id behaviour.

    Computes base_id = _slugify_helper_name(name). If base_id is not in
    existing_ids, returns it. Otherwise, appends _2, _3, ... until unused.
    """
    base_id = _slugify_helper_name(name)
    if base_id not in existing_ids:
        return base_id
    n = 2
    while True:
        candidate = f"{base_id}_{n}"
        if candidate not in existing_ids:
            return candidate
        n += 1


@runtime_checkable
class ApiProtocol(Protocol):
    """Protocol covering the public async interface of hassette.api.Api.

    RecordingApi conformance is verified by Pyright (structural) and
    ``test_recording_api_protocol_parity.py`` (behavioral).
    """

    # WebSocket methods
    async def ws_send_and_wait(self, **data: Any) -> Any: ...
    async def ws_send_json(self, **data: Any) -> None: ...

    # REST methods
    async def rest_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        suppress_error_message: bool = False,
        **kwargs,
    ) -> aiohttp.ClientResponse: ...
    async def get_rest_request(
        self, url: str, params: dict[str, Any] | None = None, **kwargs
    ) -> aiohttp.ClientResponse: ...
    async def post_rest_request(
        self, url: str, data: dict[str, Any] | None = None, **kwargs
    ) -> aiohttp.ClientResponse: ...
    async def delete_rest_request(self, url: str, **kwargs) -> aiohttp.ClientResponse: ...

    # Write methods
    async def turn_on(self, entity_id: str | StrEnum, domain: str = ..., **data) -> None: ...
    async def turn_off(self, entity_id: str | StrEnum, domain: str = ...) -> None: ...
    async def toggle_service(self, entity_id: str | StrEnum, domain: str = ...) -> None: ...
    async def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: bool | None = False,
        **data: Any,
    ) -> ServiceResponse | None: ...
    async def set_state(
        self,
        entity_id: str | StrEnum,
        state: Any,
        attributes: dict[str, Any] | None = None,
    ) -> dict: ...
    async def fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    async def delete_entity(self, entity_id: str) -> None: ...

    # Read methods
    async def get_state(self, entity_id: str) -> BaseState: ...
    async def get_state_raw(self, entity_id: str) -> "HassStateDict": ...
    async def get_states(self) -> list[BaseState]: ...
    async def get_states_raw(self) -> list["HassStateDict"]: ...
    async def get_states_iterator(self) -> Generator[BaseState[Any], Any, None]: ...
    async def get_entity(self, entity_id: str, model: type[BaseEntity]) -> BaseEntity: ...
    async def get_entity_or_none(self, entity_id: str, model: type[BaseEntity]) -> BaseEntity | None: ...
    async def entity_exists(self, entity_id: str) -> bool: ...
    async def get_state_or_none(self, entity_id: str) -> BaseState | None: ...
    async def get_state_value(self, entity_id: str) -> Any: ...
    async def get_state_value_typed(self, entity_id: str) -> Any: ...
    async def get_attribute(self, entity_id: str, attribute: str) -> Any | FalseySentinel: ...

    # Configuration and metadata
    async def get_config(self) -> dict[str, Any]: ...
    async def get_services(self) -> dict[str, Any]: ...
    async def get_panels(self) -> dict[str, Any]: ...

    # History, logbook, calendars, camera, template
    async def get_history(
        self,
        entity_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> list[HistoryEntry]: ...
    async def get_histories(
        self,
        entity_ids: list[str],
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> dict[str, list[HistoryEntry]]: ...
    async def get_logbook(
        self,
        entity_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str,
    ) -> list[dict]: ...
    async def get_calendars(self) -> list[dict]: ...
    async def get_calendar_events(
        self,
        calendar_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str,
    ) -> list[dict]: ...
    async def get_camera_image(
        self,
        entity_id: str,
        timestamp: PlainDateTime | ZonedDateTime | Date | str | None = None,
    ) -> bytes: ...
    async def render_template(
        self,
        template: str,
        variables: dict | None = None,
    ) -> str: ...

    # input_boolean CRUD
    async def list_input_booleans(self) -> list[InputBooleanRecord]: ...
    async def create_input_boolean(self, params: CreateInputBooleanParams) -> InputBooleanRecord: ...
    async def update_input_boolean(self, helper_id: str, params: UpdateInputBooleanParams) -> InputBooleanRecord: ...
    async def delete_input_boolean(self, helper_id: str) -> None: ...

    # input_number CRUD
    async def list_input_numbers(self) -> list[InputNumberRecord]: ...
    async def create_input_number(self, params: CreateInputNumberParams) -> InputNumberRecord: ...
    async def update_input_number(self, helper_id: str, params: UpdateInputNumberParams) -> InputNumberRecord: ...
    async def delete_input_number(self, helper_id: str) -> None: ...

    # input_text CRUD
    async def list_input_texts(self) -> list[InputTextRecord]: ...
    async def create_input_text(self, params: CreateInputTextParams) -> InputTextRecord: ...
    async def update_input_text(self, helper_id: str, params: UpdateInputTextParams) -> InputTextRecord: ...
    async def delete_input_text(self, helper_id: str) -> None: ...

    # input_select CRUD
    async def list_input_selects(self) -> list[InputSelectRecord]: ...
    async def create_input_select(self, params: CreateInputSelectParams) -> InputSelectRecord: ...
    async def update_input_select(self, helper_id: str, params: UpdateInputSelectParams) -> InputSelectRecord: ...
    async def delete_input_select(self, helper_id: str) -> None: ...

    # input_datetime CRUD
    async def list_input_datetimes(self) -> list[InputDatetimeRecord]: ...
    async def create_input_datetime(self, params: CreateInputDatetimeParams) -> InputDatetimeRecord: ...
    async def update_input_datetime(self, helper_id: str, params: UpdateInputDatetimeParams) -> InputDatetimeRecord: ...
    async def delete_input_datetime(self, helper_id: str) -> None: ...

    # input_button CRUD
    async def list_input_buttons(self) -> list[InputButtonRecord]: ...
    async def create_input_button(self, params: CreateInputButtonParams) -> InputButtonRecord: ...
    async def update_input_button(self, helper_id: str, params: UpdateInputButtonParams) -> InputButtonRecord: ...
    async def delete_input_button(self, helper_id: str) -> None: ...

    # counter CRUD
    async def list_counters(self) -> list[CounterRecord]: ...
    async def create_counter(self, params: CreateCounterParams) -> CounterRecord: ...
    async def update_counter(self, helper_id: str, params: UpdateCounterParams) -> CounterRecord: ...
    async def delete_counter(self, helper_id: str) -> None: ...

    # timer CRUD
    async def list_timers(self) -> list[TimerRecord]: ...
    async def create_timer(self, params: CreateTimerParams) -> TimerRecord: ...
    async def update_timer(self, helper_id: str, params: UpdateTimerParams) -> TimerRecord: ...
    async def delete_timer(self, helper_id: str) -> None: ...

    # counter action methods
    async def increment_counter(self, entity_id: str) -> None: ...
    async def decrement_counter(self, entity_id: str) -> None: ...
    async def reset_counter(self, entity_id: str) -> None: ...


def _not_implemented(method_name: str) -> Never:
    """Raise NotImplementedError with a helpful message."""
    raise NotImplementedError(
        f"RecordingApi.{method_name}() is not implemented. "
        "Seed state via AppTestHarness.set_state() for read methods, "
        "or use a full integration test for methods requiring a live HA connection."
    )


class RecordingApi(Resource):
    """Test double for hassette.api.Api.

    Records write-method calls for assertion in tests. Delegates read methods to
    StateProxy so tests see seeded state values. get_state() raises
    EntityNotFoundError for unseeded entities (matching real Api behavior).

    on_initialize() calls self.mark_ready() — required for the Resource lifecycle.

    sync attribute is a _RecordingSyncFacade instance. Write calls via api.sync.*
    are recorded to the same `calls` list as the async side. Read methods delegate
    to the StateProxy. Methods not covered by the facade raise NotImplementedError.

    Unstubbed methods raise NotImplementedError with guidance on alternatives.

    Authoring constraints (enforced by the ``_RecordingSyncFacade`` generator):

    1. Methods must not call other ``async def`` methods on ``self`` directly;
       use sync helpers (``_get_raw_state``, ``_convert_state``) instead.
       Violating this constraint will fail the generator with a clear error
       pointing at the offending call site.

    2. Stub methods — those that should raise ``NotImplementedError`` on the
       sync side rather than be body-copied into the facade — should use
       ``self._not_implemented(name)`` for the canonical helpful error message
       on the async side. The ``_RecordingSyncFacade`` generator detects
       stub-tier methods by recognizing any body that contains only
       docstrings, ``raise`` statements, and/or ``_not_implemented()`` calls,
       so ``raise NotImplementedError(...)`` works too, but
       ``self._not_implemented(name)`` is preferred because the helper returns
       an exception with the project's standard seed-state guidance.

    Example::

        async with AppTestHarness(MotionLights, config={}) as harness:
            await harness.simulate_state_change("sensor.test", old_value="off", new_value="on")
            harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")
    """

    calls: list[ApiCall]
    helper_definitions: dict[str, dict[str, Any]]
    # `_RecordingSyncFacade` is intentionally private (underscore prefix). Users should
    # access the sync facade only via `harness.api_recorder.sync`; do not import the
    # type directly — it is not part of the public API surface.
    sync: "_RecordingSyncFacade"

    # Methods whose __getattr__ message should redirect users to get_state()
    _STATE_CONVERSION_METHODS: ClassVar[frozenset[str]] = frozenset(
        {
            "get_state_value",
            "get_state_value_typed",
            "get_attribute",
        }
    )

    def __init__(
        self,
        hassette: "Hassette",
        *,
        state_proxy: "StateProxy | None" = None,
        parent: Resource | None = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        # state_proxy may be injected directly (e.g. in unit tests) or resolved
        # lazily from hassette._state_proxy (when created via App.add_child()).
        self._state_proxy_override = state_proxy
        self.calls = []
        self.helper_definitions = {d: {} for d in _SUPPORTED_HELPER_DOMAINS}
        self.sync = _RecordingSyncFacade(self)

    @property
    def _state_proxy(self) -> "StateProxy":
        """Resolve the state proxy: injected override takes precedence, else hassette._state_proxy."""
        if self._state_proxy_override is not None:
            return self._state_proxy_override
        sp = self.hassette._state_proxy
        if sp is None:
            raise RuntimeError(
                "RecordingApi: no StateProxy available. Ensure HassetteHarness is started with with_state_proxy()."
            )
        return sp

    async def on_initialize(self) -> None:
        """Mark this resource ready. Called by Resource.initialize()."""
        self.mark_ready(reason="RecordingApi initialized")

    def _new_helper_id(self, domain: str, name: str) -> str:
        """Generate a unique helper id for domain, mirroring HA's IDManager.generate_id.

        Private sync helper called by create_* methods. The sync facade generator
        rewrites ``self._new_helper_id(...)`` → ``self._parent._new_helper_id(...)``
        so body-copied create methods in _RecordingSyncFacade call this correctly.

        Emits a DEBUG log when the returned id was auto-suffixed due to a
        collision — otherwise a test author who expected ``vacation_mode`` but
        got ``vacation_mode_2`` has no log signal explaining why.
        """
        existing_ids = set(self.helper_definitions[domain].keys())
        generated = _generate_helper_id(existing_ids, name)
        base_slug = _slugify_helper_name(name)
        if generated != base_slug:
            self.logger.debug(
                "RecordingApi %s: name %r -> id %r (base slug %r was already taken; auto-suffixed)",
                domain,
                name,
                generated,
                base_slug,
            )
        return generated

    # ------------------------------------------------------------------
    # Write methods — record ApiCall, then return a stub value.
    # Signatures must exactly match hassette.api.Api.
    # ------------------------------------------------------------------

    async def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data: Any) -> None:
        """Record a turn_on call directly under its own method name."""
        entity_id = str(entity_id)
        self.calls.append(
            ApiCall(
                method="turn_on",
                args=(entity_id,),
                kwargs={"entity_id": entity_id, "domain": domain, **data},
            )
        )

    async def turn_off(self, entity_id: str | StrEnum, domain: str = "homeassistant") -> None:
        """Record a turn_off call directly under its own method name."""
        entity_id = str(entity_id)
        self.calls.append(
            ApiCall(
                method="turn_off",
                args=(entity_id,),
                kwargs={"entity_id": entity_id, "domain": domain},
            )
        )

    async def toggle_service(self, entity_id: str | StrEnum, domain: str = "homeassistant") -> None:
        """Record a toggle_service call directly under its own method name."""
        entity_id = str(entity_id)
        self.calls.append(
            ApiCall(
                method="toggle_service",
                args=(entity_id,),
                kwargs={"entity_id": entity_id, "domain": domain},
            )
        )

    async def call_service(
        self,
        domain: str,
        service: str,
        target: dict[str, str] | dict[str, list[str]] | None = None,
        return_response: bool | None = False,
        **data: Any,
    ) -> ServiceResponse | None:
        """Record a call_service call. Returns stub ServiceResponse when return_response=True."""
        self.calls.append(
            ApiCall(
                method="call_service",
                args=(domain, service),
                kwargs={
                    "domain": domain,
                    "service": service,
                    # Deep-copy target at record time so later caller mutations — including
                    # mutations to nested lists like `{"entity_id": [...]}`, which HA entity
                    # targets frequently contain — do not alter the recorded assertion
                    # surface (immutability principle).
                    "target": copy.deepcopy(target),
                    "return_response": return_response,
                    **data,
                },
            )
        )
        if return_response:
            return ServiceResponse(context=Context(id=None, parent_id=None, user_id=None))
        return None

    async def set_state(
        self,
        entity_id: str | StrEnum,
        state: Any,
        attributes: dict[str, Any] | None = None,
    ) -> dict:
        """Record a set_state call. Returns an empty dict stub."""
        entity_id = str(entity_id)
        self.calls.append(
            ApiCall(
                method="set_state",
                args=(entity_id, state),
                # Deep-copy attributes at record time so later caller mutations —
                # including mutations to nested structures — do not alter the recorded
                # assertion surface (immutability principle).
                kwargs={
                    "entity_id": entity_id,
                    "state": state,
                    "attributes": copy.deepcopy(attributes),
                },
            )
        )
        return {}

    async def fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a fire_event call. Returns an empty dict stub."""
        self.calls.append(
            ApiCall(
                method="fire_event",
                args=(event_type,),
                # Deep-copy event_data at record time so later caller mutations —
                # including mutations to nested structures — do not alter the recorded
                # assertion surface (immutability principle).
                kwargs={"event_type": event_type, "event_data": copy.deepcopy(event_data)},
            )
        )
        return {}

    # ------------------------------------------------------------------
    # Read methods — delegate to StateProxy, convert via state registry.
    # ------------------------------------------------------------------

    def _get_raw_state(self, entity_id: str) -> "HassStateDict":
        """Look up raw state dict from the proxy, raising EntityNotFoundError if absent."""
        raw = self._state_proxy.states.get(entity_id)
        if raw is None:
            raise EntityNotFoundError(f"Entity '{entity_id}' not found in StateProxy (not seeded).")
        return raw

    def _convert_state(self, raw: "HassStateDict", entity_id: str | None = None) -> BaseState:
        """Convert a raw HassStateDict to a typed BaseState via the state registry.

        Args:
            raw: Raw state dict from the StateProxy.
            entity_id: Optional entity ID passed to the state registry for accurate domain
                resolution. Matches the behaviour of the real Api and StateManager.
        """
        return self.hassette.state_registry.try_convert_state(raw, entity_id)

    async def get_state(self, entity_id: str) -> BaseState:
        """Return the typed state for entity_id. Raises EntityNotFoundError if not seeded."""
        raw = self._get_raw_state(entity_id)
        return self._convert_state(raw, entity_id)

    async def get_states(self) -> list[BaseState]:
        """Return typed states for all seeded entities."""
        # Snapshot the dict to avoid RuntimeError from concurrent mutation.
        items = list(self._state_proxy.states.items())
        return [self._convert_state(raw, eid) for eid, raw in items]

    async def get_entity(self, entity_id: str, model: type[BaseEntity]) -> BaseEntity:
        """Return a pydantic-validated entity wrapper for entity_id.

        Matches the real ``Api.get_entity`` signature exactly — ``model`` is required
        and must be a :class:`~hassette.models.entities.base.BaseEntity` subclass.
        Callers that want registry-converted state without a specific entity model
        should call :meth:`get_state` instead.

        Raises:
            TypeError: If ``model`` is not a ``BaseEntity`` subclass.
            EntityNotFoundError: If ``entity_id`` is not seeded.
        """
        if not issubclass(model, BaseEntity):  # runtime check — mirrors Api.get_entity
            raise TypeError(f"Model {model!r} is not a valid BaseEntity subclass")

        raw = self._get_raw_state(entity_id)
        return model.model_validate({"state": raw})

    async def get_entity_or_none(self, entity_id: str, model: type[BaseEntity]) -> BaseEntity | None:
        """Return a pydantic-validated entity wrapper for entity_id, or None if not seeded.

        Inlines the logic from :meth:`get_entity` using sync helpers only — no peer
        ``async def`` calls on ``self`` — to satisfy the authoring constraint required
        by the ``_RecordingSyncFacade`` generator. Matches the real
        ``Api.get_entity_or_none`` signature; see :meth:`get_entity` for semantics.
        """
        if not issubclass(model, BaseEntity):  # runtime check — mirrors Api.get_entity
            raise TypeError(f"Model {model!r} is not a valid BaseEntity subclass")

        try:
            raw = self._get_raw_state(entity_id)
        except EntityNotFoundError:
            return None
        return model.model_validate({"state": raw})

    async def entity_exists(self, entity_id: str) -> bool:
        """Return True if entity_id is seeded in the StateProxy."""
        return entity_id in self._state_proxy.states

    async def get_state_or_none(self, entity_id: str) -> BaseState | None:
        """Return the typed state for entity_id, or None if not seeded.

        Inlines the logic from :meth:`get_state` using sync helpers only — no peer
        ``async def`` calls on ``self`` — to satisfy the authoring constraint required
        by the ``_RecordingSyncFacade`` generator.
        """
        try:
            raw = self._get_raw_state(entity_id)
        except EntityNotFoundError:
            return None
        return self._convert_state(raw, entity_id)

    # ------------------------------------------------------------------
    # Unstubbed methods — raise NotImplementedError with helpful message.
    # ------------------------------------------------------------------

    async def get_state_raw(self, entity_id: str) -> dict:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("get_state_raw")

    async def get_states_raw(self) -> list[dict]:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("get_states_raw")

    async def get_history(self, entity_id: str, *args: Any, **kwargs: Any) -> list:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("get_history")

    async def render_template(self, template: str, variables: dict | None = None) -> str:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("render_template")

    async def ws_send_and_wait(self, **data: Any) -> Any:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("ws_send_and_wait")

    async def ws_send_json(self, **data: Any) -> None:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("ws_send_json")

    async def rest_request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("rest_request")

    async def delete_entity(self, entity_id: str) -> None:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("delete_entity")

    # ------------------------------------------------------------------
    # Helper CRUD — seeds/mutates helper_definitions dict and records ApiCall.
    # Signatures match hassette.api.Api exactly.
    #
    # Generic core methods (_list_helper, _create_helper, _update_helper,
    # _delete_helper) implement the shared logic dispatching via
    # _RECORD_TYPE_TO_DOMAIN. The 32 per-domain methods below are thin typed
    # delegations that call the generic core; no logic lives in them.
    # ------------------------------------------------------------------

    def _list_helper(self, record_type: type) -> list[Any]:
        """Generic list helper — returns shallow or deep copies of stored records.

        Dispatches via ``_RECORD_TYPE_TO_DOMAIN`` to determine the domain and
        whether ``deep=True`` copies are needed.

        Args:
            record_type: The Record class (e.g. ``InputBooleanRecord``).

        Returns:
            List of model copies for the domain.
        """
        domain, deep_copy = _RECORD_TYPE_TO_DOMAIN[record_type]
        return [r.model_copy(deep=deep_copy) for r in self.helper_definitions[domain].values()]

    def _create_helper(self, record_type: type, method_name: str, params: Any) -> Any:
        """Generic create helper — records an ApiCall and inserts a new record.

        Dispatches via ``_RECORD_TYPE_TO_DOMAIN`` to determine the domain and
        copy depth.  Auto-suffixes the generated id on collision (mirrors HA's
        IDManager.generate_id).

        Args:
            record_type: The Record class to instantiate.
            method_name: The API method name to record (e.g. ``"create_input_boolean"``).
            params: The Create*Params model instance.

        Returns:
            A copy of the newly created record.
        """
        domain, deep_copy = _RECORD_TYPE_TO_DOMAIN[record_type]
        self.calls.append(
            ApiCall(
                method=method_name,
                args=(),
                kwargs=params.model_dump(exclude_unset=True),
            )
        )
        generated_id = self._new_helper_id(domain, params.name)
        record = record_type(id=generated_id, **params.model_dump(exclude_unset=True))
        self.helper_definitions[domain][record.id] = record
        return record.model_copy(deep=deep_copy)

    def _update_helper(self, record_type: type, method_name: str, helper_id: str, params: Any) -> Any:
        """Generic update helper — records an ApiCall and mutates the stored record.

        Dispatches via ``_RECORD_TYPE_TO_DOMAIN`` to determine the domain and
        copy depth.

        Args:
            record_type: The Record class.
            method_name: The API method name to record (e.g. ``"update_input_boolean"``).
            helper_id: The helper id to update.
            params: The Update*Params model instance.

        Returns:
            A copy of the updated record.

        Raises:
            FailedMessageError: With code='not_found' if helper_id is not seeded.
        """
        domain, deep_copy = _RECORD_TYPE_TO_DOMAIN[record_type]
        self.calls.append(
            ApiCall(
                method=method_name,
                args=(helper_id,),
                kwargs={"helper_id": helper_id, **params.model_dump(exclude_unset=True)},
            )
        )
        if helper_id not in self.helper_definitions[domain]:
            raise FailedMessageError(
                f"{domain} helper {helper_id!r} not found. Seed it via harness.seed_helper() first.",
                code="not_found",
            )
        existing = self.helper_definitions[domain][helper_id]
        updated = existing.model_copy(update=params.model_dump(exclude_unset=True))
        self.helper_definitions[domain][helper_id] = updated
        return updated.model_copy(deep=deep_copy)

    def _delete_helper(self, record_type: type, method_name: str, helper_id: str) -> None:
        """Generic delete helper — records an ApiCall and removes the stored record.

        Dispatches via ``_RECORD_TYPE_TO_DOMAIN`` to determine the domain.

        Args:
            record_type: The Record class.
            method_name: The API method name to record (e.g. ``"delete_input_boolean"``).
            helper_id: The helper id to delete.

        Raises:
            FailedMessageError: With code='not_found' if helper_id is not seeded.
        """
        domain, _deep_copy = _RECORD_TYPE_TO_DOMAIN[record_type]
        self.calls.append(
            ApiCall(
                method=method_name,
                args=(helper_id,),
                kwargs={"helper_id": helper_id},
            )
        )
        if helper_id not in self.helper_definitions[domain]:
            raise FailedMessageError(
                f"{domain} helper {helper_id!r} not found.",
                code="not_found",
            )
        del self.helper_definitions[domain][helper_id]

    # --- input_boolean ---

    async def list_input_booleans(self) -> list[InputBooleanRecord]:
        """Return all seeded input_boolean helpers. Delegates to _list_helper."""
        return cast("list[InputBooleanRecord]", self._list_helper(InputBooleanRecord))

    async def create_input_boolean(self, params: CreateInputBooleanParams) -> InputBooleanRecord:
        """Record the call and add a record to helper_definitions. Delegates to _create_helper."""
        return cast("InputBooleanRecord", self._create_helper(InputBooleanRecord, "create_input_boolean", params))

    async def update_input_boolean(self, helper_id: str, params: UpdateInputBooleanParams) -> InputBooleanRecord:
        """Record the call and mutate the seeded record. Delegates to _update_helper."""
        return cast(
            "InputBooleanRecord", self._update_helper(InputBooleanRecord, "update_input_boolean", helper_id, params)
        )

    async def delete_input_boolean(self, helper_id: str) -> None:
        """Record the call and remove the seeded record. Delegates to _delete_helper."""
        self._delete_helper(InputBooleanRecord, "delete_input_boolean", helper_id)

    # --- input_number ---

    async def list_input_numbers(self) -> list[InputNumberRecord]:
        """Return all seeded input_number helpers. Delegates to _list_helper."""
        return cast("list[InputNumberRecord]", self._list_helper(InputNumberRecord))

    async def create_input_number(self, params: CreateInputNumberParams) -> InputNumberRecord:
        """Record the call and add a record to helper_definitions. Delegates to _create_helper."""
        return cast("InputNumberRecord", self._create_helper(InputNumberRecord, "create_input_number", params))

    async def update_input_number(self, helper_id: str, params: UpdateInputNumberParams) -> InputNumberRecord:
        """Record the call and mutate the seeded record. Delegates to _update_helper."""
        return cast(
            "InputNumberRecord", self._update_helper(InputNumberRecord, "update_input_number", helper_id, params)
        )

    async def delete_input_number(self, helper_id: str) -> None:
        """Record the call and remove the seeded record. Delegates to _delete_helper."""
        self._delete_helper(InputNumberRecord, "delete_input_number", helper_id)

    # --- input_text ---

    async def list_input_texts(self) -> list[InputTextRecord]:
        """Return all seeded input_text helpers. Delegates to _list_helper."""
        return cast("list[InputTextRecord]", self._list_helper(InputTextRecord))

    async def create_input_text(self, params: CreateInputTextParams) -> InputTextRecord:
        """Record the call and add a record to helper_definitions. Delegates to _create_helper."""
        return cast("InputTextRecord", self._create_helper(InputTextRecord, "create_input_text", params))

    async def update_input_text(self, helper_id: str, params: UpdateInputTextParams) -> InputTextRecord:
        """Record the call and mutate the seeded record. Delegates to _update_helper."""
        return cast("InputTextRecord", self._update_helper(InputTextRecord, "update_input_text", helper_id, params))

    async def delete_input_text(self, helper_id: str) -> None:
        """Record the call and remove the seeded record. Delegates to _delete_helper."""
        self._delete_helper(InputTextRecord, "delete_input_text", helper_id)

    # --- input_select ---

    async def list_input_selects(self) -> list[InputSelectRecord]:
        """Return all seeded input_select helpers as deep-isolated copies.

        Delegates to _list_helper. Uses ``model_copy(deep=True)`` because
        ``InputSelectRecord.options`` is a ``list[str]`` — the ``deep_copy=True``
        flag in ``_RECORD_TYPE_TO_DOMAIN`` ensures the list is not aliased.
        """
        return cast("list[InputSelectRecord]", self._list_helper(InputSelectRecord))

    async def create_input_select(self, params: CreateInputSelectParams) -> InputSelectRecord:
        """Record the call and add a record to helper_definitions. Delegates to _create_helper."""
        return cast("InputSelectRecord", self._create_helper(InputSelectRecord, "create_input_select", params))

    async def update_input_select(self, helper_id: str, params: UpdateInputSelectParams) -> InputSelectRecord:
        """Record the call and mutate the seeded record. Delegates to _update_helper."""
        return cast(
            "InputSelectRecord", self._update_helper(InputSelectRecord, "update_input_select", helper_id, params)
        )

    async def delete_input_select(self, helper_id: str) -> None:
        """Record the call and remove the seeded record. Delegates to _delete_helper."""
        self._delete_helper(InputSelectRecord, "delete_input_select", helper_id)

    # --- input_datetime ---

    async def list_input_datetimes(self) -> list[InputDatetimeRecord]:
        """Return all seeded input_datetime helpers. Delegates to _list_helper."""
        return cast("list[InputDatetimeRecord]", self._list_helper(InputDatetimeRecord))

    async def create_input_datetime(self, params: CreateInputDatetimeParams) -> InputDatetimeRecord:
        """Record the call and add a record to helper_definitions. Delegates to _create_helper."""
        return cast("InputDatetimeRecord", self._create_helper(InputDatetimeRecord, "create_input_datetime", params))

    async def update_input_datetime(self, helper_id: str, params: UpdateInputDatetimeParams) -> InputDatetimeRecord:
        """Record the call and mutate the seeded record. Delegates to _update_helper."""
        return cast(
            "InputDatetimeRecord", self._update_helper(InputDatetimeRecord, "update_input_datetime", helper_id, params)
        )

    async def delete_input_datetime(self, helper_id: str) -> None:
        """Record the call and remove the seeded record. Delegates to _delete_helper."""
        self._delete_helper(InputDatetimeRecord, "delete_input_datetime", helper_id)

    # --- input_button ---

    async def list_input_buttons(self) -> list[InputButtonRecord]:
        """Return all seeded input_button helpers. Delegates to _list_helper."""
        return cast("list[InputButtonRecord]", self._list_helper(InputButtonRecord))

    async def create_input_button(self, params: CreateInputButtonParams) -> InputButtonRecord:
        """Record the call and add a record to helper_definitions. Delegates to _create_helper."""
        return cast("InputButtonRecord", self._create_helper(InputButtonRecord, "create_input_button", params))

    async def update_input_button(self, helper_id: str, params: UpdateInputButtonParams) -> InputButtonRecord:
        """Record the call and mutate the seeded record. Delegates to _update_helper."""
        return cast(
            "InputButtonRecord", self._update_helper(InputButtonRecord, "update_input_button", helper_id, params)
        )

    async def delete_input_button(self, helper_id: str) -> None:
        """Record the call and remove the seeded record. Delegates to _delete_helper."""
        self._delete_helper(InputButtonRecord, "delete_input_button", helper_id)

    # --- counter ---

    async def list_counters(self) -> list[CounterRecord]:
        """Return all seeded counter helpers. Delegates to _list_helper."""
        return cast("list[CounterRecord]", self._list_helper(CounterRecord))

    async def create_counter(self, params: CreateCounterParams) -> CounterRecord:
        """Record the call and add a record to helper_definitions. Delegates to _create_helper."""
        return cast("CounterRecord", self._create_helper(CounterRecord, "create_counter", params))

    async def update_counter(self, helper_id: str, params: UpdateCounterParams) -> CounterRecord:
        """Record the call and mutate the seeded record. Delegates to _update_helper."""
        return cast("CounterRecord", self._update_helper(CounterRecord, "update_counter", helper_id, params))

    async def delete_counter(self, helper_id: str) -> None:
        """Record the call and remove the seeded record. Delegates to _delete_helper."""
        self._delete_helper(CounterRecord, "delete_counter", helper_id)

    # --- timer ---

    async def list_timers(self) -> list[TimerRecord]:
        """Return all seeded timer helpers. Delegates to _list_helper."""
        return cast("list[TimerRecord]", self._list_helper(TimerRecord))

    async def create_timer(self, params: CreateTimerParams) -> TimerRecord:
        """Record the call and add a record to helper_definitions. Delegates to _create_helper."""
        return cast("TimerRecord", self._create_helper(TimerRecord, "create_timer", params))

    async def update_timer(self, helper_id: str, params: UpdateTimerParams) -> TimerRecord:
        """Record the call and mutate the seeded record. Delegates to _update_helper."""
        return cast("TimerRecord", self._update_helper(TimerRecord, "update_timer", helper_id, params))

    async def delete_timer(self, helper_id: str) -> None:
        """Record the call and remove the seeded record. Delegates to _delete_helper."""
        self._delete_helper(TimerRecord, "delete_timer", helper_id)

    # --- counter action methods ---

    async def increment_counter(self, entity_id: str) -> None:
        """Record an increment_counter call directly (not via call_service)."""
        self.calls.append(
            ApiCall(
                method="increment_counter",
                args=(entity_id,),
                kwargs={"entity_id": entity_id},
            )
        )

    async def decrement_counter(self, entity_id: str) -> None:
        """Record a decrement_counter call directly (not via call_service)."""
        self.calls.append(
            ApiCall(
                method="decrement_counter",
                args=(entity_id,),
                kwargs={"entity_id": entity_id},
            )
        )

    async def reset_counter(self, entity_id: str) -> None:
        """Record a reset_counter call directly (not via call_service)."""
        self.calls.append(
            ApiCall(
                method="reset_counter",
                args=(entity_id,),
                kwargs={"entity_id": entity_id},
            )
        )

    # ------------------------------------------------------------------
    # Fallback for uncovered methods
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """Raise NotImplementedError for public attributes not defined on RecordingApi.

        Private/dunder attributes fall through to the default AttributeError so that
        Resource internals (e.g. ``_unique_name``) and Python machinery work correctly.

        State-conversion methods (get_state_value, get_state_value_typed, get_attribute)
        get a tailored message directing users to ``await self.api.get_state(entity_id)``.
        All other unimplemented methods get the generic "Seed state" guidance.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._STATE_CONVERSION_METHODS:
            raise NotImplementedError(
                f"RecordingApi.{name} is not implemented. "
                f"Call `await self.api.get_state(entity_id)` and read the returned state directly."
            )
        raise NotImplementedError(
            f"RecordingApi.{name}() is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )

    # ------------------------------------------------------------------
    # Assertion helpers
    # ------------------------------------------------------------------

    def get_calls(self, method: str | None = None) -> list[ApiCall]:
        """Return all recorded calls, optionally filtered by method name.

        Args:
            method: If given, return only calls for this method name.

        Returns:
            List of ApiCall records (a copy — callers may modify safely).
        """
        if method is None:
            return list(self.calls)
        return [c for c in self.calls if c.method == method]

    def assert_called(self, method: str, **kwargs: Any) -> None:
        """Assert that method was called at least once with matching kwargs.

        Performs **partial** (subset) matching: the call passes if all specified
        ``kwargs`` are present in the recorded call's kwargs with matching values.
        Extra kwargs in the recorded call are ignored. Positional arguments
        recorded in ``call.args`` are also checked via the recorded ``kwargs``
        dict — write methods record their positional args as both ``args`` and
        ``kwargs`` so assertions like
        ``assert_called("turn_on", entity_id="light.kitchen")`` work.

        This is a partial-match alias. See also :meth:`assert_called_partial`
        (identical semantics, explicit name) and :meth:`assert_called_exact`
        (no extra kwargs allowed in the recorded call).

        Args:
            method: Method name to check.
            **kwargs: Expected keyword arguments that must appear in at least one call.

        Raises:
            AssertionError: If no call matches.
        """
        matching = self.get_calls(method)
        if not matching:
            raise AssertionError(f"Expected '{method}' to have been called, but it was never called.")

        if kwargs:
            for call in matching:
                # Check that all expected kwargs appear in the call's recorded kwargs.
                # Write methods record positional args in both call.args and call.kwargs
                # so kwargs-based assertions work uniformly for all methods.
                if all(k in call.kwargs and call.kwargs[k] == v for k, v in kwargs.items()):
                    return
            raise AssertionError(
                f"'{method}' was called {len(matching)} time(s), but none matched kwargs {kwargs!r}. "
                f"Calls recorded: {[{'args': c.args, 'kwargs': c.kwargs} for c in matching]}"
            )

    def assert_called_partial(self, method: str, **kwargs: Any) -> None:
        """Assert that method was called at least once with matching kwargs (partial match).

        Non-deprecated alias for :meth:`assert_called`. Performs **partial**
        (subset) matching: the call passes if all specified ``kwargs`` are
        present in the recorded call's kwargs with matching values. Extra kwargs
        in the recorded call are ignored.

        Use this name when you want to make the partial-match intent explicit in
        test code. Both ``assert_called`` and ``assert_called_partial`` behave
        identically; they differ only in name clarity.

        See also :meth:`assert_called_exact` for exact (no-extra-kwargs) matching.

        Args:
            method: Method name to check.
            **kwargs: Expected keyword arguments that must appear in at least one call.

        Raises:
            AssertionError: If no call matches.
        """
        self.assert_called(method, **kwargs)

    def assert_called_exact(self, method: str, **kwargs: Any) -> None:
        """Assert that method was called at least once with exactly the specified kwargs.

        Performs **exact** matching: the call passes only when the recorded
        call's ``kwargs`` dict is exactly equal to the provided ``kwargs`` —
        no extra keys are allowed. This is stricter than :meth:`assert_called`
        and :meth:`assert_called_partial`, which allow extra keys in the
        recorded call.

        Use this when you need to verify that no unexpected kwargs were passed.
        For example, if a method should be called *only* with ``entity_id``
        and nothing else, use ``assert_called_exact("turn_off", entity_id="light.x")``
        rather than ``assert_called("turn_off", entity_id="light.x")`` — the latter
        would pass even if ``domain="homeassistant"`` was also recorded.

        Args:
            method: Method name to check.
            **kwargs: The exact keyword arguments expected in at least one call.

        Raises:
            AssertionError: If no call was recorded with exactly the specified kwargs.

        Example::

            await api.turn_off("light.x")
            # Passes — recorded kwargs are {"entity_id": "light.x", "domain": "homeassistant"}
            api.assert_called("turn_off", entity_id="light.x")       # partial: OK
            # Fails — extra "domain" key is present
            api.assert_called_exact("turn_off", entity_id="light.x") # exact: fails
            # Passes — matches exactly
            api.assert_called_exact("turn_off", entity_id="light.x", domain="homeassistant")
        """
        matching = self.get_calls(method)
        if not matching:
            raise AssertionError(f"Expected '{method}' to have been called, but it was never called.")

        for call in matching:
            if call.kwargs == kwargs:
                return
        raise AssertionError(
            f"'{method}' was called {len(matching)} time(s), but none matched kwargs exactly {kwargs!r}. "
            f"Calls recorded: {[{'args': c.args, 'kwargs': c.kwargs} for c in matching]}"
        )

    def assert_not_called(self, method: str) -> None:
        """Assert that method was never called.

        Args:
            method: Method name to check.

        Raises:
            AssertionError: If the method was called at least once.
        """
        matching = self.get_calls(method)
        if matching:
            raise AssertionError(
                f"Expected '{method}' not to have been called, but it was called {len(matching)} time(s)."
            )

    def assert_call_count(self, method: str, count: int) -> None:
        """Assert that method was called exactly count times.

        Args:
            method: Method name to check.
            count: Expected number of calls.

        Raises:
            AssertionError: If the call count does not match.
        """
        actual = len(self.get_calls(method))
        if actual != count:
            raise AssertionError(
                f"Expected '{method}' to have been called {count} time(s), but it was called {actual} time(s)."
            )

    def reset(self) -> None:
        """Clear all recorded calls and reset helper_definitions to empty-per-domain state.

        Replaces the calls list with a new empty list rather than mutating the
        existing list in place. This preserves any snapshots callers hold
        (e.g., ``saved = api.calls`` before a ``simulate_*`` call) — they
        will still see the original calls after reset, as expected.
        """
        self.calls = []
        self.helper_definitions = {d: {} for d in _SUPPORTED_HELPER_DOMAINS}
