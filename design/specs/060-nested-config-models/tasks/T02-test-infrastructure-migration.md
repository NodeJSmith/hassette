---
task_id: "T02"
title: "Migrate test infrastructure to nested config"
status: "planned"
depends_on: ["T01"]
implements: ["FR#10", "AC#7"]
---

## Summary

Update the test infrastructure that all other tests depend on — `make_test_config()`, `preserve_config`, `web_mocks.py`, and related test utilities — to work with the nested config structure from T01. This must be done before any source access site migration (T03) because tests cannot construct configs or create mock hassette instances without these utilities working.

## Prompt

### Step 1: Update `make_test_config()` in `src/hassette/test_utils/config.py`

Update the hermetic config factory to support nested model field overrides.

**Internal defaults migration:** Change the factory's built-in defaults from flat to nested form:
- `"autodetect_apps": False` → `"app": {"autodetect": False}`
- `"run_web_api": False` → `"web_api": {"run": False}`
- `"run_app_precheck": False` stays root (it's a root-level field)
- `"disable_state_proxy_polling": True` stays root
- `"token": "test-token"` stays root
- `"base_url": "http://test.invalid:8123"` stays root
- `"data_dir": data_dir` stays root

**Add `extra="forbid"`** to the hermetic subclass's `model_config` override so stale flat field names (e.g., passing `db_path=` instead of `database={"path": ...}`) raise immediately instead of being silently absorbed into `model_extra`.

**Support both calling styles:** `make_test_config(database={"retention_days": 14})` and `make_test_config(database=DatabaseConfig(retention_days=14))` should both work — Pydantic handles dict-to-model coercion natively.

### Step 2: Update `preserve_config` in `src/hassette/test_utils/harness.py`

Replace the per-key `setattr` restoration (lines 152-162) with `HassetteConfig.model_validate(original)` — full model reconstruction fires all validators including cross-field ones. The `original` dict from `model_dump()` will contain nested dicts after T01, so `model_validate` correctly reconstructs the nested structure.

### Step 3: Update `web_mocks.py` in `src/hassette/test_utils/web_mocks.py`

The `create_hassette_stub()` function sets flat config attributes on a MagicMock (lines 68-74):
```python
hassette.config.run_web_api = run_web_api
hassette.config.web_api_cors_origins = cors_origins
```

After migration, some of these fields live on nested models. MagicMock auto-creates nested attributes, so `hassette.config.web_api.run = run_web_api` works without explicit setup. Update the attribute assignments to use nested paths. Also update the `config_dump` dictionary (line 133) to nested structure.

### Step 4: Update other test utilities as needed

Check and update any config field access in:
- `src/hassette/test_utils/fixtures.py` — config field references in fixture setup
- `src/hassette/test_utils/helpers.py` — config field access in helper functions
- `src/hassette/test_utils/reset.py` — config field access in reset logic
- `src/hassette/test_utils/app_harness.py` — config field access in app test harness

### Step 5: Update `make_test_config` tests

Update `tests/unit/test_make_test_config.py` to verify:
- Nested dict overrides work: `make_test_config(data_dir=tmp_path, database={"retention_days": 14})`
- Model instance overrides work: `make_test_config(data_dir=tmp_path, database=DatabaseConfig(retention_days=14))`
- Stale flat field names raise (e.g., `make_test_config(data_dir=tmp_path, db_retention_days=14)` should fail due to `extra="forbid"`)
- Default values produce valid config with nested structure

## Focus

- `src/hassette/test_utils/config.py` (99 lines) — `make_test_config()` function and hermetic class factory. The closure-ref pattern (`cell[0] = merged`) must continue working. The key change is the defaults dict structure and adding `extra="forbid"`.
- `src/hassette/test_utils/harness.py:152-162` — `preserve_config` context manager. The `model_dump()` → `model_validate()` change is straightforward but verify it works with the nested structure.
- `src/hassette/test_utils/web_mocks.py:60-80` — `create_hassette_stub()` sets 7 config attributes directly on a MagicMock. MagicMock auto-creates nested attrs, so `hassette.config.web_api.run` works naturally.
- `tests/unit/test_make_test_config.py` (12 config accesses) — existing tests for the factory.
- The hermetic subclass pattern caches a single class to avoid accumulating `__subclasses__()`. The class definition itself changes (new `model_config`), but since it's cached on first call, tests that import it get the updated version.
- `src/hassette/test_utils/fixtures.py` uses `make_test_config` extensively — verify all fixtures still produce valid configs after the defaults change.

## Verify
- [ ] FR#10: `make_test_config(data_dir=tmp_path, database={"retention_days": 14})` produces a config where `config.database.retention_days == 14` and all other database defaults are intact
- [ ] AC#7: Both nested dict kwargs and model instance kwargs work with `make_test_config`; stale flat field names raise ValidationError
