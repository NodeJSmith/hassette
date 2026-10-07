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


def run(tmp_path: Path, stub: str) -> list[tuple[int, str]]:
    states_dir = tmp_path / "states"
    states_dir.mkdir()
    (states_dir / "models.py").write_text(MODELS)
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
    states_dir = tmp_path / "states"
    states_dir.mkdir()
    (states_dir / "models.py").write_text('class FooState(BaseState):\n    domain: Literal["a", "b"]\n')
    with pytest.raises(SystemExit, match="unsupported domain annotation"):
        check_stub(tmp_path / "unused.pyi", states_dir=states_dir)
