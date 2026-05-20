---
task_id: "T02"
title: "Migrate named factory functions to shared factory"
status: "done"
depends_on: ["T01"]
implements: ["FR#6", "AC#1"]
---

## Summary
Replace all 15 `_make_*` factory function definitions and 7 import sites with calls to the shared `make_mock_hassette()` or `make_ws_hassette_stub()`. Each migration is mechanical: delete the local factory, add an import of `make_mock_hassette` from `hassette.test_utils`, and replace call sites. Some factories accept parameters (e.g., `strict_lifecycle`) that become config overrides.

## Prompt
Migrate all test files that define or import named factory functions matching the pattern `_make_hassette_stub|_make_mock_hassette|_make_hassette_mock|_make_ws_hassette_stub`. Each file needs:

1. Delete the local factory function definition (or remove the import of it)
2. Add `from hassette.test_utils import make_mock_hassette` (or `make_ws_hassette_stub` for WS files)
3. Replace all call sites with the shared factory, preserving any config overrides

**EXCLUDE `test_hassette_timeout_warning.py`** — it uses `object.__new__(Hassette)` and is explicitly out of scope.

### Files with factory DEFINITIONS to migrate (14 files, excluding the excluded one):

Unit tests — root:
- `tests/unit/test_framework_injection_points.py:37` — `_make_mock_hassette(name)`. Uses `Mock()` not `AsyncMock`. Accepts a `name` parameter. Check if `make_mock_hassette()` can replace this or if it needs `sealed=False` for the `name` attribute.
- `tests/unit/test_recording_api.py:40` — `_make_hassette_stub()`
- `tests/unit/test_task_bucket.py:26` — `_make_hassette_mock()`
- `tests/unit/test_resource_depends_on.py:17` — `_make_hassette_mock()`
- `tests/unit/test_recording_api_helpers.py:56` — `_make_hassette_stub()`
- `tests/unit/test_recording_sync_facade.py:49` — `_make_hassette_stub()`
- `tests/unit/test_config_log_level.py:46` — `_make_mock_hassette()`
- `tests/unit/test_state_manager.py:13` — `_make_hassette_mock()`

Unit tests — core:
- `tests/unit/core/test_ws_connection_state.py:19` — `_make_ws_hassette_stub()` → use `make_ws_hassette_stub()`
- `tests/unit/core/test_service_watcher_exhausted.py:29` — `_make_hassette_stub()`
- `tests/unit/core/test_bus_service_public_accessors.py:29` — `_make_hassette_mock()`
- `tests/unit/core/test_websocket_readiness_events.py:19` — `_make_ws_hassette_stub()` → use `make_ws_hassette_stub()`

Unit tests — resources:
- `tests/unit/resources/conftest.py:8` — `_make_hassette_stub()`. This is the shared conftest factory imported by 7 other files.

Integration tests:
- `tests/integration/test_event_stream_service.py:13` — `_make_mock_hassette(buffer_size)`

### Files with factory IMPORTS to migrate (7 files):

All import `_make_hassette_stub` from `tests/unit/resources/conftest.py`:
- `tests/unit/resources/test_lifecycle_transitions.py`
- `tests/unit/resources/test_start_children_and_wait.py`
- `tests/unit/resources/test_lifecycle_propagation.py`
- `tests/unit/resources/test_serve_wrapper_shutdown.py`
- `tests/unit/resources/test_service_lifecycle.py`
- `tests/unit/resources/test_lifecycle_side_effect_free.py`
- `tests/unit/resources/test_emit_readiness_event.py`

For these 7 files: replace `from .conftest import _make_hassette_stub` (or the absolute import variant) with `from hassette.test_utils import make_mock_hassette`, then update call sites.

### Migration pattern for each file:

1. Read the existing factory to understand what config fields it sets and what non-config attributes it wires
2. Determine which config fields differ from `make_test_config()` defaults — only those become overrides
3. Determine if any non-config attributes are set beyond what `make_mock_hassette()` provides — if yes, use `sealed=False` and wire extras after the call
4. Replace the factory call with `make_mock_hassette(**overrides)` or fixture that calls it

After migrating all files, run `grep -r '_make_hassette_stub\|_make_mock_hassette\|_make_hassette_mock\|_make_ws_hassette_stub' tests/` to verify zero results (AC#1 grep check, partial — inline fixtures are T04's scope).

Run `timeout 300 uv run pytest tests/unit/ -x -n 2` after each batch of ~5 files to catch regressions early.

## Focus
- `test_framework_injection_points.py` is unusual — its factory uses `Mock()` not `AsyncMock()`, and passes a `name` parameter. Read this file carefully to determine if `make_mock_hassette()` (which returns AsyncMock) is compatible or if it needs a different approach.
- `test_event_stream_service.py` accepts `buffer_size` parameter — this maps to a config override on the event stream buffer config.
- `test_config_log_level.py` tests config-related behavior — read it carefully to understand what config values it needs and whether real config changes the test semantics.
- The 7 import files in `tests/unit/resources/` use two different import styles: 5 use `from .conftest import _make_hassette_stub` (relative) and 2 use `from tests.unit.resources.conftest import _make_hassette_stub` (absolute). Both get replaced with `from hassette.test_utils import make_mock_hassette`.
- After removing the factory from `tests/unit/resources/conftest.py`, verify nothing else in that conftest needs updating (it may have other fixtures).

## Verify
- [ ] FR#6: `grep -r '_make_hassette_stub\|_make_mock_hassette\|_make_hassette_mock\|_make_ws_hassette_stub' tests/` returns zero results
- [ ] AC#1: The named factory grep pattern returns zero matches (the inline fixture portion of AC#1 is verified in T04)
