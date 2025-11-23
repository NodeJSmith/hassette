import inspect
from importlib import import_module
from pathlib import Path
from typing import cast, get_args

from hassette.models import states
from hassette.models.states import base

EXCLUDE_CLASSES = [
    base.BaseState,
    base.StringBaseState,
    base.NumericBaseState,
    base.BoolBaseState,
    base.IntBaseState,
    base.NumericBaseState,
    base.TimeBaseState,
    base.DateTimeBaseState,
]

STATES_PATH = Path(states.__file__).parent

print(f"States models are located in: {STATES_PATH}")


def import_all_models():
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


def test_all_domains_registered():
    """Test that all state models are registered in the states module."""
    all_models = import_all_models()
    registered_domains = list(base.DomainLiteral.__args__)
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

    # assert domain in registered_domains, f"Domain '{domain}' for model '{class_name}' is not registered."

    if missing_domains:
        full_domain_list = sorted(registered_domains + missing_domains)
        print(full_domain_list)

    assert not missing_domains

    print(f"All {len(all_models)} state models are properly registered.")


def test_all_classes_in_state_union():
    """Test that all state models are included in the StateUnion type."""
    all_models = import_all_models()
    state_union_types = get_args(states._StateUnion.__value__)
    missing_classes = []

    for model_cls in all_models.values():
        model_cls = cast("type[states.BaseState]", model_cls)

        # excluded classes doesn't work so well with importlib
        if model_cls in EXCLUDE_CLASSES or "base.BaseState" in str(model_cls):
            continue

        if model_cls not in state_union_types:
            missing_classes.append(model_cls.__name__)

    missing_classes = sorted(missing_classes)

    if missing_classes:
        print(f"Missing classes in StateUnion: {missing_classes}")

    assert not missing_classes

    print(f"All {len(all_models)} state models are included in StateUnion.")
