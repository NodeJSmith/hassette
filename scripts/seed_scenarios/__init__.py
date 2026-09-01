"""Deterministic scenario generators for the hassette telemetry seed database.

One module per named scenario, each exposing a single ``scenario_*`` function that takes a
``SeedContext`` and populates it. ``SCENARIOS`` below is the registry the CLI
(``scripts/seed_db.py``) drives; shared building blocks live in ``base``. Adding a scenario
means adding a module here and registering its function in ``SCENARIOS`` -- the CLI's
``--scenario`` choices are derived from that dict, so nothing else needs touching.

Scenario functions call into the shared seed helpers (``seed_listener``, ``seed_job``,
``seed_app_blocking_event``, etc.) repeatedly with the same call shape, differing only in
literal ``app_key``/``class_name``/offset arguments. PMD's clone detector treats these calls
as duplicate fragments, so a scenario module whose per-app blocks trip it carries a
``dup-ignore-file`` marker (see ``tools/check_duplicate_code.py``) rather than being forced
into a data-driven loop, which would obscure the per-app literal values scenario authors need
to read and edit directly.
"""

from collections.abc import Callable

from seed_scenarios.adversarial import scenario_adversarial
from seed_scenarios.base import SeedContext, SeedIntegrityError
from seed_scenarios.degraded import scenario_degraded
from seed_scenarios.empty import scenario_empty
from seed_scenarios.error import scenario_error
from seed_scenarios.healthy import scenario_healthy
from seed_scenarios.large_volume import scenario_large_volume
from seed_scenarios.lifecycle import scenario_lifecycle

SCENARIOS: dict[str, Callable[[SeedContext], None]] = {
    "healthy": scenario_healthy,
    "empty": scenario_empty,
    "degraded": scenario_degraded,
    "error": scenario_error,
    "large-volume": scenario_large_volume,
    "lifecycle": scenario_lifecycle,
    "adversarial": scenario_adversarial,
}

__all__ = ["SCENARIOS", "SeedContext", "SeedIntegrityError"]
