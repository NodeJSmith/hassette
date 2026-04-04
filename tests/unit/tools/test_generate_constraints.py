"""Unit tests for tools/generate_constraints.py."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from generate_constraints import generate_lines

# ---------------------------------------------------------------------------
# Fixtures: fake pyproject.toml content
# ---------------------------------------------------------------------------

SIMPLE_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "hassette"
    version = "0.24.0"
    dependencies = [
        "aiohttp>=3.11.18",
        "pydantic-settings>=2.10.0",
        "typing-extensions==4.15.*",
        "whenever==0.9.*",
    ]
    """
)

PYPROJECT_WITH_EXTRAS = textwrap.dedent(
    """\
    [project]
    name = "hassette"
    version = "0.24.0"
    dependencies = [
        "uvicorn[standard]>=0.34.0",
        "pydantic[email]>=2.0,<3",
        "aiohttp>=3.11",
    ]
    """
)


# ---------------------------------------------------------------------------
# Helper: run generate_lines with a fake pyproject path
# ---------------------------------------------------------------------------


def run_generate(tmp_path: Path, pyproject_content: str, hassette_version: str = "0.24.0") -> list[str]:
    """Call generate_lines() with a fake pyproject.toml and mocked importlib.metadata."""
    toml_file = tmp_path / "pyproject.toml"
    toml_file.write_text(pyproject_content)

    with patch("generate_constraints.importlib.metadata.version", return_value=hassette_version):
        return generate_lines(toml_file)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_output_starts_with_comment(tmp_path: Path) -> None:
    lines = run_generate(tmp_path, SIMPLE_PYPROJECT)
    assert lines[0].startswith("#"), "First line should be a comment"


def test_hassette_pin_is_exact(tmp_path: Path) -> None:
    lines = run_generate(tmp_path, SIMPLE_PYPROJECT, hassette_version="0.24.0")
    assert "hassette==0.24.0" in lines, f"Expected exact hassette pin, got: {lines}"


def test_hassette_pin_uses_metadata_version(tmp_path: Path) -> None:
    """The pin must come from importlib.metadata, not pyproject version field."""
    lines = run_generate(tmp_path, SIMPLE_PYPROJECT, hassette_version="9.9.9")
    assert "hassette==9.9.9" in lines


def test_hassette_pin_is_not_range(tmp_path: Path) -> None:
    """hassette should be pinned with ==, not >= or similar."""
    lines = run_generate(tmp_path, SIMPLE_PYPROJECT)
    hassette_line = next((line for line in lines if line.startswith("hassette")), None)
    assert hassette_line is not None, "No hassette line found"
    assert "==" in hassette_line
    assert ">=" not in hassette_line


def test_extras_are_stripped(tmp_path: Path) -> None:
    """uvicorn[standard]>=0.34.0 should become uvicorn>=0.34.0."""
    lines = run_generate(tmp_path, PYPROJECT_WITH_EXTRAS)
    assert any(line.startswith("uvicorn>=") for line in lines), f"Expected uvicorn>= line, got: {lines}"
    assert not any("[" in line for line in lines if not line.startswith("#")), (
        f"Extras brackets should be stripped from all non-comment lines, got: {lines}"
    )


def test_ranges_are_preserved(tmp_path: Path) -> None:
    """pydantic>=2.0,<3 should be preserved as-is (extras stripped, range kept)."""
    lines = run_generate(tmp_path, PYPROJECT_WITH_EXTRAS)
    assert any(line == "pydantic>=2.0,<3" for line in lines), f"Expected pydantic>=2.0,<3, got: {lines}"


def test_simple_ranges_preserved(tmp_path: Path) -> None:
    """aiohttp>=3.11.18 should appear verbatim."""
    lines = run_generate(tmp_path, SIMPLE_PYPROJECT)
    assert any(line.startswith("aiohttp>=") for line in lines), f"Expected aiohttp>= line, got: {lines}"


