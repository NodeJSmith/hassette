"""Tests for entity service method conversion to def -> Coroutine[Any, Any, None].

Covers:
    - Every generated entity service method is def -> Coroutine[Any, Any, None];
      forgotten await emits HassetteForgottenAwaitWarning attributed to the caller.
    - LightEntity.turn_on, HumidifierEntity.set_humidity, LightEntity.toggle
      warn on forgotten await (attributed), behave correctly when awaited,
      and entity.sync.turn_on() still registers; regen check confirms
      models/entities/*.py use def -> Coroutine[...].
"""

import collections.abc
import gc
import inspect
import sys
import warnings
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from hassette.api.api import Api
from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.models.entities.humidifier import HumidifierEntity
from hassette.models.entities.light import LightEntity
from hassette.models.states import HumidifierState
from tests.unit.conftest import entity_session, make_api, make_domain_entity, make_light_entity

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENTITIES_DIR = _REPO_ROOT / "src" / "hassette" / "models" / "entities"
_MANIFEST = _REPO_ROOT / ".generated-manifest"

if TYPE_CHECKING:
    from contextvars import Token

    from hassette import Hassette

EntityFactory = Callable[[Api], "tuple[Any, Token[Hassette]]"]
ServiceCall = Callable[[Any], Coroutine[Any, Any, None]]


# dup-ignore-start: documented per-file opt-in pattern (see drain_forgotten_await_handles docstring
# in tests/unit/conftest.py) — every warning-heavy test module repeats this one-line wrapper by design.
@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""
    # dup-ignore-end


def make_bedroom_humidifier(api: Api) -> "tuple[HumidifierEntity, Token[Hassette]]":
    return make_domain_entity(
        api, entity_id="humidifier.bedroom", state="off", entity_cls=HumidifierEntity, state_cls=HumidifierState
    )


# Regen check — generated files use def -> Coroutine[...], not async def


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
    """Every manifest-listed entity file must not contain 'async def' for service methods.

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
    """Every manifest-listed entity file must import Coroutine and Any unconditionally."""
    entity_path = _ENTITIES_DIR / filename
    source = entity_path.read_text()
    assert "from collections.abc import Coroutine" in source, (
        f"{filename} missing 'from collections.abc import Coroutine'"
    )
    assert "from typing import Any" in source, f"{filename} missing 'from typing import Any'"


# Service methods are plain def, not async def


def test_light_entity_turn_on_is_plain_def() -> None:
    """LightEntity.turn_on must be a plain def, not async def."""
    assert not inspect.iscoroutinefunction(LightEntity.turn_on), (
        "LightEntity.turn_on must be a plain def after conversion"
    )


def test_humidifier_entity_set_humidity_is_plain_def() -> None:
    """HumidifierEntity.set_humidity must be a plain def, not async def."""
    assert not inspect.iscoroutinefunction(HumidifierEntity.set_humidity), (
        "HumidifierEntity.set_humidity must be a plain def after conversion"
    )


# Return annotation resolves to collections.abc.Coroutine


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
    """LightEntity.turn_on return annotation __origin__ must be collections.abc.Coroutine."""
    origin = _get_return_annotation_origin(LightEntity, "turn_on")
    assert origin is collections.abc.Coroutine, (
        f"LightEntity.turn_on return annotation __origin__ = {origin!r}, expected Coroutine"
    )


def test_humidifier_entity_set_humidity_return_annotation_is_coroutine() -> None:
    """HumidifierEntity.set_humidity return annotation __origin__ must be Coroutine."""
    origin = _get_return_annotation_origin(HumidifierEntity, "set_humidity")
    assert origin is collections.abc.Coroutine, (
        f"HumidifierEntity.set_humidity return annotation __origin__ = {origin!r}, expected Coroutine"
    )


# Forgotten await warns; attribution points at caller (this test file)

# Each call lambda is defined in this module, so it is the frame that creates the
# coroutine — the warning must name this file, not conftest or the entity module.
FORGOTTEN_AWAIT_CASES = [
    pytest.param(make_light_entity, lambda e: e.turn_on(), id="light-turn_on"),
    pytest.param(make_bedroom_humidifier, lambda e: e.set_humidity(humidity=60), id="humidifier-set_humidity"),
    pytest.param(make_light_entity, lambda e: e.toggle(), id="light-toggle"),
]

AWAITED_CASES = [
    pytest.param(make_light_entity, lambda e: e.turn_on(brightness=200), id="light-turn_on"),
    pytest.param(make_bedroom_humidifier, lambda e: e.set_humidity(humidity=60), id="humidifier-set_humidity"),
    pytest.param(make_light_entity, lambda e: e.toggle(), id="light-toggle"),
]


@pytest.mark.parametrize(("factory", "call"), FORGOTTEN_AWAIT_CASES)
def test_entity_service_forgotten_await_warns(factory: EntityFactory, call: ServiceCall) -> None:
    """Dropping an un-awaited entity service call emits HassetteForgottenAwaitWarning attributed to the caller."""
    with entity_session(factory(make_api())) as entity:
        with pytest.warns(HassetteForgottenAwaitWarning) as record:
            _ = call(entity)
            del _
            gc.collect()
        assert len(record) >= 1
        warning_msg = str(record[0].message)
        assert __file__ in warning_msg or Path(__file__).stem in warning_msg, (
            f"Warning not attributed to caller: {warning_msg!r}"
        )


# Awaited call acts correctly (no warning, None returned)


@pytest.mark.parametrize(("factory", "call"), AWAITED_CASES)
async def test_entity_service_awaited_returns_none_no_warning(factory: EntityFactory, call: ServiceCall) -> None:
    """Awaiting an entity service call returns None and emits no warning."""
    with entity_session(factory(make_api())) as entity:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = await call(entity)
        assert result is None


# entity.sync.turn_on() still registers (via the domain facade)


def test_entity_sync_turn_on_registers() -> None:
    """entity.sync.turn_on() executes synchronously via the domain sync facade.

    LightEntity.sync is a LightEntitySyncFacade. Because `light` defines a
    `turn_on` service, the facade's generated turn_on routes through
    api.sync.call_service(...) — matching the async LightEntity.turn_on delegation.
    """
    api = make_api()
    with entity_session(make_light_entity(api)) as entity:
        # Patch api.sync to a mock so we don't need a real event loop here.
        mock_sync = MagicMock()
        api.sync = mock_sync

        entity.sync.turn_on(brightness=100)
        # The generated facade mirrors the async method: it forwards every light
        # param (the rest defaulting to None). Assert the meaningful dispatch args
        # without coupling to every optional param.
        mock_sync.call_service.assert_called_once()
        kwargs = mock_sync.call_service.call_args.kwargs
        assert kwargs["domain"] == entity.domain
        assert kwargs["service"] == "turn_on"
        assert kwargs["target"] == {"entity_id": entity.entity_id}
        assert kwargs["brightness"] == 100
