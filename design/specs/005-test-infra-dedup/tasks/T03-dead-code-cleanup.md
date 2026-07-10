---
task_id: "T03"
title: "Delete dead code and fix misplaced fixtures"
status: "planned"
depends_on: ["T01"]
implements: ["FR#8", "FR#9", "FR#10", "FR#11", "FR#14", "FR#20", "AC#4", "AC#5", "AC#6", "AC#7"]
---

## Summary
Remove dead exports, dead test data files, and dead asyncio markers. Move 3 misplaced fixtures to their correct directory. Add a docstring to the intentional `hassette_with_bus` override. Depends on T01 because both modify the `__init__.py` and `_internal/__init__.py` export chain (T01 adds factory exports, this task removes dead exports).

## Target Files
- modify: `src/hassette/test_utils/helpers.py`
- modify: `src/hassette/test_utils/web_helpers.py`
- modify: `src/hassette/test_utils/fixtures.py`
- modify: `src/hassette/test_utils/__init__.py`
- modify: `src/hassette/test_utils/_internal/__init__.py`
- modify: `tests/integration/conftest.py`
- modify: `tests/integration/web_api/conftest.py`
- modify: `tests/unit/bus/conftest.py`
- modify: `tests/unit/core/test_logging_service.py`
- modify: `tests/TESTING.md`
- delete: `tests/data/events/device_tracker_event.json`

## Prompt
### FR#8 — Dead test app files
Already deleted on this branch (committed in `a51b37b0`). Verify AC#4 holds.

### FR#9 — Dead exports
1. Delete `emit_service_event()` from `src/hassette/test_utils/helpers.py` (line 408-410). Remove its re-export from `_internal/__init__.py` and `__init__.py`.
2. Delete `make_listener_metric()` from `src/hassette/test_utils/web_helpers.py` (line 146). Remove its re-export from `_internal/__init__.py` and `__init__.py`.
3. Delete `setup_registry()` from `src/hassette/test_utils/web_helpers.py` (line 194). Remove its re-export from `_internal/__init__.py` and `__init__.py`.
4. Delete `hassette_with_nothing` fixture from `src/hassette/test_utils/fixtures.py` (lines 54-60). Note: this fixture is NOT in `__all__` or re-exported via `_internal/__init__.py` — it's registered only via `pytest_plugins = ["hassette.test_utils.fixtures"]` in `tests/conftest.py:47`, so deleting the function from `fixtures.py` is sufficient.
5. Remove `"hassette_with_nothing"` string from the `_HARNESS_FIXTURES` frozenset in `tests/integration/conftest.py:46`.
6. Remove the `hassette_with_nothing` reference from `tests/TESTING.md:119-123` and update the harness fixture count from "8 module-scoped" to "7 module-scoped".

Note: `mock_transport_builder` was already removed by the clean code sweep (commit `05912d8d`).

### FR#10 — Dead asyncio markers
Remove the 13 bare `@pytest.mark.asyncio` markers from `tests/unit/core/test_logging_service.py`. These are no-ops because `asyncio_mode = "auto"` in `pyproject.toml`. Do NOT remove `@pytest.mark.asyncio(loop_scope="function")` markers in other files — those override the default session scope and are functionally significant.

### FR#11 — Misplaced fixtures
Move `app`, `client`, and `runtime_query_service` fixtures from `tests/integration/conftest.py` (lines 72-89) to `tests/integration/web_api/conftest.py`. Their sole dependency `mock_hassette` is defined only in `web_api/conftest.py`. No integration test outside `web_api/` uses these fixtures.

Note: `tests/integration/web_api/test_ws_endpoint.py` already defines local overrides of `app` (line 66) and `client` (line 77) — these will continue to work.

### FR#14 — hassette_with_bus docstring
Add a docstring to the `hassette_with_bus` override in `tests/unit/bus/conftest.py` following the pattern of `tests/integration/telemetry/conftest.py::db_hassette`. The docstring should explain the intentional scope/type change.

### FR#20 — Dead test data
Delete `tests/data/events/device_tracker_event.json` (wrong format, zero references).

## Focus
- When deleting from `__init__.py`, check whether the symbol is in `__all__` (Tier 1) or just a re-export (Tier 2). `emit_service_event`, `make_listener_metric`, and `setup_registry` are Tier 2 re-exports — remove them from `_internal/__init__.py` and `__init__.py`. `hassette_with_nothing` is NOT in either file — it's registered via `pytest_plugins` in `tests/conftest.py`.
- The `_HARNESS_FIXTURES` frozenset at `tests/integration/conftest.py:46` is used by `cleanup_harness` autouse fixture. After removing `"hassette_with_nothing"`, verify the frozenset still matches the actual fixture list.
- For the fixture move (FR#11), copy the fixture functions including their `@pytest.fixture` decorators and type annotations.

## Verify
- [ ] FR#8: `ls tests/data/apps/` shows exactly 6 `.py` files (already done — verify)
- [ ] FR#9: Dead exports removed from helpers.py, web_helpers.py, fixtures.py, and all re-export chains
- [ ] FR#10: `grep -rn "pytest.mark.asyncio" tests/unit/core/test_logging_service.py` returns zero results
- [ ] FR#11: `grep -rn "def app\b\|def client\b\|def runtime_query_service\b" tests/integration/conftest.py` returns zero results
- [ ] FR#14: `hassette_with_bus` in `tests/unit/bus/conftest.py` has an explanatory docstring
- [ ] FR#20: `tests/data/events/device_tracker_event.json` does not exist
- [ ] AC#4: `ls tests/data/apps/` shows exactly the 6 expected files
- [ ] AC#5: `grep -rn "emit_service_event\|make_listener_metric\|setup_registry\|hassette_with_nothing" src/hassette/test_utils/` returns zero results
- [ ] AC#6: `grep -rn "pytest.mark.asyncio" tests/unit/core/test_logging_service.py` returns zero results
- [ ] AC#7: `grep -rn "def app\b\|def client\b\|def runtime_query_service\b" tests/integration/conftest.py` returns zero results — all three moved to `web_api/conftest.py`
