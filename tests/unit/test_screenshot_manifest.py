"""Validate the docs/screenshots.yml manifest structure.

This test verifies AC#6: the manifest is the single source of truth for
screenshots. Adding a new screenshot requires only a manifest entry change —
no script modifications.
"""

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MANIFEST_PATH = _REPO_ROOT / "docs" / "screenshots.yml"

EXPECTED_ENTRY_COUNT = 16


def _load_manifest() -> list[dict]:
    with _MANIFEST_PATH.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise TypeError(f"Expected manifest to be a YAML list, got {type(data).__name__}")
    return data


def test_manifest_parses_as_list():
    with _MANIFEST_PATH.open() as f:
        data = yaml.safe_load(f)
    assert isinstance(data, list), f"Expected YAML list, got {type(data).__name__}"


def test_all_entries_have_required_fields():
    entries = _load_manifest()
    for i, entry in enumerate(entries):
        assert "url" in entry, f"Entry {i} missing 'url' field"
        assert "output" in entry, f"Entry {i} missing 'output' field"
        assert "width" in entry, f"Entry {i} missing 'width' field"


def test_output_paths_follow_convention():
    entries = _load_manifest()
    for i, entry in enumerate(entries):
        output = entry["output"]
        assert output.startswith("docs/_static/web_ui_"), (
            f"Entry {i} output '{output}' must start with 'docs/_static/web_ui_'"
        )
        assert output.endswith(".png"), f"Entry {i} output '{output}' must end with '.png'"


def test_all_urls_contain_port_placeholder():
    entries = _load_manifest()
    for i, entry in enumerate(entries):
        url = entry["url"]
        assert "{port}" in url, f"Entry {i} url '{url}' must contain the {{port}} placeholder"


def test_selector_values_are_non_empty_strings():
    entries = _load_manifest()
    for i, entry in enumerate(entries):
        if "selector" in entry:
            selector = entry["selector"]
            assert isinstance(selector, str), f"Entry {i} selector must be a string, got {type(selector).__name__}"
            assert selector.strip(), f"Entry {i} selector must not be empty"


def test_entry_count_matches_expected():
    entries = _load_manifest()
    assert len(entries) == EXPECTED_ENTRY_COUNT, (
        f"Expected {EXPECTED_ENTRY_COUNT} manifest entries, found {len(entries)}. "
        "Update EXPECTED_ENTRY_COUNT if you intentionally added or removed a screenshot."
    )


def test_no_duplicate_output_paths():
    entries = _load_manifest()
    outputs = [entry["output"] for entry in entries]
    seen = set()
    duplicates = []
    for output in outputs:
        if output in seen:
            duplicates.append(output)
        seen.add(output)
    assert not duplicates, f"Duplicate output paths found: {duplicates}"
