"""Validate the docs/screenshots.yml manifest structure.

The manifest is the single source of truth for screenshots. Adding a new
screenshot requires only a manifest entry change — no script modifications.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = REPO_ROOT / "docs" / "screenshots.yml"
PORT_PLACEHOLDER_BY_OUTPUT_PREFIX = {
    "docs/_static/web_ui_": "{port}",
    "docs/_static/ha-": "{ha_port}",
}


@pytest.fixture
def manifest() -> list[dict[str, object]]:
    with MANIFEST_PATH.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise TypeError(f"Expected manifest to be a YAML list, got {type(data).__name__}")
    return data


def test_all_entries_have_required_fields(manifest: list[dict[str, object]]):
    for i, entry in enumerate(manifest):
        assert "url" in entry, f"Entry {i} missing 'url' field"
        assert "output" in entry, f"Entry {i} missing 'output' field"
        assert "width" in entry, f"Entry {i} missing 'width' field"
        assert "height" in entry, f"Entry {i} missing 'height' field"


def test_output_paths_follow_convention(manifest: list[dict[str, object]]):
    for i, entry in enumerate(manifest):
        output = entry["output"]
        assert isinstance(output, str)
        assert output.startswith(tuple(PORT_PLACEHOLDER_BY_OUTPUT_PREFIX)), (
            f"Entry {i} output '{output}' must start with one of {list(PORT_PLACEHOLDER_BY_OUTPUT_PREFIX)}"
        )
        assert output.endswith(".png"), f"Entry {i} output '{output}' must end with '.png'"


def test_all_urls_contain_port_placeholder_for_their_output(manifest: list[dict[str, object]]):
    for i, entry in enumerate(manifest):
        url = entry["url"]
        output = entry["output"]
        assert isinstance(url, str)
        assert isinstance(output, str)
        placeholder = next(p for prefix, p in PORT_PLACEHOLDER_BY_OUTPUT_PREFIX.items() if output.startswith(prefix))
        assert placeholder in url, f"Entry {i} url '{url}' must contain the {placeholder} placeholder"


def test_selector_values_are_non_empty_strings(manifest: list[dict[str, object]]):
    for i, entry in enumerate(manifest):
        if "selector" in entry:
            selector = entry["selector"]
            assert isinstance(selector, str), f"Entry {i} selector must be a string, got {type(selector).__name__}"
            assert selector.strip(), f"Entry {i} selector must not be empty"


def test_no_duplicate_output_paths(manifest: list[dict[str, object]]):
    outputs = [entry["output"] for entry in manifest]
    assert len(outputs) == len(set(outputs)), f"Duplicate output paths: {[o for o in outputs if outputs.count(o) > 1]}"
