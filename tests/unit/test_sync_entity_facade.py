"""Runtime dispatch tests for generated domain entity sync facades.

Covers:
    AC#2 — CoverEntity.sync, ClimateEntity.sync, LightEntity.sync are instances of
            their respective {Domain}EntitySyncFacade, not BaseEntitySyncFacade.
    AC#3 — CoverEntity.sync.open_cover() dispatches to api.sync.call_service with
            the correct domain/service/target and no extra kwargs.
    AC#4 — ClimateEntity.sync.set_temperature(temperature=21.0) passes the param through.
    AC#5 — LightEntity.sync.turn_on(brightness=128) and .turn_off() route through
            call_service (generated override); isinstance(..., BaseEntitySyncFacade)
            holds (inheritance chain intact).
"""

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from hassette import context
from hassette.models.entities.base import BaseEntitySyncFacade
from hassette.models.entities.climate import ClimateEntity, ClimateEntitySyncFacade
from hassette.models.entities.cover import CoverEntity, CoverEntitySyncFacade
from hassette.models.entities.light import LightEntitySyncFacade
from hassette.models.states import ClimateState, CoverState
from tests.unit.conftest import make_api, make_light_entity

if TYPE_CHECKING:
    from contextvars import Token

    from hassette import Hassette
    from hassette.api.api import Api


# ---------------------------------------------------------------------------
# Entity construction helpers
# ---------------------------------------------------------------------------


def make_cover_entity(api: "Api") -> tuple[CoverEntity, "Token[Hassette]"]:
    """Create a CoverEntity wired to the given api via HASSETTE_INSTANCE context."""
    hassette_mock = MagicMock()
    hassette_mock.api = api
    token = context.HASSETTE_INSTANCE.set(hassette_mock)

    state = CoverState.model_validate({"entity_id": "cover.garage", "state": "closed", "attributes": {}, "context": {}})
    entity = CoverEntity(state=state)
    return entity, token


def make_climate_entity(api: "Api") -> tuple[ClimateEntity, "Token[Hassette]"]:
    """Create a ClimateEntity wired to the given api via HASSETTE_INSTANCE context."""
    hassette_mock = MagicMock()
    hassette_mock.api = api
    token = context.HASSETTE_INSTANCE.set(hassette_mock)

    state = ClimateState.model_validate(
        {"entity_id": "climate.living_room", "state": "heat", "attributes": {}, "context": {}}
    )
    entity = ClimateEntity(state=state)
    return entity, token


# make_light_entity is shared — imported from tests.unit.conftest (also used by
# test_entity_coroutine_conversion). make_cover_entity / make_climate_entity stay
# local here since they have no second consumer.


# ---------------------------------------------------------------------------
# AC#2 — .sync returns the domain-specific facade type
# ---------------------------------------------------------------------------


def test_cover_sync_is_cover_entity_sync_facade() -> None:
    """AC#2: CoverEntity.sync is a CoverEntitySyncFacade instance, not the base."""
    api = make_api()
    entity, token = make_cover_entity(api)
    try:
        assert isinstance(entity.sync, CoverEntitySyncFacade)
        assert type(entity.sync) is CoverEntitySyncFacade
    finally:
        context.HASSETTE_INSTANCE.reset(token)


def test_climate_sync_is_climate_entity_sync_facade() -> None:
    """AC#2: ClimateEntity.sync is a ClimateEntitySyncFacade instance, not the base."""
    api = make_api()
    entity, token = make_climate_entity(api)
    try:
        assert isinstance(entity.sync, ClimateEntitySyncFacade)
        assert type(entity.sync) is ClimateEntitySyncFacade
    finally:
        context.HASSETTE_INSTANCE.reset(token)


def test_light_sync_is_light_entity_sync_facade() -> None:
    """AC#2: LightEntity.sync is a LightEntitySyncFacade instance, not the base."""
    api = make_api()
    entity, token = make_light_entity(api)
    try:
        assert isinstance(entity.sync, LightEntitySyncFacade)
        assert type(entity.sync) is LightEntitySyncFacade
    finally:
        context.HASSETTE_INSTANCE.reset(token)


# ---------------------------------------------------------------------------
# AC#3 — no-param dispatch: CoverEntity.sync.open_cover()
# ---------------------------------------------------------------------------


