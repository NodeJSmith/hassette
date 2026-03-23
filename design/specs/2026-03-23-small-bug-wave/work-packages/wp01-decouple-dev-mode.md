# WP01: Decouple app actions from dev_mode (#348)

**Lane:** todo
**Closes:** #348

## Summary

Remove `_check_reload_allowed()` guard from stop/start/reload endpoints. The guard was a config-flag gate (not auth) that incorrectly blocked manual app management in production mode.

## Acceptance Criteria

- [ ] `POST /api/apps/{app_key}/start` returns 202 regardless of `dev_mode` setting
- [ ] `POST /api/apps/{app_key}/stop` returns 202 regardless of `dev_mode` setting
- [ ] `POST /api/apps/{app_key}/reload` returns 202 regardless of `dev_mode` setting
- [ ] File watcher auto-reload remains gated by `dev_mode` (no change to `app_handler.py`)
- [ ] `allow_reload_in_prod` docstring updated to clarify it only controls the file watcher
- [ ] Test updated to verify endpoints work without dev_mode

## Files to Change

| File | Change |
|------|--------|
| `src/hassette/web/routes/apps.py` | Delete `_check_reload_allowed()` (lines 38-40) and remove calls at lines 45, 56, 67 |
| `tests/integration/test_web_api.py` | Rename `test_app_management_forbidden_in_prod` → `test_app_management_works_without_dev_mode`, assert 202 |
| `src/hassette/config/config.py` | Update `allow_reload_in_prod` docstring |

## Verification

```bash
uv run pytest tests/integration/test_web_api.py -v -k "app_management"
```
