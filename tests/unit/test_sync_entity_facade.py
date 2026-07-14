"""Runtime dispatch tests for generated domain entity sync facades.

Covers:
    — CoverEntity.sync, ClimateEntity.sync, LightEntity.sync are instances of
      their respective {Domain}EntitySyncFacade, not BaseEntitySyncFacade.
    — CoverEntity.sync.open_cover() dispatches to api.sync.call_service with
      the correct domain/service/target and no extra kwargs.
    — ClimateEntity.sync.set_temperature(temperature=21.0) passes the param through.
    — LightEntity.sync.turn_on(brightness=128) and .turn_off() route through
      call_service (generated override); isinstance(..., BaseEntitySyncFacade)
      holds (inheritance chain intact).
    — LockEntity does NOT expose turn_on/turn_off/toggle (those services don't
      exist for the lock domain in HA).
"""

from contextlib import contextmanager
from typing import TYPE_CHECKING, TypeVar
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from hassette import context
from hassette.models.entities.base import BaseEntity, BaseEntitySyncFacade
from hassette.models.entities.climate import ClimateEntity, ClimateEntitySyncFacade
from hassette.models.entities.cover import CoverEntity, CoverEntitySyncFacade
from hassette.models.entities.light import LightEntitySyncFacade
from hassette.models.entities.lock import LockEntity, LockEntitySyncFacade
from hassette.models.states import ClimateState, CoverState, LockState
from tests.unit.conftest import make_api, make_light_entity

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextvars import Token

    from hassette import Hassette
    from hassette.api.api import Api

COVER_ENTITY_ID = "cover.garage"
CLIMATE_ENTITY_ID = "climate.living_room"
LOCK_ENTITY_ID = "lock.front_door"

EntityT = TypeVar("EntityT", bound=BaseEntity)
StateModelT = TypeVar("StateModelT", bound=BaseModel)


# Entity construction helpers


def make_domain_entity(
    api: "Api", *, entity_id: str, state: str, entity_cls: type[EntityT], state_cls: type[StateModelT]
) -> "tuple[EntityT, Token[Hassette]]":
    """Create a domain entity wired to the given api via HASSETTE_INSTANCE context.

    Parameterized factory covering cover/climate/lock — the three domains this module
    tests beyond light. make_light_entity (imported from conftest) stays separate since
    it is also shared with test_entity_coroutine_conversion.
    """
    hassette_mock = MagicMock()
    hassette_mock.api = api
    token = context.HASSETTE_INSTANCE.set(hassette_mock)

    entity_state = state_cls.model_validate({"entity_id": entity_id, "state": state, "attributes": {}, "context": {}})
    entity = entity_cls(state=entity_state)
    return entity, token


@contextmanager
def entity_session(entity_and_token: "tuple[EntityT, Token[Hassette]]") -> "Iterator[EntityT]":
    """Yield the entity from a (entity, token) pair and reset the context var on exit.

    Wraps the output of make_domain_entity / make_light_entity so tests don't repeat
    the try/finally reset boilerplate.
    """
    entity, token = entity_and_token
    try:
        yield entity
    finally:
        context.HASSETTE_INSTANCE.reset(token)


def make_cover_entity(api: "Api") -> "tuple[CoverEntity, Token[Hassette]]":
    return make_domain_entity(
        api, entity_id=COVER_ENTITY_ID, state="closed", entity_cls=CoverEntity, state_cls=CoverState
    )


def make_climate_entity(api: "Api") -> "tuple[ClimateEntity, Token[Hassette]]":
    return make_domain_entity(
        api, entity_id=CLIMATE_ENTITY_ID, state="heat", entity_cls=ClimateEntity, state_cls=ClimateState
    )


def make_lock_entity(api: "Api") -> "tuple[LockEntity, Token[Hassette]]":
    return make_domain_entity(api, entity_id=LOCK_ENTITY_ID, state="locked", entity_cls=LockEntity, state_cls=LockState)


# .sync returns the domain-specific facade type


def test_cover_sync_is_cover_entity_sync_facade() -> None:
    """CoverEntity.sync is a CoverEntitySyncFacade instance, not the base."""
    api = make_api()
    with entity_session(make_cover_entity(api)) as entity:
        assert isinstance(entity.sync, CoverEntitySyncFacade)
        assert type(entity.sync) is CoverEntitySyncFacade


def test_climate_sync_is_climate_entity_sync_facade() -> None:
    """ClimateEntity.sync is a ClimateEntitySyncFacade instance, not the base."""
    api = make_api()
    with entity_session(make_climate_entity(api)) as entity:
        assert isinstance(entity.sync, ClimateEntitySyncFacade)
        assert type(entity.sync) is ClimateEntitySyncFacade


def test_light_sync_is_light_entity_sync_facade() -> None:
    """LightEntity.sync is a LightEntitySyncFacade instance, not the base."""
    api = make_api()
    with entity_session(make_light_entity(api)) as entity:
        assert isinstance(entity.sync, LightEntitySyncFacade)
        assert type(entity.sync) is LightEntitySyncFacade


# No-param dispatch: CoverEntity.sync.open_cover()


