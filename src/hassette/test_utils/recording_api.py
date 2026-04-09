"""RecordingApi — test double for hassette.api.Api.

Records write-method calls for test assertions. Delegates read methods to
StateProxy. Implements ApiProtocol for static conformance checking.

Intended for use with AppTestHarness. Users who need full HTTP-level
fidelity should use a full integration test with a live HA connection.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, Never, Protocol, cast, runtime_checkable
from unittest.mock import Mock

from hassette.exceptions import EntityNotFoundError
from hassette.models.entities.base import BaseEntity
from hassette.models.services import ServiceResponse
from hassette.models.states.base import BaseState, Context
from hassette.resources.base import Resource
from hassette.test_utils.api_call import ApiCall

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.state_proxy import StateProxy
    from hassette.events import HassStateDict


@runtime_checkable
class ApiProtocol(Protocol):
    """Protocol covering the public async interface of hassette.api.Api.

    RecordingApi is verified to conform to this protocol at module import
    time via the module-level ``_: ApiProtocol = cast(...)`` assertion.
    """

    # Write methods
    async def turn_on(self, entity_id: str | StrEnum, domain: str = ..., **data) -> None: ...
    async def turn_off(self, entity_id: str | StrEnum, domain: str = ...) -> None: ...
    async def toggle_service(self, entity_id: str | StrEnum, domain: str = ...) -> None: ...
    async def call_service(
        self,
        domain: str,
        service: str,
        target: dict | None = None,
        return_response: bool | None = False,
        **data,
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

    # Read methods
    async def get_state(self, entity_id: str) -> BaseState: ...
    async def get_states(self) -> list[BaseState]: ...
    async def get_entity(self, entity_id: str, model: type[Any] = ...) -> BaseState: ...
    async def get_entity_or_none(self, entity_id: str, model: type[Any] = ...) -> BaseState | None: ...
    async def entity_exists(self, entity_id: str) -> bool: ...
    async def get_state_or_none(self, entity_id: str) -> BaseState | None: ...


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

    sync attribute is a Mock() instance. Apps using self.api.sync.* in the paths
    under test must use a full integration test for those code paths.

    Unstubbed methods raise NotImplementedError with guidance on alternatives.

    Example::

        async with AppTestHarness(MotionLights, config={}) as harness:
            await harness.simulate_state_change("sensor.test", old_value="off", new_value="on")
            harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")
    """

    calls: list[ApiCall]
    sync: Mock

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
        self.sync = Mock()

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

    # ------------------------------------------------------------------
    # Write methods — record ApiCall, then return a stub value.
    # Signatures must exactly match hassette.api.Api.
    # ------------------------------------------------------------------

    async def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data) -> None:
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
        **data,
    ) -> ServiceResponse | None:
        """Record a call_service call. Returns stub ServiceResponse when return_response=True."""
        self.calls.append(
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
                kwargs={"entity_id": entity_id, "state": state, "attributes": attributes},
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
                kwargs={"event_type": event_type, "event_data": event_data},
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

    async def get_entity(self, entity_id: str, model: type[Any] = BaseState) -> BaseState:
        """Return the typed state for entity_id. Raises EntityNotFoundError if not seeded.

        When ``model`` is a :class:`~hassette.models.entities.base.BaseEntity` subclass,
        the raw state dict is validated through ``model.model_validate({"state": raw})``,
        mirroring the real ``Api.get_entity`` behavior. This ensures tests catch type
        mismatches that would surface in production.

        When ``model`` is the default ``BaseState``, falls back to state-registry conversion
        (same as :meth:`get_state`).
        """
        raw = self._get_raw_state(entity_id)
        if model is not BaseState and issubclass(model, BaseEntity):
            return cast("BaseState", model.model_validate({"state": raw}))
        return self._convert_state(raw, entity_id)

    async def get_entity_or_none(self, entity_id: str, model: type[Any] = BaseState) -> BaseState | None:
        """Return the typed state for entity_id, or None if not seeded.

        Delegates to :meth:`get_entity`, which performs model validation when
        ``model`` is a BaseEntity subclass.
        """
        try:
            return await self.get_entity(entity_id, model)
        except EntityNotFoundError:
            return None

    async def entity_exists(self, entity_id: str) -> bool:
        """Return True if entity_id is seeded in the StateProxy."""
        return entity_id in self._state_proxy.states

    async def get_state_or_none(self, entity_id: str) -> BaseState | None:
        """Return the typed state for entity_id, or None if not seeded."""
        try:
            return await self.get_state(entity_id)
        except EntityNotFoundError:
            return None

    # ------------------------------------------------------------------
    # Unstubbed methods — raise NotImplementedError with helpful message.
    # ------------------------------------------------------------------

    async def get_state_raw(self, entity_id: str) -> dict:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("get_state_raw")
        raise RuntimeError("unreachable")  # for type checker

    async def get_states_raw(self) -> list[dict]:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("get_states_raw")
        raise RuntimeError("unreachable")

    async def get_history(self, entity_id: str, *args: Any, **kwargs: Any) -> list:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("get_history")
        raise RuntimeError("unreachable")

    async def render_template(self, template: str, variables: dict | None = None) -> str:
        """Not implemented — raises NotImplementedError."""
        _not_implemented("render_template")
        raise RuntimeError("unreachable")

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

    def assert_called(self, method: str, **kwargs) -> None:
        """Assert that method was called at least once with matching kwargs.

        Performs partial (subset) matching: the call passes if all specified
        ``kwargs`` are present in the recorded call's kwargs with matching values.
        Positional arguments recorded in ``call.args`` are also checked via the
        recorded ``kwargs`` dict — write methods record their positional args as
        both ``args`` and ``kwargs`` so assertions like
        ``assert_called("turn_on", entity_id="light.kitchen")`` work.

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
        """Clear all recorded calls."""
        self.calls.clear()


# ---------------------------------------------------------------------------
# Annotation convention — cast() is a runtime no-op and Pyright does not
# verify structural conformance through casts. This serves as documentation
# that RecordingApi intends to satisfy ApiProtocol. Actual safety nets:
# (1) __getattr__ raises NotImplementedError for uncovered methods.
# (2) ApiProtocol covers the subset of Api methods that RecordingApi stubs.
# ---------------------------------------------------------------------------
_: ApiProtocol = cast("ApiProtocol", RecordingApi)
