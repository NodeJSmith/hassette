---
task_id: "T01"
title: "Make token optional and update packaging"
status: "planned"
depends_on: []
implements: ["FR#7", "FR#8", "AC#6", "AC#9"]
---

## Summary

Change `HassetteConfig.token` from required to optional so CLI commands can instantiate config without HA credentials. Add property guards to prevent `Bearer None` headers and `len(None)` errors. Add startup validation so the server still rejects missing tokens. Update `pyproject.toml` with new dependencies. Remove unused pydantic-settings CLI settings from `model_config`. Update test infrastructure to match.

## Prompt

### Config changes

Edit `src/hassette/config/config.py`:

1. **Token field** (line 132): Change `token: str = Field(default=...)` to `token: str | None = Field(default=None, ...)`. Keep the existing `validation_alias` unchanged.

2. **`auth_headers` property** (line 225): Add a guard — if `self.token is None`, return `{}` (empty dict). Currently returns `{"Authorization": f"Bearer {self.token}"}` which would produce `Bearer None`.

3. **`truncated_token` property** (line 235): Add a guard — if `self.token is None`, return `"<not set>"`. Currently calls `len(self.token)` which would raise `TypeError`.

4. **`model_config`** (lines 58-68): Change `cli_parse_args` from `True` to `False`. Remove `cli_prog_name`, `cli_kebab_case`, `cli_ignore_unknown_args`, and `cli_shortcuts` — these are only relevant when pydantic-settings parses CLI args, and cyclopts replaces that (T02).

### Startup validation

Edit `src/hassette/__main__.py` — in the `main()` function (line 41), after `HassetteConfig()` is instantiated but before `Hassette(config)` is created, add a check: if `config.token is None`, raise `FatalError("HA token is required for server startup. Set HASSETTE__TOKEN, HA_TOKEN, or pass --token.")`. This preserves the existing exception handling in `entrypoint()` which already catches `FatalError`.

### Packaging

Edit `pyproject.toml`:
- Add `cyclopts>=4.0,<5.0` to `[project.dependencies]` (Rich is a transitive dep)
- Add `httpx>=0.28.0` to `[project.dependencies]`

### Test infrastructure

- `tests/conftest.py` line 98: `TestConfig` sets `cli_parse_args=False` in model_config — now redundant (parent defaults to False). Remove it for clarity or leave it; either is fine.
- `src/hassette/test_utils/config.py` line 56: same — the harness config sets `cli_parse_args=False`. Now redundant.
- `tests/unit/test_config.py`: Many tests set `cli_parse_args=False` in model_config overrides. Now redundant. Leave them — removing is churn that doesn't change behavior.
- Grep for `HassetteConfig(` calls without `token=` — these will now get `token=None` instead of `ValidationError`. Verify each still tests the intended behavior.

### Unit tests

Write tests for:
- `HassetteConfig(token=None)` instantiates without error
- `HassetteConfig(token=None).auth_headers` returns empty dict
- `HassetteConfig(token=None).truncated_token` returns `"<not set>"`
- `HassetteConfig(token="abc123").auth_headers` returns `{"Authorization": "Bearer abc123"}` (existing behavior preserved)
- Server startup with `token=None` raises `FatalError`
- Config env var loading still works (`HASSETTE__TOKEN`, `HA_TOKEN`)

## Focus

- `src/hassette/config/config.py`: `HassetteConfig` at line 44, token at 132, auth_headers at 225, truncated_token at 235, model_config at 56-68, resolve_paths validator at 258
- `src/hassette/__main__.py`: `main()` at line 41, `entrypoint()` at 65. FatalError is already imported
- `src/hassette/core/websocket_service.py:541` uses `config.token` directly — safe because startup validation prevents None reaching the server
- The `resolve_paths` validator (config.py:258) creates `config_dir` and `data_dir` on disk. CLI commands instantiating HassetteConfig trigger this. Design doc says this is acceptable
- Test files with `cli_parse_args=False`: tests/conftest.py, test_config.py (~15), test_config_models.py (~7), test_log_records.py (~4), test_autodetect_apps.py (~5), test_schema_migration.py, test_apps_env.py, system/conftest.py, test_utils/config.py

## Verify

- [ ] FR#7: HassetteConfig loads server address from env vars and config files with token=None (CLI usage path)
- [ ] FR#8: Server startup with valid token continues to work (backward compat)
- [ ] AC#6: Running the server start path with a valid token still starts the framework
- [ ] AC#9: HassetteConfig reads web_api.host and web_api.port from env/config for CLI address discovery
