"""Characterization tests for tools/check_state_manager_stub.py.

Pin what the guard reports: a catalog domain with no stub property, a stub property with no catalog
domain, and a stub property typed with the wrong state class. Explicit ``DomainStates`` properties
on the runtime ``StateManager`` (the narrowed sensor accessors) count as expected stub entries, and
properties not returning ``DomainStates`` are ignored on both sides.

The real stub is checked against the real catalog by the ``check-state-manager-stub`` hook in a fresh
process, not here: test modules register their own ``BaseState`` subclasses into the process-global
catalog at import time, so an in-process check would see test-only domains.
"""

from pathlib import Path

import pytest
from check_state_manager_stub import check_stub

CATALOG = {"light": "LightState", "switch": "SwitchState"}

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


def run(tmp_path: Path, stub: str, catalog: dict[str, str] = CATALOG, source: str = SOURCE) -> list[tuple[int, str]]:
    source_path = tmp_path / "state_manager.py"
    source_path.write_text(source)
    stub_path = tmp_path / "state_manager.pyi"
    stub_path.write_text(stub)
    return check_stub(stub_path, model_props=catalog, source_path=source_path)


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


def test_union_state_class_reported_as_mismatch(tmp_path: Path) -> None:
    stub = MATCHING_STUB.replace(
        "DomainStates[states.LightState]", "DomainStates[states.SwitchState | states.LightState]"
    )
    assert run(tmp_path, stub) == [
        (5, "property `light` typed states.SwitchState | states.LightState, expected LightState")
    ]


def test_source_property_conflicting_with_model_fails_loudly(tmp_path: Path) -> None:
    source = SOURCE + '\n    @property\n    def light(self) -> "DomainStates[states.SwitchState]": ...\n'
    with pytest.raises(SystemExit, match="property `light` typed SwitchState"):
        run(tmp_path, MATCHING_STUB, source=source)
