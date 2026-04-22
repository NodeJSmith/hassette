"""Structural drift test: every Bus.on_* subscription method must have a simulate_* counterpart on AppTestHarness.

If this test fails, a new ``on_*`` method was added to ``Bus`` without a corresponding
``simulate_*`` method on ``AppTestHarness`` (via ``SimulationMixin``). Add the missing
``simulate_*`` method to ``hassette.test_utils.simulation.SimulationMixin``.
"""

from hassette.bus import Bus
from hassette.resources.base import Resource
from hassette.test_utils.app_harness import AppTestHarness


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
