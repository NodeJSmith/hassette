import inspect
from importlib import import_module
from pathlib import Path
from typing import cast, get_args

import pytest

from hassette.models import states
from hassette.models.states import base
from hassette.states import States

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


def test_all_domains_registered(all_models: dict[str, type[states.BaseState]]):
    """Test that all state models are registered in the states module."""
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


def test_all_classes_in_state_union(all_models: dict[str, type[states.BaseState]]):
    """Test that all state models are included in the StateUnion type."""
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


def test_states_class_has_property_for_each_domain(all_models: dict[str, type[states.BaseState]]):
    """Test that the States class has a property for each domain."""
    '''
    @property
    def input_datetime(self) -> DomainStates[states.InputDatetimeState]:
        """Access all input datetime entity states with full typing."""
        return self.get_states(states.InputDatetimeState)
    '''

    template = '''
    @property
    def {property_name}(self) -> DomainStates[states.{model_cls_name}]:
        """Access all {domain} entity states with full typing."""
        return self.get_states(states.{model_cls_name})
'''

    found_properties: dict[str, type[states.BaseState]] = {}
    missing_properties: dict[str, type[states.BaseState]] = {}

    for model_cls in all_models.values():
        model_cls = cast("type[states.BaseState]", model_cls)

        # excluded classes doesn't work so well with importlib
        if model_cls in EXCLUDE_CLASSES or "base.BaseState" in str(model_cls):
            continue

        domain = model_cls.get_domain()
        property_name = domain  # Singular form
        # if not hasattr(states_instance, property_name):
        #     missing_properties.append(property_name)
        if not hasattr(States, property_name):
            missing_properties[property_name] = model_cls
        else:
            found_properties[property_name] = model_cls

    # missing_properties = dict(sorted(missing_properties.items()))
    all_properties = {**found_properties, **missing_properties}
    all_properties = dict(sorted(all_properties.items()))

    if all_properties:
        # print(f"Missing properties in States class: {missing_properties}")
        for property_name, model_cls in all_properties.items():
            domain = model_cls.get_domain()
            model_cls_name = model_cls.__name__
            print(
                template.format(
                    property_name=property_name,
                    model_cls_name=model_cls_name,
                    domain=domain,
                )
            )

    assert not missing_properties

    print(f"States class has properties for all {len(all_models)} domains.")
