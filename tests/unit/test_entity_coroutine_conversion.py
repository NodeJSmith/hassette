"""Tests for entity service method conversion to def -> Coroutine[Any, Any, None].

Covers:
    FR#13 — every generated entity service method and BaseEntity.turn_on/turn_off/toggle
             is def -> Coroutine[Any, Any, None]; forgotten await emits
             HassetteForgottenAwaitWarning attributed to the caller.
    AC#11 — LightEntity.turn_on, HumidifierEntity.set_humidity, BaseEntity.toggle
             warn on forgotten await (attributed), behave correctly when awaited,
             and entity.sync.turn_on() still registers; regen check confirms
             models/entities/*.py use def -> Coroutine[...].
"""

import collections.abc
import gc
import inspect
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from hassette import context
from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.models.entities.base import BaseEntity
from hassette.models.entities.humidifier import HumidifierEntity
from hassette.models.entities.light import LightEntity
from hassette.models.states import HumidifierState, LightState
from tests.unit.conftest import make_api

if TYPE_CHECKING:
    from contextvars import Token

    from hassette import Hassette
    from hassette.api.api import Api


def make_light_entity(api: "Api") -> tuple[LightEntity, "Token[Hassette]"]:
    """Create a LightEntity wired to the given api via HASSETTE_INSTANCE context."""
    hassette_mock = MagicMock()
    hassette_mock.api = api
    token = context.HASSETTE_INSTANCE.set(hassette_mock)

    state = LightState.model_validate({"entity_id": "light.kitchen", "state": "off", "attributes": {}, "context": {}})
    entity = LightEntity(state=state)
    # token stays set for the test duration — caller cleans up if needed
    # (or we rely on contextvars scoping per coroutine)
    return entity, token


def make_humidifier_entity(api: "Api") -> tuple[HumidifierEntity, "Token[Hassette]"]:
    """Create a HumidifierEntity wired to the given api via HASSETTE_INSTANCE context."""
    hassette_mock = MagicMock()
    hassette_mock.api = api
    token = context.HASSETTE_INSTANCE.set(hassette_mock)

    state = HumidifierState.model_validate(
        {"entity_id": "humidifier.bedroom", "state": "off", "attributes": {}, "context": {}}
    )
    entity = HumidifierEntity(state=state)
    return entity, token


# ---------------------------------------------------------------------------
# FR#13 / AC#11 regen check — generated files use def -> Coroutine[...], not async def
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENTITIES_DIR = _REPO_ROOT / "src" / "hassette" / "models" / "entities"
_MANIFEST = _REPO_ROOT / ".generated-manifest"


def _manifest_entity_files() -> list[str]:
    """Read .generated-manifest and return basenames of generated entity files (excluding __init__)."""
    lines = _MANIFEST.read_text().splitlines()
    return [
        Path(line).name
        for line in lines
        if line.startswith("src/hassette/models/entities/") and not line.endswith("__init__.py")
    ]


_GENERATED_ENTITY_FILES = _manifest_entity_files()
# An empty list would make the parametrized checks below vacuously pass — exactly the
# silent-skip failure mode this manifest-driven guard exists to catch.
assert _GENERATED_ENTITY_FILES, ".generated-manifest lists no entity files — regen guard cannot run"


@pytest.mark.parametrize("filename", _GENERATED_ENTITY_FILES)
def test_generated_entity_file_uses_def_not_async_def(filename: str) -> None:
    """FR#13 regen check: every manifest-listed entity file must not contain 'async def' for service methods.

    Parametrized over the full .generated-manifest so any domain silently dropped from
    regeneration causes this test to fail rather than go undetected.
    """
    entity_path = _ENTITIES_DIR / filename
    assert entity_path.exists(), f"{entity_path} does not exist"
    source = entity_path.read_text()
    assert "async def" not in source, (
        f"{filename} still contains 'async def' — regenerate from updated template. "
        "Run: uv run hassette-codegen generate --ha-core-path ~/source/core"
    )


