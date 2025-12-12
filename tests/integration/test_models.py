# ruff: noqa: ARG001

import inspect
import typing
from importlib import import_module
from pathlib import Path
from typing import cast

import pytest

from hassette.core.state_registry import STATE_REGISTRY
from hassette.models import states
from hassette.models.states import base

if typing.TYPE_CHECKING:
    from hassette import Hassette

EXCLUDE_CLASSES = [
    base.BaseState,
    base.BoolBaseState,
    base.DateTimeBaseState,
    base.NumericBaseState,
    base.StringBaseState,
    base.TimeBaseState,
]

STATES_PATH = Path(states.__file__).parent


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


def test_all_domains_registered(hassette_with_state_proxy: "Hassette", all_models: dict[str, type[states.BaseState]]):
    """Test that all state models are registered in the state registry."""

    registered_domains = [x.domain for x in STATE_REGISTRY._registry]
    missing_domains = []

    for model_cls in all_models.values():
        model_cls = cast("type[states.BaseState]", model_cls)
        if "domain" not in model_cls.model_fields:
            continue

        # excluded classes doesn't work so well with importlib
        if model_cls in EXCLUDE_CLASSES or "base.BaseState" in str(model_cls):
            continue

        domain = model_cls.get_domain()

        if domain not in registered_domains:
            missing_domains.append(domain)

    missing_domains = sorted(missing_domains)

    if missing_domains:
        full_domain_list = sorted(registered_domains + missing_domains)
        print(f"Missing domains: {missing_domains}")
        print(f"Full domain list: {full_domain_list}")

    assert not missing_domains, f"Domains not registered: {missing_domains}"

    print(f"All {len(all_models)} state models are properly registered in the registry.")


def test_all_classes_in_registry(all_models: dict[str, type[states.BaseState]]):
    """Test that all state models are included in the state registry."""

    registered_classes = [v for v in STATE_REGISTRY._registry.values()]
    missing_classes = []

    for model_cls in all_models.values():
        model_cls = cast("type[states.BaseState]", model_cls)

        # excluded classes doesn't work so well with importlib
        if model_cls in EXCLUDE_CLASSES or "base.BaseState" in str(model_cls):
            continue

        if model_cls not in registered_classes:
            missing_classes.append(model_cls.__name__)

    missing_classes = sorted(missing_classes)

    if missing_classes:
        print(f"Missing classes in registry: {missing_classes}")

    assert not missing_classes, f"Classes not registered: {missing_classes}"

    print(f"All {len(all_models)} state models are included in the registry.")


def test_registry_can_convert_all_domains(
    all_models: dict[str, type[states.BaseState]],
):
    """Test that the registry can look up classes for all known domains."""

    for model_cls in all_models.values():
        model_cls = cast("type[states.BaseState]", model_cls)

        # excluded classes doesn't work so well with importlib
        if model_cls in EXCLUDE_CLASSES or "base.BaseState" in str(model_cls):
            continue

        domain = model_cls.get_domain()
        retrieved_class = STATE_REGISTRY.resolve(domain=domain)

        assert retrieved_class is model_cls, (
            f"Registry returned {retrieved_class} for domain '{domain}', expected {model_cls}"
        )

    print(f"Registry can successfully look up all {len(all_models)} state classes by domain.")