def test_star_specifiers_preserved(tmp_path: Path) -> None:
    """typing-extensions==4.15.* should be preserved."""
    lines = run_generate(tmp_path, SIMPLE_PYPROJECT)
    assert any("typing-extensions" in line for line in lines)
    assert any("4.15.*" in line for line in lines), f"Star specifier should be preserved, got: {lines}"


def test_all_deps_present(tmp_path: Path) -> None:
    """Every declared dependency should appear in the output (by normalized name)."""
    lines = run_generate(tmp_path, SIMPLE_PYPROJECT)
    non_comment = [line for line in lines if not line.startswith("#") and line.strip()]
    # hassette plus 4 deps
    assert len(non_comment) >= 4, f"Expected at least 4 dep lines, got: {non_comment}"


def test_no_duplicate_hassette(tmp_path: Path) -> None:
    """hassette should appear exactly once."""
    lines = run_generate(tmp_path, SIMPLE_PYPROJECT)
    hassette_lines = [line for line in lines if line.startswith("hassette")]
    assert len(hassette_lines) == 1, f"Expected exactly one hassette line, got: {hassette_lines}"


PYPROJECT_MULTI_EXTRAS = textwrap.dedent(
    """\
    [project]
    name = "hassette"
    version = "0.24.0"
    dependencies = [
        "httpx[http2,brotli]>=0.25",
        "tzdata>=2024.1; sys_platform == 'win32'",
    ]
    """
)


def test_multiple_comma_separated_extras_stripped(tmp_path: Path) -> None:
    """httpx[http2,brotli]>=0.25 → httpx>=0.25."""
    lines = run_generate(tmp_path, PYPROJECT_MULTI_EXTRAS)
    assert any(line == "httpx>=0.25" for line in lines), f"Expected httpx>=0.25, got: {lines}"
    assert not any("[" in line for line in lines if not line.startswith("#"))


def test_environment_markers_preserved(tmp_path: Path) -> None:
    """Deps with environment markers should pass through verbatim (marker preserved)."""
    lines = run_generate(tmp_path, PYPROJECT_MULTI_EXTRAS)
    assert any("tzdata>=2024.1; sys_platform" in line for line in lines), f"Expected marker preserved, got: {lines}"


def test_no_blank_dep_lines(tmp_path: Path) -> None:
    """Output should have no blank lines between deps (comment + deps only)."""
    lines = run_generate(tmp_path, SIMPLE_PYPROJECT)
    # All non-comment lines should be non-empty
    non_comment = [line for line in lines if not line.startswith("#")]
    assert all(line.strip() for line in non_comment), f"Unexpected blank lines: {lines}"


def test_pydantic_with_extras_and_range(tmp_path: Path) -> None:
    """pydantic[email]>=2.0,<3 → pydantic>=2.0,<3."""
    lines = run_generate(tmp_path, PYPROJECT_WITH_EXTRAS)
    assert any(line == "pydantic>=2.0,<3" for line in lines), f"Expected pydantic>=2.0,<3, got: {lines}"


def test_generate_lines_returns_list_of_strings(tmp_path: Path) -> None:
    lines = run_generate(tmp_path, SIMPLE_PYPROJECT)
    assert isinstance(lines, list)
    assert all(isinstance(line, str) for line in lines)


PYPROJECT_NO_DEPS = textwrap.dedent(
    """\
    [project]
    name = "hassette"
    version = "0.24.0"
    """
)


def test_missing_dependencies_key_exits(tmp_path: Path) -> None:
    """generate_lines() should exit cleanly when [project].dependencies is missing."""
    toml_file = tmp_path / "pyproject.toml"
    toml_file.write_text(PYPROJECT_NO_DEPS)

    with patch("generate_constraints.importlib.metadata.version", return_value="0.24.0"):
        with pytest.raises(SystemExit) as exc_info:
            generate_lines(toml_file)
        assert exc_info.value.code == 1