@pytest.mark.parametrize("filename", _GENERATED_ENTITY_FILES)
def test_generated_entity_file_imports_coroutine_and_any(filename: str) -> None:
    """FR#13 regen check: every manifest-listed entity file must import Coroutine and Any unconditionally."""
    entity_path = _ENTITIES_DIR / filename
    source = entity_path.read_text()
    assert "from collections.abc import Coroutine" in source, (
        f"{filename} missing 'from collections.abc import Coroutine'"
    )
    assert "from typing import Any" in source, f"{filename} missing 'from typing import Any'"


# ---------------------------------------------------------------------------
# FR#13 — service methods are plain def, not async def
# ---------------------------------------------------------------------------


def test_light_entity_turn_on_is_plain_def() -> None:
    """FR#13: LightEntity.turn_on must be a plain def, not async def."""
    assert not inspect.iscoroutinefunction(LightEntity.turn_on), (
        "LightEntity.turn_on must be a plain def after T07 conversion"
    )


def test_humidifier_entity_set_humidity_is_plain_def() -> None:
    """FR#13: HumidifierEntity.set_humidity must be a plain def, not async def."""
    assert not inspect.iscoroutinefunction(HumidifierEntity.set_humidity), (
        "HumidifierEntity.set_humidity must be a plain def after T07 conversion"
    )


def test_base_entity_toggle_is_plain_def() -> None:
    """FR#13: BaseEntity.toggle must be a plain def, not async def."""
    assert not inspect.iscoroutinefunction(BaseEntity.toggle), (
        "BaseEntity.toggle must be a plain def after T07 conversion"
    )


def test_base_entity_turn_on_is_plain_def() -> None:
    """FR#13: BaseEntity.turn_on must be a plain def, not async def."""
    assert not inspect.iscoroutinefunction(BaseEntity.turn_on), (
        "BaseEntity.turn_on must be a plain def after T07 conversion"
    )


def test_base_entity_turn_off_is_plain_def() -> None:
    """FR#13: BaseEntity.turn_off must be a plain def, not async def."""
    assert not inspect.iscoroutinefunction(BaseEntity.turn_off), (
        "BaseEntity.turn_off must be a plain def after T07 conversion"
    )


# ---------------------------------------------------------------------------
# FR#13 — return annotation resolves to collections.abc.Coroutine
# ---------------------------------------------------------------------------


def _get_return_annotation_origin(cls, method_name: str):
    method = getattr(cls, method_name)
    raw = getattr(method, "__annotations__", {}).get("return")
    if raw is None:
        return None
    if isinstance(raw, str):
        module = sys.modules[cls.__module__]
        raw = eval(raw, vars(module))  # noqa: S307
    return getattr(raw, "__origin__", None)


def test_light_entity_turn_on_return_annotation_is_coroutine() -> None:
    """AC#11: LightEntity.turn_on return annotation __origin__ must be collections.abc.Coroutine."""
    origin = _get_return_annotation_origin(LightEntity, "turn_on")
    assert origin is collections.abc.Coroutine, (
        f"LightEntity.turn_on return annotation __origin__ = {origin!r}, expected Coroutine"
    )


def test_humidifier_entity_set_humidity_return_annotation_is_coroutine() -> None:
    """AC#11: HumidifierEntity.set_humidity return annotation __origin__ must be Coroutine."""
    origin = _get_return_annotation_origin(HumidifierEntity, "set_humidity")
    assert origin is collections.abc.Coroutine, (
        f"HumidifierEntity.set_humidity return annotation __origin__ = {origin!r}, expected Coroutine"
    )


def test_base_entity_toggle_return_annotation_is_coroutine() -> None:
    """AC#11: BaseEntity.toggle return annotation __origin__ must be collections.abc.Coroutine."""
    origin = _get_return_annotation_origin(BaseEntity, "toggle")
    assert origin is collections.abc.Coroutine, (
        f"BaseEntity.toggle return annotation __origin__ = {origin!r}, expected Coroutine"
    )


# ---------------------------------------------------------------------------
# AC#11 — forgotten await warns; attribution points at caller (this test file)
# ---------------------------------------------------------------------------


