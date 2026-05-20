---
task_id: "T05"
title: "Remove dead fixtures, update documentation, verify ACs"
status: "planned"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#8", "AC#3", "AC#4", "AC#5", "AC#6"]
---

## Summary
Remove the 5 dead fixtures from `tests/conftest.py`, update `tests/TESTING.md` to document `make_mock_hassette()` as the standard pattern, and run the full verification suite to confirm all acceptance criteria pass. This is the final cleanup task.

## Prompt
### Remove dead fixtures

Delete these 5 session-scoped fixtures from `tests/conftest.py` (they have zero consumers):
- `test_data_path` (line 175, decorator at 174)
- `test_config_path` (line 184, decorator at 183)
- `test_events_path` (line 190, decorator at 189)
- `test_api_responses_path` (line 196, decorator at 195)
- `test_apps_path` (line 202, decorator at 201)

Keep the module-level constants (`TEST_DATA_PATH`, `TEST_CONFIG_PATH`, `TEST_EVENTS_PATH`, `TEST_API_RESPONSES_PATH`, `TEST_APPS_PATH`) — they're used by `TestConfig` and other fixtures.

### Update `tests/TESTING.md`

In the "Choosing a Mock Strategy" table (around line 29), add a row for `make_mock_hassette()`:

| Scenario | Tool | Why |
|---|---|---|
| Unit tests needing a hassette mock with real config | `make_mock_hassette()` | Real Pydantic validation, sealed by default, no drift |

In the "Fixture Naming Conventions" section (around line 62), update the `mock_hassette` entry:
- `mock_hassette` — lightweight hassette mock created via `make_mock_hassette()` from `hassette.test_utils`
- `db_hassette` — database-backed hassette mock with `premigrated_db_path`, also via `make_mock_hassette()`

In the "Available Factories" section (around line 142), add:

### `make_mock_hassette(**config_overrides)` — `test_utils/mock_hassette.py`

Builds a sealed AsyncMock hassette with real Pydantic-validated config via `make_test_config()`. Accepts any HassetteConfig field as a keyword override. Non-config attributes (ready_event, shutdown_event, service stubs, etc.) are wired automatically.

### `make_ws_hassette_stub(**kwargs)` — `test_utils/mock_hassette.py`

Thin wrapper around `make_mock_hassette()` with WebSocket config fields pre-set to sub-millisecond values for retry/timeout testing.

### Full verification

Run the complete acceptance criteria verification:

1. **AC#1** — `grep -r '_make_hassette_stub\|_make_mock_hassette\|_make_hassette_mock\|_make_ws_hassette_stub' tests/` returns zero results. Also verify no inline `mock_hassette` fixture outside `test_utils/` or `e2e/` manually sets `.config.` on a MagicMock.
2. **AC#2** — `grep -rn 'def initialized_db' tests/` returns exactly one result.
3. **AC#3** — Structural: `make_mock_hassette()` delegates to `make_test_config()` which delegates to `HassetteConfig` model defaults. No test file hardcodes config field values outside of intentional overrides.
4. **AC#4** — `timeout 300 uv run nox -s dev -- -n 2` passes with zero failures.
5. **AC#5** — `git diff --stat` against the branch point shows a net reduction in test code lines.
6. **AC#6** — The 5 dead fixtures are no longer in `tests/conftest.py`.

If any AC fails, investigate and fix before marking complete.

## Focus
- The dead fixture line numbers may shift if T03/T04 modified `tests/conftest.py` — search by function name, not line number.
- `tests/TESTING.md` has a clear structure with headed sections and tables — match the existing formatting style.
- For AC#4, run `timeout 300 uv run nox -s dev -- -n 2` (not bare pytest) — this is the CI-equivalent command per CLAUDE.md.
- For AC#5, use `git diff --stat $(git merge-base HEAD main)` to measure against the branch point.
- The docs site (`docs/`) may also reference test_utils — check `docs/pages/testing/` for any page that should mention `make_mock_hassette`. The design doc's Documentation Updates section mentions adding it to the `test_utils` public API docs.

## Verify
- [ ] FR#8: `grep -n 'def test_data_path\|def test_config_path\|def test_events_path\|def test_api_responses_path\|def test_apps_path' tests/conftest.py` returns zero results
- [ ] AC#3: `make_mock_hassette()` uses `make_test_config()` which uses real `HassetteConfig` model — fields with defaults require no test file changes
- [ ] AC#4: `uv run nox -s dev -- -n 2` exits with status 0
- [ ] AC#5: `git diff --stat` shows net negative line count in test files
- [ ] AC#6: The 5 dead root-level fixtures are removed from `tests/conftest.py`
