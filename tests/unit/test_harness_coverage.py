"""Structural drift test: every Bus.on_* subscription method must have a simulate_* counterpart on AppTestHarness.

If this test fails, a new ``on_*`` method was added to ``Bus`` without a corresponding
``simulate_*`` method on ``AppTestHarness`` (via ``SimulationMixin``). Add the missing
``simulate_*`` method to ``hassette.test_utils.simulation.SimulationMixin``.
"""

import pytest

from hassette.bus import Bus
from hassette.resources.base import Resource
from hassette.test_utils.app_harness import AppTestHarness
from hassette.test_utils.simulation import SimulationMixin
from hassette.types import ResourceStatus

SIMULATION_TIMEOUT_CASES: list[tuple[str, tuple, dict]] = [
    ("simulate_state_change", ("sensor.test",), {"old_value": "off", "new_value": "on"}),
    (
        "simulate_attribute_change",
        ("sensor.test", "temperature"),
        {"old_value": 20, "new_value": 21},
    ),
    ("simulate_call_service", ("light", "turn_on"), {}),
    ("simulate_component_loaded", ("mqtt",), {}),
    ("simulate_service_registered", ("light", "turn_on"), {}),
    ("simulate_hassette_service_status", ("WebSocketService", ResourceStatus.RUNNING), {}),
    ("simulate_websocket_connected", (), {}),
    ("simulate_websocket_disconnected", (), {}),
    ("simulate_app_state_changed", (ResourceStatus.RUNNING,), {}),
    ("drain_task_bucket", (), {}),
]


def test_all_bus_subscriptions_have_simulate_counterparts():
    """Every Bus.on_* subscription method must have a matching simulate_* on AppTestHarness."""
    # Get on_* methods defined directly on Resource (lifecycle hooks, not subscriptions)
    resource_methods = {name for name in Resource.__dict__ if name.startswith("on_")}

    # Methods on Bus that are not event subscriptions (no simulate counterpart needed)
    non_subscription_methods = {"on_error"}

    # Get on_* methods defined directly on Bus, excluding those inherited from Resource
    # and non-subscription methods like on_error (handler registration, not event subscription)
    bus_methods = {
        name.removeprefix("on_")
        for name in Bus.__dict__
        if name.startswith("on_") and name not in resource_methods and name not in non_subscription_methods
    }

    # Get simulate_* methods available on AppTestHarness (including inherited from SimulationMixin)
    harness_methods = {name.removeprefix("simulate_") for name in dir(AppTestHarness) if name.startswith("simulate_")}

    missing = bus_methods - harness_methods
    assert not missing, (
        f"Bus subscription methods without simulate counterparts on AppTestHarness: "
        f"{sorted('on_' + m for m in missing)}. "
        f"Add simulate_* methods to SimulationMixin for each."
    )


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs"),
    SIMULATION_TIMEOUT_CASES,
    ids=[case[0] for case in SIMULATION_TIMEOUT_CASES],
)
async def test_simulation_entry_points_validate_timeout_before_harness_access(
    method_name: str,
    args: tuple,
    kwargs: dict,
) -> None:
    """Invalid deadlines fail before a simulation requires or dispatches through a harness."""
    simulation = SimulationMixin()

    with pytest.raises(ValueError, match="timeout must be finite and non-negative"):
        await getattr(simulation, method_name)(*args, **kwargs, timeout=-1.0)
