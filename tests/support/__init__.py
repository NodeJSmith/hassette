"""Internal test infrastructure for hassette's own test suite.

Tier 2 helpers only — outside ``src/`` and absent from the wheel. Tests import
from specific submodules (e.g. ``from tests.support.factories import make_scheduled_job``)
rather than from this package root.
"""
