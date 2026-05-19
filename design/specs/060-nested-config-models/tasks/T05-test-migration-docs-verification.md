---
task_id: "T05"
title: "Migrate test assertions, update documentation, and verify"
status: "planned"
depends_on: ["T02", "T03", "T04"]
implements: ["AC#8", "AC#10"]
---

## Summary

Update all test files that reference flat config field names to use the new nested paths, update documentation to reflect the nested config structure, and run the full verification suite (tests, type checker, linter) to confirm zero regressions. This is the final integration task — every prior task has changed source code, test infrastructure, or API contracts, and this task ensures everything works together.

## Prompt

### Step 1: Migrate test file config references

Update all test files that access config fields via flat names. The test infrastructure (make_test_config, preserve_config, web_mocks) was updated in T02, and source code in T03. Test files need both:

a) **Config construction** — tests that pass flat field overrides to `make_test_config()` need nested form:
   - `make_test_config(data_dir=tmp_path, db_retention_days=7)` → `make_test_config(data_dir=tmp_path, database={"retention_days": 7})`
   - `make_test_config(data_dir=tmp_path, websocket_heartbeat_interval_seconds=60)` → `make_test_config(data_dir=tmp_path, websocket={"heartbeat_interval_seconds": 60})`

b) **Config assertions** — tests that assert on config field values need nested access:
   - `assert config.db_retention_days == 7` → `assert config.database.retention_days == 7`
   - `assert config.websocket_heartbeat_interval_seconds == 60` → `assert config.websocket.heartbeat_interval_seconds == 60`

c) **Config mutation** — tests that mutate config fields directly need nested paths:
   - `config.db_retention_days = 14` → `config.database.retention_days = 14`

Key test files to update (highest access count first):
- `tests/unit/test_config.py` (55 accesses)
- `tests/unit/core/test_ws_connection_state.py` (28 accesses)
- `tests/integration/test_command_executor.py` (27 accesses)
- `tests/unit/core/test_websocket_readiness_events.py` (23 accesses)
- `tests/integration/test_registration.py` (23 accesses)
- `tests/integration/test_dispatch_unification.py` (23 accesses)
- `tests/unit/test_config_log_level.py` (22 accesses)
- `tests/unit/test_make_test_config.py` (12 accesses)
- All other test files with config field references

Use grep to find remaining flat field patterns after migration:
```
grep -rn 'config\.db_\|config\.websocket_\|config\.scheduler_\|config\.file_watcher_\|config\.web_api_\|config\.run_web_api\|config\.run_web_ui\|config\.autodetect_apps\|config\.app_dir\|_log_level\b' tests/ --include='*.py'
```

### Step 2: Update documentation

**Config reference page** in `docs/`: Restructure to show grouped sections with TOML examples for each group. Show both TOML section format and environment variable format.

**Getting started guide** in `docs/`: Update `hassette.toml` examples to use nested sections (`[database]`, `[websocket]`, etc. under `[hassette]`).

**Environment variable reference** in `docs/`: Update to show nested delimiter paths (`HASSETTE__DATABASE__PATH`, `HASSETTE__WEBSOCKET__HEARTBEAT_INTERVAL_SECONDS`, etc.).

**Developer guide** in `docs/`: Add guidance on where new config fields should go — which group, or root-level if cross-cutting. Reference the model docstrings.

**Docstrings**: Verify `HassetteConfig` class docstring is updated and each nested model in `models.py` has a descriptive docstring (these should already exist from T01).

### Step 3: Full verification

Run the complete verification suite:

```bash
# Unit and integration tests
timeout 300 uv run pytest tests/unit tests/integration -v -n 2 --dist loadscope

# Type checking
uv run pyright

# Linter
uv run ruff check

# Frontend build + tests
cd frontend && npm run build && npm run test

# Schema freshness
uv run python tools/check_schemas_fresh.py

# CSS lint checks
uv run python tools/check_global_css_allowlist.py
uv run python tools/check_dead_global_css.py
uv run python tools/check_css_module_globals.py
uv run python tools/check_undefined_css_refs.py
```

If any failures, fix them. The goal is zero test failures and zero type errors.

### Step 4: Final grep for stale references

Run a comprehensive grep across the entire repo for any remaining flat field references:
```
grep -rn 'db_retention_days\|db_max_size_mb\|db_migration_timeout\|db_write_queue_max\|telemetry_write_queue_max\|websocket_authentication_timeout\|websocket_response_timeout\|websocket_connection_timeout\|websocket_total_timeout\|websocket_heartbeat_interval\|websocket_connect_retry\|websocket_early_drop\|websocket_max_recovery\|scheduler_min_delay\|scheduler_max_delay\|scheduler_default_delay\|scheduler_behind_schedule\|scheduler_job_timeout\|file_watcher_debounce\|file_watcher_step\|database_service_log_level\|bus_service_log_level\|scheduler_service_log_level\|app_handler_log_level\|web_api_log_level\|websocket_log_level\|service_watcher_log_level\|file_watcher_log_level\|task_bucket_log_level\|command_executor_log_level\|apps_log_level\|state_proxy_log_level\|api_log_level' src/ tests/ --include='*.py' | grep -v __pycache__ | grep -v models.py | grep -v 'AliasChoices'
```

Any matches (excluding models.py field definitions and AliasChoices declarations) indicate missed migration sites.

## Focus

- `tests/unit/test_config.py` — the largest test file (55 accesses). Contains tests for defaults, validation, field coercion, TOML loading, env var loading. Many of these test the config module directly and may already be partially updated by T01. Verify no duplication.
- `tests/unit/test_config_log_level.py` — tests for the log level default behavior. After migration, per-service levels default to `None` and are filled by model_validator. Test assertions may need fundamental restructuring, not just renames.
- `tests/integration/test_command_executor.py` — creates configs with `telemetry_write_queue_max` overrides. Needs nested form.
- `tests/unit/core/test_ws_connection_state.py` and `test_websocket_readiness_events.py` — create configs with `websocket_*` overrides. High access count.
- System tests (`tests/system/`) and E2E tests (`tests/e2e/`) may also reference config fields. Check `tests/system/conftest.py` and `tests/e2e/conftest.py`.
- Documentation lives in `docs/`. Check which pages reference config field names — the config reference page, getting started guide, and any tutorial pages.
- The `nox` sessions (`uv run nox -s dev`, `uv run nox -s tests`) run pytest with specific marker filters and `--dist loadscope`. Use the same settings for verification.

## Verify
- [ ] AC#8: Full test suite passes with zero failures (`uv run pytest tests/unit tests/integration -v -n 2 --dist loadscope`)
- [ ] AC#10: Pyright type checking passes with no new errors (`uv run pyright` exits 0)