def test_cover_sync_open_cover_dispatches_call_service() -> None:
    """open_cover() calls api.sync.call_service once with correct domain/service/target, no extra kwargs."""
    api = make_api()
    with entity_session(make_cover_entity(api)) as entity:
        mock_sync = MagicMock()
        api.sync = mock_sync

        entity.sync.open_cover()

        mock_sync.call_service.assert_called_once()
        kwargs = mock_sync.call_service.call_args.kwargs
        assert kwargs["domain"] == "cover"
        assert kwargs["service"] == "open_cover"
        assert kwargs["target"] == {"entity_id": COVER_ENTITY_ID}
        # A no-param service forwards exactly these three keys — pin the full set so
        # both an extra kwarg and a missing expected key are caught.
        assert set(kwargs) == {"domain", "service", "target"}


# Required-param dispatch: ClimateEntity.sync.set_temperature()


def test_climate_sync_set_temperature_passes_param_through() -> None:
    """set_temperature(temperature=21.0) passes the temperature param through to call_service."""
    api = make_api()
    with entity_session(make_climate_entity(api)) as entity:
        mock_sync = MagicMock()
        api.sync = mock_sync

        entity.sync.set_temperature(temperature=21.0)

        # set_temperature forwards all climate params (hvac_mode, target_temp_high,
        # target_temp_low default to None). Assert the meaningful dispatch args
        # without coupling to every optional param.
        mock_sync.call_service.assert_called_once()
        kwargs = mock_sync.call_service.call_args.kwargs
        assert kwargs["domain"] == "climate"
        assert kwargs["service"] == "set_temperature"
        assert kwargs["target"] == {"entity_id": CLIMATE_ENTITY_ID}
        assert kwargs["temperature"] == 21.0


# Optional-param dispatch + inheritance intact: LightEntity.sync.turn_on/turn_off
#
# The turn_on dispatch is also exercised by
# test_entity_coroutine_conversion.test_entity_sync_turn_on_registers. The overlap is
# intentional — that test pins the same dispatch path alongside turn_off and the inheritance check.


def test_light_sync_turn_on_dispatches_via_call_service() -> None:
    """LightEntity.sync.turn_on(brightness=128) routes through call_service (generated override)."""
    api = make_api()
    with entity_session(make_light_entity(api)) as entity:
        mock_sync = MagicMock()
        api.sync = mock_sync

        entity.sync.turn_on(brightness=128)

        # The generated facade forwards all light params (many default to None).
        # Assert the meaningful subset without coupling to every optional param.
        #
        # Note for test authors: this mock (and RecordingApi.sync) records the None-valued
        # optional kwargs as-is. Production drops them — Api._call_service filters
        # `{k: v for k, v in data.items() if v is not None}` before the WebSocket payload — so
        # a kwargs-pinning assertion via the mock/recorder sees Nones that never reach HA.
        mock_sync.call_service.assert_called_once()
        kwargs = mock_sync.call_service.call_args.kwargs
        assert kwargs["domain"] == "light"
        assert kwargs["service"] == "turn_on"
        assert kwargs["target"] == {"entity_id": "light.kitchen"}
        assert kwargs["brightness"] == 128


def test_light_sync_turn_off_dispatches_via_call_service() -> None:
    """LightEntity.sync.turn_off() routes through call_service (generated override)."""
    api = make_api()
    with entity_session(make_light_entity(api)) as entity:
        mock_sync = MagicMock()
        api.sync = mock_sync

        entity.sync.turn_off()

        mock_sync.call_service.assert_called_once()
        kwargs = mock_sync.call_service.call_args.kwargs
        assert kwargs["domain"] == "light"
        assert kwargs["service"] == "turn_off"
        assert kwargs["target"] == {"entity_id": "light.kitchen"}


def test_light_sync_inherits_base_entity_sync_facade() -> None:
    """LightEntitySyncFacade is a subclass of BaseEntitySyncFacade (inheritance chain intact)."""
    api = make_api()
    with entity_session(make_light_entity(api)) as entity:
        assert isinstance(entity.sync, BaseEntitySyncFacade)


# .sync caching: same instance returned on repeated access


def test_sync_property_caches_facade_instance() -> None:
    """The .sync property caches the facade — repeated access returns the same object."""
    api = make_api()
    with entity_session(make_light_entity(api)) as entity:
        first = entity.sync
        second = entity.sync
        assert first is second


# Serviceless domain: LockEntity does NOT expose turn_on/turn_off/toggle
#
# Lock has no lock.turn_on / lock.turn_off / lock.toggle services in HA.
# BaseEntity no longer provides these methods, so they must be absent.


def test_lock_sync_is_lock_entity_sync_facade() -> None:
    """LockEntity.sync is a LockEntitySyncFacade instance, not the base."""
    api = make_api()
    with entity_session(make_lock_entity(api)) as entity:
        assert isinstance(entity.sync, LockEntitySyncFacade)
        assert type(entity.sync) is LockEntitySyncFacade


@pytest.mark.parametrize("method", ["turn_on", "turn_off", "toggle"])
def test_lock_entity_does_not_have_base_service_methods(method: str) -> None:
    """LockEntity must not expose turn_on/turn_off/toggle (no such HA services)."""
    api = make_api()
    with entity_session(make_lock_entity(api)) as entity:
        assert not hasattr(entity, method), f"LockEntity should not have {method}"


@pytest.mark.parametrize("method", ["turn_on", "turn_off", "toggle"])
def test_lock_sync_does_not_have_base_service_methods(method: str) -> None:
    """LockEntitySyncFacade must not expose turn_on/turn_off/toggle."""
    api = make_api()
    with entity_session(make_lock_entity(api)) as entity:
        assert not hasattr(entity.sync, method), f"LockEntitySyncFacade should not have {method}"
