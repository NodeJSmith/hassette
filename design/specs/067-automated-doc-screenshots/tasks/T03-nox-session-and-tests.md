---
task_id: "T03"
title: "Add nox session and manifest validation test"
status: "planned"
depends_on: ["T02"]
implements: ["AC#6"]
---

## Summary
Add a `screenshots` nox session for convenience and a unit test that validates the YAML manifest structure. The nox session matches the project's existing pattern for dev tooling. The test validates that all manifest entries have required fields, that output paths point to `docs/_static/`, that selectors reference valid `data-testid` patterns, and that adding a new entry is all that's needed for a new screenshot (no script changes required).

## Prompt
Two changes:

### 1. `noxfile.py` — add screenshots session

Add a `screenshots` nox session after the existing `system` session:

```python
@nox.session(python=False)
def screenshots(session):
    session.run("uv", "run", "python", "scripts/capture_screenshots.py", external=True)
```

Use `python=False` — the script manages its own Python environment via `uv run`.

### 2. `tests/unit/test_screenshot_manifest.py` — manifest validation test

Write a unit test that loads `docs/screenshots.yml` and validates:
- The file parses as a YAML list
- Each entry has `url`, `output`, and `width` fields
- Each `output` path starts with `docs/_static/web_ui_` and ends with `.png`
- Each `url` contains the `{port}` placeholder
- Entries with a `selector` field have a non-empty string value
- The total entry count matches the expected number of screenshots (currently 16)
- No duplicate `output` paths exist

Use `yaml.safe_load()` to parse. The test file path is `tests/unit/test_screenshot_manifest.py`. Use `Path(__file__).resolve()` to find the repo root and locate `docs/screenshots.yml` relative to it.

This test verifies AC#6 — that the manifest is the single source of truth and new screenshots require only a manifest entry change.

## Focus
- Check existing test files in `tests/unit/` to match naming conventions and import patterns.
- The manifest uses `{port}` as a literal string placeholder — the test should verify this string exists in URLs, not try to resolve it.
- PyYAML is available in the test environment (transitive dependency of shot-scraper, also used by other test infrastructure).
- The nox session goes near the other utility sessions (after `system` or `system_with_coverage`). Check `noxfile.py` for the exact insertion point.

## Verify
- [ ] AC#6: The test validates that adding a new screenshot entry (with url, output, width) to the manifest is structurally valid without any script changes — the manifest schema is the contract, not the script logic
