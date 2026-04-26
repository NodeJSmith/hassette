"""Unit tests for StateManager.__getattr__ and DomainStates._validate_or_return_from_cache."""

from unittest.mock import MagicMock, patch

import pytest

from hassette.exceptions import RegistryNotReadyError
from hassette.models.states import BaseState, LightState, SensorState
from hassette.state_manager.state_manager import DomainStates, StateManager
from hassette.test_utils import make_light_state_dict


def _make_hassette_mock() -> MagicMock:
    """Return a MagicMock Hassette with just enough attributes for StateManager.__init__."""
    hassette = MagicMock()
    hassette.config.state_proxy_log_level = "DEBUG"
    hassette.config.log_level = "DEBUG"
    hassette.config.task_bucket_log_level = "DEBUG"
    hassette.config.task_cancellation_timeout_seconds = 5
    return hassette


@pytest.fixture
def mock_hassette() -> MagicMock:
    return _make_hassette_mock()


@pytest.fixture
def state_manager(mock_hassette: MagicMock) -> StateManager:
    return StateManager(mock_hassette, parent=mock_hassette)


# ---------------------------------------------------------------------------
# TestStateManagerGetattr — __getattr__ dispatch logic
# ---------------------------------------------------------------------------


class TestStateManagerGetattr:
    def test_underscore_prefix_raises_attribute_error(self, state_manager: StateManager) -> None:
        with pytest.raises(AttributeError, match="has no attribute '_internal_attr'"):
            state_manager._internal_attr  # noqa: B018

    def test_reserved_name_raises_attribute_error(self, state_manager: StateManager) -> None:
        with pytest.raises(AttributeError, match="has no attribute 'name'"):
            state_manager.name  # noqa: B018

    def test_registry_not_ready_raises_attribute_error(self, state_manager: StateManager) -> None:
        state_manager.hassette.state_registry.resolve.side_effect = RegistryNotReadyError()

        with pytest.raises(AttributeError, match="State registry not initialized") as exc_info:
            state_manager.light  # noqa: B018

        assert exc_info.value.__suppress_context__ is True

    def test_unregistered_domain_raises_attribute_error(self, state_manager: StateManager) -> None:
        state_manager.hassette.state_registry.resolve.return_value = None

        with pytest.raises(AttributeError, match="not registered in the state registry"):
            state_manager.totally_unknown_domain  # noqa: B018

    def test_registered_domain_returns_domain_states(self, state_manager: StateManager) -> None:
        state_manager.hassette.state_registry.resolve.return_value = LightState

        result = state_manager.light

        assert isinstance(result, DomainStates)
        assert result._model is LightState

    def test_registered_domain_is_cached_on_second_access(self, state_manager: StateManager) -> None:
        state_manager.hassette.state_registry.resolve.return_value = LightState

        first = state_manager.light
        second = state_manager.light

        assert first is second

    def test_different_domains_return_different_domain_states(self, state_manager: StateManager) -> None:
        def resolve_side_effect(*, domain: str) -> type[BaseState] | None:
            return {"light": LightState, "sensor": SensorState}.get(domain)

        state_manager.hassette.state_registry.resolve.side_effect = resolve_side_effect

        light_states = state_manager.light
        sensor_states = state_manager.sensor

        assert light_states is not sensor_states
        assert light_states._model is LightState
        assert sensor_states._model is SensorState

    def test_domain_named_items_does_not_collide_with_items_method(self, state_manager: StateManager) -> None:
        result = state_manager.items
        assert callable(result)
        assert not isinstance(result, DomainStates)


# ---------------------------------------------------------------------------
# TestDomainStatesCacheValidation — _validate_or_return_from_cache logic
# ---------------------------------------------------------------------------


@pytest.fixture
def domain_states() -> DomainStates[LightState]:
    proxy = MagicMock()
    return DomainStates(proxy, LightState)


class TestDomainStatesCacheValidation:
    def test_context_id_match_returns_cached_object(self, domain_states: DomainStates[LightState]) -> None:
        ds = domain_states
        ts = "2026-01-01T00:00:00+00:00"
        ctx = {"id": "fixed-context-id", "parent_id": None, "user_id": None}

        state_1 = make_light_state_dict(
            "light.bedroom",
            "on",
            brightness=150,
            last_changed=ts,
            last_updated=ts,
            context=ctx,
        )
        state_2 = make_light_state_dict(
            "light.bedroom",
            "on",
            brightness=150,
            last_changed=ts,
            last_updated=ts,
            context=ctx,
        )

        with patch.object(LightState, "model_validate", wraps=LightState.model_validate) as spy:
            first = ds._validate_or_return_from_cache("light.bedroom", state_1)
            second = ds._validate_or_return_from_cache("light.bedroom", state_2)

        assert first is second
        assert spy.call_count == 1

    def test_frozen_state_match_returns_cached_object(self, domain_states: DomainStates[LightState]) -> None:
        ds = domain_states
        ts = "2026-01-01T00:00:00+00:00"

        state_1 = make_light_state_dict(
            "light.bedroom",
            "on",
            brightness=150,
            last_changed=ts,
            last_updated=ts,
            context={"id": None, "parent_id": None, "user_id": None},
        )
        state_2 = make_light_state_dict(
            "light.bedroom",
            "on",
            brightness=150,
            last_changed=ts,
            last_updated=ts,
            context={"id": None, "parent_id": None, "user_id": None},
        )

        with patch.object(LightState, "model_validate", wraps=LightState.model_validate) as spy:
            first = ds._validate_or_return_from_cache("light.bedroom", state_1)
            second = ds._validate_or_return_from_cache("light.bedroom", state_2)

        assert first is second
        assert spy.call_count == 1

    def test_changed_state_produces_new_object(self, domain_states: DomainStates[LightState]) -> None:
        ds = domain_states
        state_on = make_light_state_dict("light.bedroom", "on", brightness=150)
        state_off = make_light_state_dict("light.bedroom", "off")

        with patch.object(LightState, "model_validate", wraps=LightState.model_validate) as spy:
            first = ds._validate_or_return_from_cache("light.bedroom", state_on)
            second = ds._validate_or_return_from_cache("light.bedroom", state_off)

        assert first is not second
        assert spy.call_count == 2
        assert ds._cache["light.bedroom"].model is second
