"""Unit tests for StateManager.__getattr__ and DomainStates._validate_or_return_from_cache."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from hassette.conversion import STATE_REGISTRY, StateKey
from hassette.exceptions import RegistryNotReadyError, UnableToConvertStateError
from hassette.models.states import BaseState, DeviceTrackerState, LightState, PersonState, SensorState
from hassette.state_manager.state_manager import DomainStates, StateManager
from hassette.test_utils import make_light_state_dict, make_mock_hassette, make_state_dict

BAD_TIMESTAMP = "INVALID-TIMESTAMP"
BAD_CONTEXT = {"id": None, "parent_id": None, "user_id": None}


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

        with patch.object(STATE_REGISTRY, "coerce_and_construct", wraps=STATE_REGISTRY.coerce_and_construct) as spy:
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

        with patch.object(STATE_REGISTRY, "coerce_and_construct", wraps=STATE_REGISTRY.coerce_and_construct) as spy:
            first = ds._validate_or_return_from_cache("light.bedroom", state_1)
            second = ds._validate_or_return_from_cache("light.bedroom", state_2)

        assert first is second
        assert spy.call_count == 1

    def test_changed_state_produces_new_object(self, domain_states: DomainStates[LightState]) -> None:
        ds = domain_states
        state_on = make_light_state_dict("light.bedroom", "on", brightness=150)
        state_off = make_light_state_dict("light.bedroom", "off")

        with patch.object(STATE_REGISTRY, "coerce_and_construct", wraps=STATE_REGISTRY.coerce_and_construct) as spy:
            first = ds._validate_or_return_from_cache("light.bedroom", state_on)
            second = ds._validate_or_return_from_cache("light.bedroom", state_off)

        assert first is not second
        assert spy.call_count == 2
        assert ds._cache["light.bedroom"].model is second


def make_bad_state_dict(entity_id: str = "light.bad") -> dict:
    return make_state_dict(
        entity_id,
        "on",
        last_changed=BAD_TIMESTAMP,
        last_updated=BAD_TIMESTAMP,
        last_reported=BAD_TIMESTAMP,
        context=BAD_CONTEXT,
    )


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
        """Iteration logs-and-continues on un-convertible entity, yields good entities."""
        proxy = MagicMock()

        good_state = make_light_state_dict("light.kitchen", "on", brightness=200)
        bad_state = make_bad_state_dict("light.bad")

        proxy.yield_domain_states.return_value = iter([("light.bad", bad_state), ("light.kitchen", good_state)])

        ds: DomainStates[LightState] = DomainStates(proxy, LightState)

        entity_ids = list(ds)

        assert "light.bad" not in entity_ids
        assert "light.kitchen" in entity_ids
        assert len(entity_ids) == 1


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

    def test_iter_yields_state_keys(self, state_manager: StateManager) -> None:
        """__iter__ yields StateKey objects from the registry."""
        light_key = StateKey(domain="light")
        with patch.object(STATE_REGISTRY, "keys", return_value=iter([light_key])):
            keys_list = list(state_manager)
            assert len(keys_list) == 1
            assert keys_list[0] == light_key

    def test_items_returns_cached_domain_states(self, state_manager: StateManager) -> None:
        """items() returns (key, DomainStates) and populates the cache."""
        with patch.object(STATE_REGISTRY, "items", return_value=iter([("light", LightState)])):
            items_list = list(state_manager.items())
            assert len(items_list) == 1

            _key, domain_states_from_items = items_list[0]
            assert domain_states_from_items._model is LightState

            assert LightState in state_manager._domain_states_cache
            assert state_manager._domain_states_cache[LightState] is domain_states_from_items

    def test_getitem_returns_fresh_uncached_instance(self, state_manager: StateManager) -> None:
        """__getitem__ always returns a fresh DomainStates, not the cached one."""
        with patch.object(STATE_REGISTRY, "items", return_value=iter([("light", LightState)])):
            # Populate cache via items()
            list(state_manager.items())
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


def make_presence_manager(
    mock_hassette: AsyncMock,
    *,
    persons: dict[str, str] | None = None,
    device_trackers: dict[str, str] | None = None,
) -> StateManager:
    """Build a StateManager whose proxy serves person/device_tracker states from the local cache.

    `persons`/`device_trackers` map entity_id -> state value, e.g. {"person.jessica": "home"}.
    """
    data = {
        "person": {eid: make_state_dict(eid, value) for eid, value in (persons or {}).items()},
        "device_tracker": {eid: make_state_dict(eid, value) for eid, value in (device_trackers or {}).items()},
    }

    def resolve(*, domain: str) -> type[BaseState] | None:
        return {"person": PersonState, "device_tracker": DeviceTrackerState}.get(domain)

    proxy = MagicMock()
    proxy.num_domain_states.side_effect = lambda domain: len(data.get(domain, {}))
    proxy.yield_domain_states.side_effect = lambda domain: iter(data.get(domain, {}).items())
    proxy.get_state.side_effect = lambda entity_id: data.get(entity_id.split(".")[0], {}).get(entity_id)

    mock_hassette.state_registry.resolve.side_effect = resolve
    mock_hassette.state_registry.try_convert_state.side_effect = STATE_REGISTRY.try_convert_state
    mock_hassette.state_proxy = proxy
    return StateManager(mock_hassette, parent=mock_hassette)


class TestStateManagerPresence:
    """anybody_home / everybody_home / nobody_home / is_home against the local person cache."""

    def test_anybody_home_true_when_one_person_home(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, persons={"person.jessica": "home", "person.bob": "not_home"})
        assert sm.anybody_home() is True

    def test_anybody_home_false_when_all_away(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, persons={"person.jessica": "not_home", "person.bob": "not_home"})
        assert sm.anybody_home() is False

    def test_everybody_home_true_when_all_home(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, persons={"person.jessica": "home", "person.bob": "home"})
        assert sm.everybody_home() is True

    def test_everybody_home_false_when_one_away(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, persons={"person.jessica": "home", "person.bob": "not_home"})
        assert sm.everybody_home() is False

    def test_nobody_home_true_when_all_away(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, persons={"person.jessica": "not_home"})
        assert sm.nobody_home() is True

    def test_nobody_home_false_when_one_home(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, persons={"person.jessica": "home", "person.bob": "not_home"})
        assert sm.nobody_home() is False

    def test_no_presence_entities(self, mock_hassette: AsyncMock) -> None:
        """With nothing tracked: no one is home, not everyone is home, no one is home."""
        sm = make_presence_manager(mock_hassette)
        assert sm.anybody_home() is False
        assert sm.everybody_home() is False
        assert sm.nobody_home() is True

    def test_device_tracker_fallback_when_no_persons(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, device_trackers={"device_tracker.phone": "home"})
        assert sm.anybody_home() is True
        assert sm.everybody_home() is True

    def test_person_domain_preferred_over_device_tracker(self, mock_hassette: AsyncMock) -> None:
        """A present device_tracker is ignored when the person domain has entities."""
        sm = make_presence_manager(
            mock_hassette,
            persons={"person.jessica": "not_home"},
            device_trackers={"device_tracker.phone": "home"},
        )
        assert sm.anybody_home() is False

    def test_is_home_true_for_present_person(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, persons={"person.jessica": "home"})
        assert sm.is_home("person.jessica") is True

    def test_is_home_false_for_absent_person(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, persons={"person.jessica": "not_home"})
        assert sm.is_home("person.jessica") is False

    def test_is_home_works_for_device_tracker(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, device_trackers={"device_tracker.phone": "home"})
        assert sm.is_home("device_tracker.phone") is True

    def test_is_home_false_for_unknown_entity(self, mock_hassette: AsyncMock) -> None:
        sm = make_presence_manager(mock_hassette, persons={"person.jessica": "home"})
        assert sm.is_home("person.nobody") is False
