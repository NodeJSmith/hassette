---
task_id: "T02"
title: "Create tests/support package with Tier 2 internals"
status: "planned"
depends_on: ["T01"]
implements: ["FR#5", "FR#6", "FR#9"]
---

## Summary

Create the `tests/support/` package with 14 modules containing all Tier 2 internal test helpers. These modules live outside `src/` and will not ship in the wheel. The package includes all web-layer factories, mock helpers, SQL utilities, uvicorn server helpers, and the Tier 2 pytest fixtures. The `tests/support/helpers.py` re-exports the two simulation event builders from `hassette.testing._simulation` for test convenience.

## Target Files

- create: `tests/support/__init__.py`
- create: `tests/support/harness.py`
- create: `tests/support/fixtures.py`
- create: `tests/support/factories.py`
- create: `tests/support/helpers.py`
- create: `tests/support/mock_hassette.py`
- create: `tests/support/web_mocks.py`
- create: `tests/support/web_manifest_helpers.py`
- create: `tests/support/web_job_helpers.py`
- create: `tests/support/web_response_helpers.py`
- create: `tests/support/web_telemetry_helpers.py`
- create: `tests/support/sql.py`
- create: `tests/support/uvicorn.py`
- create: `tests/support/resource_tracker.py`
- create: `tests/support/state_proxy_mocks.py`
- read: `src/hassette/test_utils/factories.py`
- read: `src/hassette/test_utils/helpers.py`
- read: `src/hassette/test_utils/mock_hassette.py`
- read: `src/hassette/test_utils/web_mocks.py`
- read: `src/hassette/test_utils/web_manifest_helpers.py`
- read: `src/hassette/test_utils/web_job_helpers.py`
- read: `src/hassette/test_utils/web_response_helpers.py`
- read: `src/hassette/test_utils/web_telemetry_helpers.py`
- read: `src/hassette/test_utils/sql_helpers.py`
- read: `src/hassette/test_utils/uvicorn_server.py`
- read: `src/hassette/test_utils/resource_tracker.py`
- read: `src/hassette/test_utils/state_proxy_mocks.py`
- read: `src/hassette/test_utils/fixtures.py`
- read: `src/hassette/test_utils/harness.py`
- read: `design/specs/108-testing-infra-split/design.md`

## Prompt

Create the `tests/support/` package by moving Tier 2 modules from `src/hassette/test_utils/` according to the design doc's `## Architecture → Module mapping (authoritative)` table.

### Module moves (whole-file, no splits)

These source modules move entirely to `tests/support/` as their destination name. Copy the file content, then update any internal imports from `hassette.test_utils.<module>` to the appropriate new path.

| Source → Destination |
|---|
| `factories.py` → `factories.py` |
| `mock_hassette.py` → `mock_hassette.py` |
| `web_mocks.py` → `web_mocks.py` |
| `web_manifest_helpers.py` → `web_manifest_helpers.py` |
| `web_job_helpers.py` → `web_job_helpers.py` |
| `web_response_helpers.py` → `web_response_helpers.py` |
| `web_telemetry_helpers.py` → `web_telemetry_helpers.py` |
| `sql_helpers.py` → `sql.py` |
| `uvicorn_server.py` → `uvicorn.py` |
| `resource_tracker.py` → `resource_tracker.py` |
| `state_proxy_mocks.py` → `state_proxy_mocks.py` |

### Modules requiring splits

1. **`harness.py` → `harness.py`** (only `preserve_config`): Extract only the `preserve_config` context manager from `src/hassette/test_utils/harness.py`. `HassetteHarness` and `wait_for` went to `hassette.testing._harness` in T01.

2. **`helpers.py` → `helpers.py`** (Tier 2 remainder): Copy everything from `src/hassette/test_utils/helpers.py` EXCEPT the 8 Tier 1 factory functions that went to `hassette.testing._factories.py` (T01) and the 2 event builder functions (`create_component_loaded_event`, `create_service_registered_event`) that were folded into `hassette.testing._simulation.py` (T01). This file also adds re-exports of those 2 event builders from `hassette.testing._simulation` for test convenience:
   ```python
   from hassette.testing._simulation import (
       create_component_loaded_event,
       create_service_registered_event,
   )
   ```

3. **`fixtures.py` → `fixtures.py`** (Tier 2 remainder): Copy all fixtures EXCEPT the 3 Tier 1 fixtures (`dummy_cache`, `event_capture`, `build_harness`) that went to `hassette.testing.fixtures` in T01. This includes: `hassette_harness`, `hassette_with_app_handler`, `hassette_with_bus`, `hassette_with_file_watcher`, `hassette_with_mock_api`, `hassette_with_scheduler`, `hassette_with_state_proxy`, `run_hassette_startup_tasks`, `sync_executor`.

### `__init__.py`

Create a minimal `tests/support/__init__.py`. It does not need re-exports — tests import from specific submodules (e.g., `from tests.support.factories import make_scheduled_job`).

### Import updates

When creating each file, update imports that reference modules within the old `hassette.test_utils` package:
- If the referenced module is now in `hassette.testing` (or `hassette.testing._*`), import from there.
- If the referenced module is now in `tests/support`, import from `tests.support.<module>`.
- `tests/support/` MAY import from `hassette.testing` — this is the correct dependency direction (FR#6).
- `hassette.testing/` must NEVER import from `tests.support/` — verify no such import exists in T01's output.

### fixtures.py import updates

The Tier 2 `fixtures.py` needs updated imports for the fixtures that depend on `HassetteHarness` and other Tier 1 symbols. For example:
- `from hassette.testing._harness import HassetteHarness` (or `from hassette.testing import HassetteHarness`)
- `from hassette.testing.config import make_test_config`

## Focus

- `tests/support/` is outside `src/` — it uses rootdir-based resolution for pytest (same as `tests.coverage_integrity`). No `pyproject.toml` changes needed for this directory.
- `factories.py` in `tests/support/` imports from `hassette.bus`, `hassette.scheduler`, etc. — these framework imports stay unchanged.
- `web_mocks.py` imports from `hassette.web` — unchanged.
- `mock_hassette.py` contains `make_mock_hassette` (demoted from Tier 1) and `make_ws_hassette_stub`. Both import from hassette framework modules — unchanged.
- `resource_tracker.py` registers pytest hooks (`pytest_runtest_setup`, `pytest_runtest_teardown`). It will be registered via `pytest_plugins` in `tests/conftest.py` (T03 handles that update).
- The `fixtures.py` Tier 2 split: the `hassette_harness` fixture creates a `HassetteHarness` — after T01, `HassetteHarness` lives in `hassette.testing._harness` and is also re-exported from `hassette.testing`. Import from either; prefer the public re-export.

## Verify

- [ ] FR#5: `python -c "from tests.support.fixtures import hassette_harness, hassette_with_bus"` succeeds (running from repo root, with `tests/` on the Python path)
- [ ] FR#6: `grep -r "from tests.support" src/hassette/testing/` returns zero matches
- [ ] FR#9: The file `tests/support/fixtures.py` contains the Tier 2 fixtures (`hassette_harness`, `hassette_with_bus`, etc.) and is importable
