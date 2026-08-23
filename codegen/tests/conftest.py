"""Shared fixtures, constants, and assertion helpers for codegen tests.

``src`` is added to the import path via the ``pythonpath`` pytest option in
``codegen/pyproject.toml``, so ``hassette_codegen`` is importable without any
per-file path manipulation.
"""

import os
import py_compile
import tempfile
from pathlib import Path

from hassette_codegen.domain_data import ExtractedDomain
from hassette_codegen.generators.entities import generate_entity_wrapper

HA_CORE = Path(os.environ.get("HA_CORE_PATH", "~/source/core")).expanduser()
"""Local checkout of Home Assistant core, used by tests that extract data from HA source."""

HAS_HA_CORE = HA_CORE.exists()
"""Whether HA_CORE points at a real checkout — tests that need it skip when this is False."""


def assert_compiles(source: str) -> None:
    """Write source to a temp file and verify it compiles without errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_path = Path(tmpdir) / "generated.py"
        source_path.write_text(source)
        py_compile.compile(str(source_path), doraise=True)


def generate_wrapper_or_fail(domain: ExtractedDomain) -> str:
    """Generate an entity wrapper and assert the domain produces output."""
    output = generate_entity_wrapper(domain)
    assert output and output.strip()
    return output
