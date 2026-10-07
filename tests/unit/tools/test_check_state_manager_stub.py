"""Characterization tests for tools/check_state_manager_stub.py.

Pin what the guard reports: a model domain with no stub property, a stub property with no model
domain, and a stub property typed with the wrong state class. Explicit ``DomainStates`` properties
on the runtime ``StateManager`` (the narrowed sensor accessors) count as expected stub entries, and
properties not returning ``DomainStates`` are ignored on both sides.
"""

from pathlib import Path

import pytest
from check_state_manager_stub import STUB_PATH, check_stub

MODELS = """\
from typing import Literal

class LightState(BaseState):
    domain: Literal["light"]

class SwitchState(BaseState):
    domain: Literal["switch"]

class NumericSensorState(BaseState):
    pass
"""

SOURCE = """\
class StateManager(Resource):
    @property
    def config_log_level(self) -> LogLevel: ...

    @property
    def numeric_sensor(self) -> "DomainStates[states.NumericSensorState]": ...
"""

MATCHING_STUB = """\
class StateManager(Resource):
    @property
    def _state_proxy(self) -> StateReader: ...
    @property
    def light(self) -> DomainStates[states.LightState]: ...
    @property
    def switch(self) -> DomainStates[states.SwitchState]: ...
    @property
    def numeric_sensor(self) -> DomainStates[states.NumericSensorState]: ...
"""


def write_models(tmp_path: Path, models: str) -> Path:
    states_dir = tmp_path / "states"
    states_dir.mkdir()
    (states_dir / "models.py").write_text(models)
    return states_dir


def run(tmp_path: Path, stub: str, models: str = MODELS) -> list[tuple[int, str]]:
    states_dir = write_models(tmp_path, models)
    source = tmp_path / "state_manager.py"
    source.write_text(SOURCE)
    stub_path = tmp_path / "state_manager.pyi"
    stub_path.write_text(stub)
    return check_stub(stub_path, states_dir=states_dir, source_path=source)


def test_matching_stub_passes(tmp_path: Path) -> None:
    assert run(tmp_path, MATCHING_STUB) == []


def test_missing_model_domain_reported_at_class_line(tmp_path: Path) -> None:
    stub = MATCHING_STUB.replace("    @property\n    def switch(self) -> DomainStates[states.SwitchState]: ...\n", "")
    assert run(tmp_path, stub) == [(1, "missing property `switch` -> DomainStates[states.SwitchState]")]


def test_missing_source_property_reported(tmp_path: Path) -> None:
    stub = MATCHING_STUB.replace(
        "    @property\n    def numeric_sensor(self) -> DomainStates[states.NumericSensorState]: ...\n", ""
    )
    assert run(tmp_path, stub) == [(1, "missing property `numeric_sensor` -> DomainStates[states.NumericSensorState]")]


def test_extra_stub_property_reported(tmp_path: Path) -> None:
    stub = MATCHING_STUB + "    @property\n    def fan(self) -> DomainStates[states.FanState]: ...\n"
    assert run(tmp_path, stub) == [(11, "property `fan` (FanState) has no matching state model domain")]


def test_wrong_state_class_reported(tmp_path: Path) -> None:
    stub = MATCHING_STUB.replace("DomainStates[states.SwitchState]", "DomainStates[states.LightState]")
    assert run(tmp_path, stub) == [(7, "property `switch` typed LightState, expected SwitchState")]


def test_real_stub_matches_models() -> None:
    assert check_stub(STUB_PATH) == []


def test_multi_value_domain_literal_fails_loudly(tmp_path: Path) -> None:
    states_dir = write_models(tmp_path, 'class FooState(BaseState):\n    domain: Literal["a", "b"]\n')
    with pytest.raises(SystemExit, match="unsupported domain annotation"):
        check_stub(tmp_path / "unused.pyi", states_dir=states_dir)


def test_qualified_literal_domain_is_recognized(tmp_path: Path) -> None:
    models = MODELS + 'class FanState(BaseState):\n    domain: typing.Literal["fan"]\n'
    assert run(tmp_path, MATCHING_STUB, models) == [(1, "missing property `fan` -> DomainStates[states.FanState]")]


def test_union_state_class_reported_as_mismatch(tmp_path: Path) -> None:
    stub = MATCHING_STUB.replace(
        "DomainStates[states.LightState]", "DomainStates[states.SwitchState | states.LightState]"
    )
    assert run(tmp_path, stub) == [
        (5, "property `light` typed states.SwitchState | states.LightState, expected LightState")
    ]


def test_source_property_conflicting_with_model_fails_loudly(tmp_path: Path) -> None:
    states_dir = write_models(tmp_path, MODELS)
    source = tmp_path / "state_manager.py"
    source.write_text(SOURCE + '\n    @property\n    def light(self) -> "DomainStates[states.SwitchState]": ...\n')
    with pytest.raises(SystemExit, match="property `light` typed SwitchState"):
        check_stub(tmp_path / "unused.pyi", states_dir=states_dir, source_path=source)


def test_aliased_domain_annotation_fails_loudly(tmp_path: Path) -> None:
    states_dir = write_models(
        tmp_path, 'LampDomain = Literal["lamp"]\n\nclass LampState(BaseState):\n    domain: LampDomain\n'
    )
    with pytest.raises(SystemExit, match="unsupported domain annotation `LampDomain`"):
        check_stub(tmp_path / "unused.pyi", states_dir=states_dir)


def test_generic_domain_declaration_on_base_classes_is_ignored(tmp_path: Path) -> None:
    models = MODELS + "class BaseState:\n    domain: str\n\nclass StateKey:\n    domain: Hashable | None = None\n"
    assert run(tmp_path, MATCHING_STUB, models) == []
