"""The ``empty`` scenario: bare schema, no rows."""

from seed_scenarios.base import SeedContext


def scenario_empty(_ctx: SeedContext) -> None:
    """Trivial baseline: bare schema, zero rows in every table. Uses no app keys."""
