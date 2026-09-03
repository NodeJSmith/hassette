# ruff: noqa: ARG001

import inspect
import logging
import typing
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import pytest

from hassette import STATE_REGISTRY
from hassette.models import states
from hassette.models.states import base
from hassette.models.states import sensor_shapes as sensor_shapes_module

if typing.TYPE_CHECKING:
    from hassette.testing import HassetteHarness

logger = logging.getLogger(__name__)

EXCLUDE_CLASSES = [
    base.BaseState,
    base.BoolBaseState,
    base.DateTimeBaseState,
    base.NumericBaseState,
    base.StringBaseState,
    base.TimeBaseState,
    # The four narrowed sensor shape classes deliberately never register: none re-declares
    # `domain`, so registering them would clobber SensorState process-wide. They are
    # filtered views over the `sensor` domain, not separate domains.
    sensor_shapes_module.NumericSensorState,
    sensor_shapes_module.EnumSensorState,
    sensor_shapes_module.TimestampSensorState,
    sensor_shapes_module.DateSensorState,
]

STATES_PATH = Path(states.__file__).parent


def _iter_included_models(all_models: dict[str, type[states.BaseState]]) -> Iterator[type[states.BaseState]]:
    """Yield the models under test, already cast and filtered.

    ``EXCLUDE_CLASSES`` doesn't work so well with importlib — the classes reimported via
    ``inspect.getmembers`` don't always compare equal by identity to the ones in the list, so the
    string check on ``"base.BaseState"`` catches what identity comparison misses.
    """
    for model_cls in all_models.values():
        model_cls = cast("type[states.BaseState]", model_cls)
        if model_cls in EXCLUDE_CLASSES or "base.BaseState" in str(model_cls):
            continue
        yield model_cls


@pytest.fixture(scope="module")
def all_models():
    """Import all state models to ensure they are registered."""
    all_classes = {}

    for state_file in STATES_PATH.glob("*.py"):
        if state_file.name.startswith("__"):
            continue
        module_name = f"hassette.models.states.{state_file.stem}"
        mod = import_module(module_name)
        classes = inspect.getmembers(mod, inspect.isclass)
        all_classes.update(
            {
                class_name: cls
                for class_name, cls in classes
                if issubclass(cls, states.BaseState) and cls not in EXCLUDE_CLASSES
            }
        )

    return all_classes


def test_all_domains_registered(
    hassette_with_state_proxy: "HassetteHarness", all_models: dict[str, type[states.BaseState]]
):
    """Test that all state models are registered in the state registry."""
    registered_domains = [x.domain for x in STATE_REGISTRY.registry]
    missing_domains = []

    for model_cls in _iter_included_models(all_models):
        if "domain" not in model_cls.model_fields:
            continue

        domain = model_cls.get_domain()

        if domain not in registered_domains:
            missing_domains.append(domain)

    missing_domains = sorted(missing_domains)

    if missing_domains:
        full_domain_list = sorted(registered_domains + missing_domains)
        logger.info("Missing domains: %s", missing_domains)
        logger.info("Full domain list: %s", full_domain_list)

    assert not missing_domains, f"Domains not registered: {missing_domains}"


def test_all_classes_in_registry(all_models: dict[str, type[states.BaseState]]):
    """Test that all state models are included in the state registry."""
    registered_classes = list(STATE_REGISTRY.registry.values())

    missing_classes = [
        model_cls.__name__ for model_cls in _iter_included_models(all_models) if model_cls not in registered_classes
    ]
    missing_classes = sorted(missing_classes)

    if missing_classes:
        logger.info("Missing classes in registry: %s", missing_classes)

    assert not missing_classes, f"Classes not registered: {missing_classes}"


def test_registry_can_convert_all_domains(
    all_models: dict[str, type[states.BaseState]],
):
    """Test that the registry can look up classes for all known domains."""
    for model_cls in _iter_included_models(all_models):
        domain = model_cls.get_domain()
        retrieved_class = STATE_REGISTRY.resolve(domain=domain)

        assert retrieved_class is model_cls, (
            f"Registry returned {retrieved_class} for domain '{domain}', expected {model_cls}"
        )


def test_fixture_data_parses_as_registered_state_class(hass_state_dicts: list[dict[str, Any]]):
    """Every entity in the JSONL fixture must parse as its registered state class.

    Catches bad captured data (e.g. manually-set test values) before it cascades
    into unrelated test failures.
    """
    failures: list[str] = []

    for state_dict in hass_state_dicts:
        entity_id = state_dict.get("entity_id", "")
        domain = entity_id.split(".")[0]

        state_cls = STATE_REGISTRY.resolve(domain=domain)
        if state_cls is None:
            continue

        try:
            converted = STATE_REGISTRY.try_convert_state(state_dict)
            if type(converted) is not state_cls:
                failures.append(f"{entity_id}: converted to {type(converted).__name__}, expected {state_cls.__name__}")
        except Exception as exc:
            failures.append(f"{entity_id}: {exc}")

    assert not failures, (
        f"{len(failures)} fixture entities failed to parse as their registered state class:\n" + "\n".join(failures)
    )
