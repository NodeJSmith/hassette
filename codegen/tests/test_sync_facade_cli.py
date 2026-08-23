"""Guard tests for hassette_codegen.sync_facade.cli module-level constants."""

import tomllib

from hassette_codegen.sync_facade.cli import _REPO_ROOT, MAX_GENERATED_LINES


def test_max_generated_lines_matches_hsl102_config() -> None:
    """MAX_GENERATED_LINES is hand-synced with HSL102's max_lines — this catches drift."""
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    hsl102_max_lines = pyproject["tool"]["house-lint"]["rules"]["HSL102"]["max_lines"]

    assert MAX_GENERATED_LINES == hsl102_max_lines
