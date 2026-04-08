"""RecordingApi — test double for hassette.api.Api.

Records write-method calls for test assertions. Delegates read methods to
StateProxy. Implements ApiProtocol for static conformance checking.

Intended for use with AppTestHarness. Users who need full HTTP-level
fidelity should pass use_api_server=True to AppTestHarness instead.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Never, Protocol, cast, runtime_checkable
from unittest.mock import Mock

from hassette.exceptions import EntityNotFoundError
from hassette.models.services import ServiceResponse
from hassette.models.states.base import BaseState, Context
from hassette.resources.base import Resource

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.state_proxy import StateProxy


@dataclass
class ApiCall:
    """Record of a single API method invocation.

    Attributes:
        method: Name of the method that was called (e.g. "turn_on").
        args: Positional arguments passed to the method.
        kwargs: Keyword arguments passed to the method.
    """

    method: str
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)


@runtime_checkable
class ApiProtocol(Protocol):
    """Protocol covering the public async interface of hassette.api.Api.

    RecordingApi is verified to conform to this protocol at module import
    time via the module-level ``_: ApiProtocol = cast(...)`` assertion.
    """

    # Write methods
    async def turn_on(self, entity_id: str | StrEnum, domain: str = ..., **data) -> None: ...
    async def turn_off(self, entity_id: str, domain: str = ...) -> None: ...
    async def toggle_service(self, entity_id: str, domain: str = ...) -> None: ...
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
    async def get_entity(self, entity_id: str, model: type[Any] | None = None) -> BaseState: ...
    async def get_entity_or_none(self, entity_id: str, model: type[Any] | None = None) -> BaseState | None: ...
    async def entity_exists(self, entity_id: str) -> bool: ...
    async def get_state_or_none(self, entity_id: str) -> BaseState | None: ...


def _not_implemented(method_name: str) -> Never:
    """Raise NotImplementedError with a helpful message directing users to use_api_server=True."""
    raise NotImplementedError(
        f"RecordingApi.{method_name}() is not implemented. Use use_api_server=True for full Api coverage."
    )


class RecordingApi(Resource):
    """Test double for hassette.api.Api.

    Records write-method calls for assertion in tests. Delegates read methods to
    StateProxy so tests see seeded state values. get_state() raises
    EntityNotFoundError for unseeded entities (matching real Api behavior).

    on_initialize() calls self.mark_ready() — required for the Resource lifecycle.

    sync attribute is a Mock() instance. Apps using self.api.sync.* in the paths
    under test must use use_api_server=True for those code paths.

    Unstubbed methods raise NotImplementedError with a message directing users to
    use_api_server=True.
    """

    calls: list[ApiCall]
    _state_proxy: "StateProxy"
    sync: Mock

    def __init__(
        self,
        hassette: "Hassette",
        *,
        state_proxy: "StateProxy",
        parent: Resource | None = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        self._state_proxy = state_proxy
        self.calls = []
        self.sync = Mock()

    async def on_initialize(self) -> None:
        """Mark this resource ready. Called by Resource.initialize()."""
        self.mark_ready(reason="RecordingApi initialized")

    # ------------------------------------------------------------------
    # Write methods — record ApiCall, then return a stub value.
    # Signatures must exactly match hassette.api.Api.
    # ------------------------------------------------------------------

    async def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data) -> None:
        """Record a turn_on call. No-op stub."""
        self.calls.append(ApiCall(method="turn_on", args=(entity_id,), kwargs={"domain": domain, **data}))

    async def turn_off(self, entity_id: str, domain: str = "homeassistant") -> None:
        """Record a turn_off call. No-op stub."""
        self.calls.append(ApiCall(method="turn_off", args=(entity_id,), kwargs={"domain": domain}))

    async def toggle_service(self, entity_id: str, domain: str = "homeassistant") -> None:
        """Record a toggle_service call. No-op stub."""
        self.calls.append(ApiCall(method="toggle_service", args=(entity_id,), kwargs={"domain": domain}))

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
                kwargs={"target": target, "return_response": return_response, **data},
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
        self.calls.append(
            ApiCall(
                method="set_state",
                args=(entity_id, state),
                kwargs={"attributes": attributes},
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
                kwargs={"event_data": event_data},
            )
        )
        return {}

    # ------------------------------------------------------------------
    # Read methods — delegate to StateProxy, convert via state registry.
    # ------------------------------------------------------------------

    def _get_raw_state(self, entity_id: str) -> dict:
        """Look up raw state dict from the proxy, raising EntityNotFoundError if absent."""
        raw = self._state_proxy.states.get(entity_id)
        if raw is None:
            raise EntityNotFoundError(f"Entity '{entity_id}' not found in StateProxy (not seeded).")
        return raw

    def _convert_state(self, raw: dict) -> BaseState:
        """Convert a raw HassStateDict to a typed BaseState via the state registry."""
        return self.hassette.state_registry.try_convert_state(raw)

    async def get_state(self, entity_id: str) -> BaseState:
        """Return the typed state for entity_id. Raises EntityNotFoundError if not seeded."""
        raw = self._get_raw_state(entity_id)
        return self._convert_state(raw)

    async def get_states(self) -> list[BaseState]:
        """Return typed states for all seeded entities."""
        return [self._convert_state(raw) for raw in self._state_proxy.states.values()]

    async def get_entity(self, entity_id: str, model: type[Any] | None = None) -> BaseState:
        """Return the typed state for entity_id. Raises EntityNotFoundError if not seeded.

        The model parameter is accepted for signature compatibility with the real Api
        but is not used — RecordingApi always returns BaseState from the state proxy.
        """
        return await self.get_state(entity_id)

    async def get_entity_or_none(self, entity_id: str, model: type[Any] | None = None) -> BaseState | None:
        """Return the typed state for entity_id, or None if not seeded."""
        try:
            return await self.get_state(entity_id)
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
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("get_state_raw")
        raise RuntimeError("unreachable")  # for type checker

    async def get_states_raw(self) -> list[dict]:
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("get_states_raw")
        raise RuntimeError("unreachable")

    async def get_state_value(self, entity_id: str) -> Any:
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("get_state_value")

    async def get_state_value_typed(self, entity_id: str) -> Any:
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("get_state_value_typed")

    async def get_attribute(self, entity_id: str, attribute: str) -> Any:
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("get_attribute")

    async def get_history(self, entity_id: str, *args: Any, **kwargs: Any) -> list:
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("get_history")
        raise RuntimeError("unreachable")

    async def render_template(self, template: str, variables: dict | None = None) -> str:
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("render_template")
        raise RuntimeError("unreachable")

    async def ws_send_and_wait(self, **data: Any) -> Any:
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("ws_send_and_wait")

    async def ws_send_json(self, **data: Any) -> None:
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("ws_send_json")

    async def rest_request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("rest_request")

    async def delete_entity(self, entity_id: str) -> None:
        """Not implemented. Use use_api_server=True for full coverage."""
        _not_implemented("delete_entity")

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
                # Check that all expected kwargs appear in the call's recorded kwargs
                if all(call.kwargs.get(k) == v for k, v in kwargs.items()):
                    return
            raise AssertionError(
                f"'{method}' was called {len(matching)} time(s), but none matched kwargs {kwargs!r}. "
                f"Calls recorded: {[c.kwargs for c in matching]}"
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
        self.calls = []


# ---------------------------------------------------------------------------
# Static conformance assertion: verified at import time by Pyright.
# Runtime cast confirms the pattern is valid.
# ---------------------------------------------------------------------------
_: ApiProtocol = cast("ApiProtocol", RecordingApi)
