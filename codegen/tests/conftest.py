"""Shared fixtures and constants for codegen tests.

``src`` is added to the import path via the ``pythonpath`` pytest option in
``codegen/pyproject.toml``, so ``hassette_codegen`` is importable without any
per-file path manipulation.
"""

import os
from pathlib import Path

HA_CORE = Path(os.environ.get("HA_CORE_PATH", "~/source/core")).expanduser()
"""Local checkout of Home Assistant core, used by tests that extract data from HA source."""

HAS_HA_CORE = HA_CORE.exists()
"""Whether HA_CORE points at a real checkout — tests that need it skip when this is False."""