def test_cover_sync_open_cover_dispatches_call_service() -> None:
    """AC#3: open_cover() calls api.sync.call_service once with correct domain/service/target, no extra kwargs."""
    api = make_api()
    entity, token = make_cover_entity(api)
    try:
        mock_sync = MagicMock()
        api.sync = mock_sync

        entity.sync.open_cover()

        mock_sync.call_service.assert_called_once()
        kwargs = mock_sync.call_service.call_args.kwargs
        assert kwargs["domain"] == "cover"
        assert kwargs["service"] == "open_cover"
        assert kwargs["target"] == {"entity_id": "cover.garage"}
        # A no-param service forwards exactly these three keys — pin the full set so
        # both an extra kwarg and a missing expected key are caught.
        assert set(kwargs) == {"domain", "service", "target"}
    finally:
        context.HASSETTE_INSTANCE.reset(token)


# ---------------------------------------------------------------------------
# AC#4 — required-param dispatch: ClimateEntity.sync.set_temperature()
# ---------------------------------------------------------------------------


def test_climate_sync_set_temperature_passes_param_through() -> None:
    """AC#4: set_temperature(temperature=21.0) passes the temperature param through to call_service."""
    api = make_api()
    entity, token = make_climate_entity(api)
    try:
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
        assert kwargs["target"] == {"entity_id": "climate.living_room"}
        assert kwargs["temperature"] == 21.0
    finally:
        context.HASSETTE_INSTANCE.reset(token)


# ---------------------------------------------------------------------------
# AC#5 — optional-param dispatch + inheritance intact: LightEntity.sync.turn_on/turn_off
#
# The turn_on dispatch is also exercised by
# test_entity_coroutine_conversion.test_entity_sync_turn_on_registers. The overlap is
# intentional — that test pins it under AC#11 (forgotten-await work); this one pins it
# under AC#5 (entity sync facade) alongside turn_off and the inheritance check.
# ---------------------------------------------------------------------------


def test_light_sync_turn_on_dispatches_via_call_service() -> None:
    """AC#5: LightEntity.sync.turn_on(brightness=128) routes through call_service (generated override)."""
    api = make_api()
    entity, token = make_light_entity(api)
    try:
        mock_sync = MagicMock()
        api.sync = mock_sync

        entity.sync.turn_on(brightness=128)

        # The generated facade forwards all light params (many default to None).
        # Assert the meaningful subset without coupling to every optional param.
        mock_sync.call_service.assert_called_once()
        kwargs = mock_sync.call_service.call_args.kwargs
        assert kwargs["domain"] == "light"
        assert kwargs["service"] == "turn_on"
        assert kwargs["target"] == {"entity_id": "light.kitchen"}
        assert kwargs["brightness"] == 128
    finally:
        context.HASSETTE_INSTANCE.reset(token)


def test_light_sync_turn_off_dispatches_via_call_service() -> None:
    """AC#5: LightEntity.sync.turn_off() routes through call_service (generated override)."""
    api = make_api()
    entity, token = make_light_entity(api)
    try:
        mock_sync = MagicMock()
        api.sync = mock_sync

        entity.sync.turn_off()

        mock_sync.call_service.assert_called_once()
        kwargs = mock_sync.call_service.call_args.kwargs
        assert kwargs["domain"] == "light"
        assert kwargs["service"] == "turn_off"
        assert kwargs["target"] == {"entity_id": "light.kitchen"}
    finally:
        context.HASSETTE_INSTANCE.reset(token)


def test_light_sync_inherits_base_entity_sync_facade() -> None:
    """AC#5: LightEntitySyncFacade is a subclass of BaseEntitySyncFacade (FR#5 inheritance chain)."""
    api = make_api()
    entity, token = make_light_entity(api)
    try:
        assert isinstance(entity.sync, BaseEntitySyncFacade)
    finally:
        context.HASSETTE_INSTANCE.reset(token)


# ---------------------------------------------------------------------------
# AC#5 — .sync caching: same instance returned on repeated access
# ---------------------------------------------------------------------------


def test_sync_property_caches_facade_instance() -> None:
    """The .sync property caches the facade — repeated access returns the same object."""
    api = make_api()
    entity, token = make_light_entity(api)
    try:
        first = entity.sync
        second = entity.sync
        assert first is second
    finally:
        context.HASSETTE_INSTANCE.reset(token)
