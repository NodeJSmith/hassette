---
task_id: "T04"
title: "Migrate inline mock_hassette fixtures to shared factory"
status: "planned"
depends_on: ["T01", "T03"]
implements: ["FR#6", "AC#1"]
---

## Summary
Migrate the remaining test files that define inline `mock_hassette` fixtures with manually-set config attributes. These aren't caught by the named factory grep (AC#1's `_make_*` pattern) but represent the same drift problem. Each migration replaces manual `.config.X = Y` attribute assignment with a `make_mock_hassette(**overrides)` call.

## Prompt
Migrate all files with inline `mock_hassette` (or similar) fixtures that manually set `.config.` attributes on a MagicMock. For each file:

1. Read the fixture to catalog every `.config.` attribute it sets
2. Compare each value against `make_test_config()` defaults and Pydantic model defaults
3. Only values that differ from defaults become explicit `**config_overrides`
4. Non-config attributes beyond what `make_mock_hassette()` provides → use `sealed=False` and wire after
5. Replace the fixture body with `make_mock_hassette()` call + any extras

### Unit test files to migrate:

- **`tests/unit/core/test_app_handler_readiness.py:17`** — `mock_hassette()` with 10+ config fields (lifecycle timeouts, dev_mode, app manifests, logging) plus `send_event`, `shutdown_event`, `_bus_service`. Needs `sealed=False` for extras like `send_event` and `_bus_service.router`.
- **`tests/unit/core/test_app_lifecycle_service.py:15`** — `mock_hassette()` with 8+ config fields plus `send_event`, `wait_for_ready`, `command_executor`. Needs `sealed=False`.
- **`tests/unit/core/test_database_service.py:15`** — `mock_hassette(tmp_path)` with 12+ DB config fields. Most match defaults — verify each.
- **`tests/unit/core/test_log_records.py:734`** — `mock_hassette_for_db(tmp_path)` with 12+ DB config fields. Same pattern as `test_database_service.py`.
- **`tests/unit/core/test_runtime_query_service.py:16`** — `mock_hassette()` with 4+ config fields plus service wiring (state_proxy, websocket_service, etc.). Needs `sealed=False` for the service property assignments.
- **`tests/unit/core/test_web_ui_watcher.py:49`** — `mock_hassette()` with 1 config field (`web_api.ui_hot_reload`) plus `runtime_query_service`. Minimal — borderline but still benefits from real config.

### Integration test files to migrate (non-web, non-initialized_db):

These have `mock_hassette` fixtures with DB config. Exclude files that use `create_hassette_stub()` — those are web tests out of scope.

- **`tests/integration/test_database_service.py:15`** — `mock_hassette(premigrated_db_path)` with 12+ DB fields, plus `mock_hassette_fresh(tmp_path)` at line 39
- **`tests/integration/test_telemetry_query_service.py:30`** — `mock_hassette(premigrated_db_path)` with DB config
- **`tests/integration/test_session_manager.py:47`** — `mock_hassette(premigrated_db_path)` with DB config
- **`tests/integration/test_framework_telemetry.py:39`** — `mock_hassette_with_db(premigrated_db_path)` (async fixture)
- **`tests/integration/test_telemetry_execution_id.py:26`** — `mock_hassette(premigrated_db_path)` with DB config
- **`tests/integration/test_telemetry_timed_out.py:25`** — `mock_hassette(premigrated_db_path)` with DB config
- **`tests/integration/test_global_jobs_and_service_info.py:39`** — `mock_hassette_db()` with 10+ DB config fields. Note: the same file's `mock_hassette_scheduler()` at line 317 uses `create_hassette_stub()` and is out of scope — only `mock_hassette_db` is migrated.
- **`tests/integration/test_web_ui_watcher.py`** — `mock_hassette()` with 1 config field (`web_api.ui_hot_reload=True`) plus `runtime_query_service`. Integration counterpart to the unit test version.

For integration files that take `premigrated_db_path`, use `make_mock_hassette(data_dir=premigrated_db_path.parent)` and let real config provide defaults for the DB fields.

After all migrations, verify the complete AC#1 check: no inline `mock_hassette` fixture outside `test_utils/` or `e2e/` manually sets `.config.` attributes on a MagicMock.

Run `timeout 300 uv run pytest tests/unit/ tests/integration/ -x -n 2` after each batch.

## Focus
- The unit test files in `core/` wire extra non-config attributes like `send_event`, `command_executor`, `_bus_service.router`, `state_proxy`, etc. These are NOT covered by `make_mock_hassette()`'s default wiring. Use `sealed=False` and set them after the factory call.
- `test_log_records.py` has the fixture at line 734 (deep in the file, not at the top) — named `mock_hassette_for_db`, not `mock_hassette`.
- `test_framework_telemetry.py` uses an async fixture (`async def mock_hassette_with_db`) — the `make_mock_hassette()` call itself is sync, so the async wrapper may still be needed if it does async setup.
- Integration DB fixtures that take `premigrated_db_path` currently set many config fields that match defaults (`retention_days=7`, `write_queue_max=2000`, `migration_timeout_seconds=120`, etc.). The factory call with `data_dir=premigrated_db_path.parent` should produce identical config — verify by running the tests.
- Web test files (`test_api_app_config.py`, `test_api_app_source.py`, `test_web_api.py`, `test_ws_endpoint.py`, `test_telemetry_route.py`, `test_dashboard_api.py`) use `create_hassette_stub()` and are OUT OF SCOPE.
- `test_global_jobs_and_service_info.py` has TWO fixtures: `mock_hassette_db()` (manual config — IN SCOPE) and `mock_hassette_scheduler()` (uses `create_hassette_stub()` — OUT OF SCOPE). Only migrate `mock_hassette_db`.
- `test_web_ui_watcher.py` exists in both `tests/unit/core/` and `tests/integration/` — both are in scope and listed above.

## Verify
- [ ] FR#6: `grep -rn 'def mock_hassette\|def mock_hassette_for_db\|def mock_hassette_fresh\|def mock_hassette_with_db\|def mock_hassette_db' tests/unit/ tests/integration/` returns only fixtures that call `make_mock_hassette()` (no manual `.config.` attribute assignment on MagicMock)
- [ ] AC#1: Combined with T02's grep, the full AC#1 check passes — no named factories AND no inline manual-config fixtures remain
