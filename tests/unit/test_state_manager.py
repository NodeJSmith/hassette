"""Unit tests for StateManager.__getattr__ and DomainStates._validate_or_return_from_cache."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from hassette.conversion import STATE_REGISTRY
from hassette.exceptions import RegistryNotReadyError, UnableToConvertStateError
from hassette.models.states import BaseState, LightState, SensorState
from hassette.state_manager.state_manager import DomainStates, StateManager
from hassette.test_utils import make_light_state_dict, make_mock_hassette


@pytest.fixture
def mock_hassette() -> AsyncMock:
    hassette = make_mock_hassette(
        sealed=False,
        logging={"log_level": "DEBUG", "state_proxy": "DEBUG", "task_bucket": "DEBUG"},
        lifecycle={"task_cancellation_timeout_seconds": 5},
    )
    hassette.state_registry = MagicMock()
    return hassette


@pytest.fixture
def state_manager(mock_hassette: AsyncMock) -> StateManager:
    return StateManager(mock_hassette, parent=mock_hassette)


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


def make_bad_state_dict(entity_id: str = "light.bad") -> dict:
    """Return a state dict that fails LightState validation (invalid timestamp strings)."""
    return {
        "entity_id": entity_id,
        "state": "on",
        "attributes": {},
        "last_changed": "INVALID-TIMESTAMP",
        "last_updated": "INVALID-TIMESTAMP",
        "last_reported": "INVALID-TIMESTAMP",
        "context": {"id": None, "parent_id": None, "user_id": None},
    }


class TestDomainStatesConversionExceptionType:
    """Exception-type normalization and divergence preservation."""

    def test_subscript_raises_unable_to_convert_not_validation_error(self) -> None:
        """DomainStates[...] raises UnableToConvertStateError, not pydantic.ValidationError."""
        proxy = MagicMock()
        proxy.get_state.return_value = make_bad_state_dict("light.bad")

        ds: DomainStates[LightState] = DomainStates(proxy, LightState)

        with pytest.raises(UnableToConvertStateError) as exc_info:
            ds["light.bad"]

        err = exc_info.value
        assert err.entity_id == "light.bad"
        assert err.state_class is LightState
        # Must NOT be a raw pydantic ValidationError
        assert not isinstance(err, ValidationError)

    def test_domain_get_raises_unable_to_convert_on_bad_state(self) -> None:
        """DomainStates.get raises UnableToConvertStateError on conversion failure."""
        proxy = MagicMock()
        proxy.get_state.return_value = make_bad_state_dict("light.bad")

        ds: DomainStates[LightState] = DomainStates(proxy, LightState)

        with pytest.raises(UnableToConvertStateError) as exc_info:
            ds.get("light.bad")

        assert exc_info.value.entity_id == "light.bad"
        assert exc_info.value.state_class is LightState

    def test_domain_get_returns_none_for_missing_entity(self) -> None:
        """DomainStates.get returns None for a missing entity (unchanged behavior)."""
        proxy = MagicMock()
        proxy.get_state.return_value = None

        ds: DomainStates[LightState] = DomainStates(proxy, LightState)

        result = ds.get("light.missing")
        assert result is None

    def test_state_manager_get_returns_none_on_conversion_failure(self, mock_hassette: AsyncMock) -> None:
        """StateManager.get returns None on conversion failure (divergence preserved)."""
        # Use plain MagicMock for state_proxy and state_registry to avoid AsyncMock coroutine leaks
        mock_state_proxy = MagicMock()
        mock_state_proxy.get_state.return_value = make_bad_state_dict("light.bad")
        mock_state_registry = MagicMock()
        # Use the realistic domain error try_convert_state raises, so the divergence holds even if
        # StateManager.get's broad except is later narrowed to UnableToConvertStateError.
        mock_state_registry.try_convert_state.side_effect = UnableToConvertStateError("light.bad", LightState)
        mock_hassette.state_proxy = mock_state_proxy
        mock_hassette.state_registry = mock_state_registry

        sm = StateManager(mock_hassette, parent=mock_hassette)
        result = sm.get("light.bad")

        assert result is None

    def test_iteration_skips_bad_entity_and_yields_good(self) -> None:
        """iteration logs-and-continues on un-convertible entity, yields good entities."""
        proxy = MagicMock()

        good_state = make_light_state_dict("light.kitchen", "on", brightness=200)
        bad_state = make_bad_state_dict("light.bad")

        proxy.yield_domain_states.return_value = iter([("light.bad", bad_state), ("light.kitchen", good_state)])

        ds: DomainStates[LightState] = DomainStates(proxy, LightState)

        results = list(ds)
        entity_ids = [eid for eid, _ in results]

        assert "light.bad" not in entity_ids
        assert "light.kitchen" in entity_ids
        assert len(results) == 1


class TestStateManagerIterationCache:
    """Iteration routes through _domain_states_cache; __getitem__ stays uncached."""

    def test_values_returns_cached_instance_shared_with_attr_access(self, state_manager: StateManager) -> None:
        """values() and attribute access return the same DomainStates instance."""
        state_manager.hassette.state_registry.resolve.return_value = LightState

        # Prime attribute access to populate the cache
        attr_result = state_manager.light  # goes through __getattr__ → _domain_states_for

        assert LightState in state_manager._domain_states_cache
        assert state_manager._domain_states_cache[LightState] is attr_result

        # values() must return the same cached instance attribute access produced
        with patch.object(STATE_REGISTRY, "values", return_value=iter([LightState])):
            values_list = list(state_manager.values())
        assert values_list == [attr_result]
        assert values_list[0] is attr_result

    def test_iter_returns_cached_domain_states(self, state_manager: StateManager) -> None:
        """__iter__ returns DomainStates from _domain_states_cache."""

        # Patch STATE_REGISTRY to have one entry: LightState
        with patch.object(STATE_REGISTRY, "items", return_value=iter([("light", LightState)])):
            items_list = list(state_manager)
            assert len(items_list) == 1

            _key, domain_states_from_iter = items_list[0]
            assert domain_states_from_iter._model is LightState

            # The instance should be in the cache now
            assert LightState in state_manager._domain_states_cache
            assert state_manager._domain_states_cache[LightState] is domain_states_from_iter

    def test_getitem_returns_fresh_uncached_instance(self, state_manager: StateManager) -> None:
        """__getitem__ always returns a fresh DomainStates, not the cached one."""

        with patch.object(STATE_REGISTRY, "items", return_value=iter([("light", LightState)])):
            # Populate cache via iteration
            list(state_manager)
            cached = state_manager._domain_states_cache.get(LightState)
            assert cached is not None

            # __getitem__ should return a DIFFERENT (fresh) instance
            fresh = state_manager[LightState]
            assert fresh is not cached

    def test_values_method_returns_cached_instances(self, state_manager: StateManager) -> None:
        """values() yields DomainStates instances from the cache."""

        with patch.object(STATE_REGISTRY, "values", return_value=iter([LightState])):
            values_list = list(state_manager.values())
            assert len(values_list) == 1
            val = values_list[0]
            assert val._model is LightState
            assert LightState in state_manager._domain_states_cache
            assert state_manager._domain_states_cache[LightState] is val

    def test_collision_guard_still_passes(self, state_manager: StateManager) -> None:
        """items/values/keys methods on StateManager are not shadowed by DomainStates (unchanged)."""
        result = state_manager.items
        assert callable(result)
        assert not isinstance(result, DomainStates)