def test_light_entity_turn_on_forgotten_await_warns() -> None:
    """AC#11: dropping un-awaited LightEntity.turn_on() emits HassetteForgottenAwaitWarning."""
    api = make_api()
    entity, token = make_light_entity(api)
    try:
        with pytest.warns(HassetteForgottenAwaitWarning) as record:
            _ = entity.turn_on()
            del _
            gc.collect()
        assert len(record) >= 1
        warning_msg = str(record[0].message)
        assert __file__ in warning_msg or Path(__file__).stem in warning_msg, (
            f"Warning not attributed to caller: {warning_msg!r}"
        )
    finally:
        context.HASSETTE_INSTANCE.reset(token)


def test_humidifier_entity_set_humidity_forgotten_await_warns() -> None:
    """AC#11: dropping un-awaited HumidifierEntity.set_humidity() emits HassetteForgottenAwaitWarning."""
    api = make_api()
    entity, token = make_humidifier_entity(api)
    try:
        with pytest.warns(HassetteForgottenAwaitWarning) as record:
            _ = entity.set_humidity(humidity=60)
            del _
            gc.collect()
        assert len(record) >= 1
        warning_msg = str(record[0].message)
        assert __file__ in warning_msg or Path(__file__).stem in warning_msg, (
            f"Warning not attributed to caller: {warning_msg!r}"
        )
    finally:
        context.HASSETTE_INSTANCE.reset(token)


def test_base_entity_toggle_forgotten_await_warns() -> None:
    """AC#11: dropping un-awaited BaseEntity.toggle() emits HassetteForgottenAwaitWarning."""
    api = make_api()
    entity, token = make_light_entity(api)  # LightEntity is a BaseEntity
    try:
        with pytest.warns(HassetteForgottenAwaitWarning) as record:
            _ = entity.toggle()
            del _
            gc.collect()
        assert len(record) >= 1
        warning_msg = str(record[0].message)
        assert __file__ in warning_msg or Path(__file__).stem in warning_msg, (
            f"Warning not attributed to caller: {warning_msg!r}"
        )
    finally:
        context.HASSETTE_INSTANCE.reset(token)


# ---------------------------------------------------------------------------
# AC#11 — awaited call acts correctly (no warning, None returned)
# ---------------------------------------------------------------------------


async def test_light_entity_turn_on_awaited_returns_none_no_warning() -> None:
    """AC#11: awaiting LightEntity.turn_on() returns None and emits no warning."""
    api = make_api()
    entity, token = make_light_entity(api)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = await entity.turn_on(brightness=200)
        assert result is None
    finally:
        context.HASSETTE_INSTANCE.reset(token)


async def test_humidifier_entity_set_humidity_awaited_returns_none_no_warning() -> None:
    """AC#11: awaiting HumidifierEntity.set_humidity() returns None and emits no warning."""
    api = make_api()
    entity, token = make_humidifier_entity(api)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = await entity.set_humidity(humidity=60)
        assert result is None
    finally:
        context.HASSETTE_INSTANCE.reset(token)


async def test_base_entity_toggle_awaited_returns_none_no_warning() -> None:
    """AC#11: awaiting BaseEntity.toggle() returns None and emits no warning."""
    api = make_api()
    entity, token = make_light_entity(api)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = await entity.toggle()
        assert result is None
    finally:
        context.HASSETTE_INSTANCE.reset(token)


# ---------------------------------------------------------------------------
# AC#11 — entity.sync.turn_on() still registers (regression via api.sync path)
# ---------------------------------------------------------------------------


def test_entity_sync_turn_on_registers() -> None:
    """AC#11: entity.sync.turn_on() still executes via api.sync (BaseEntitySyncFacade route)."""
    api = make_api()
    entity, token = make_light_entity(api)
    try:
        # BaseEntitySyncFacade.turn_on routes through self.entity.api.sync.turn_on(...)
        # which goes via run_sync. We just verify no exception and the call passes through.
        # Patch api.sync to a mock so we don't need a real event loop here.
        mock_sync = MagicMock()
        api.sync = mock_sync

        entity.sync.turn_on(brightness=100)
        mock_sync.turn_on.assert_called_once_with(entity.entity_id, entity.domain, brightness=100)
    finally:
        context.HASSETTE_INSTANCE.reset(token)
