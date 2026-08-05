---
task_id: "T02"
title: "Add CliConfig group and regenerate config schema"
status: "done"
depends_on: []
implements: ["AC#13"]
---

## Summary

Add a `CliConfig` group holding the CLI's connect-target settings — `server_url`, `verify_ssl`, `token_file`, `auth_token` — and wire it onto `HassetteConfig` as `cli`. This is the config surface the rest of the feature reads from, and it exists as its own group specifically to separate "where the server binds" (`web_api.host`/`port`) from "where the client connects." Adding a group changes `hassette.schema.json`, which a pre-push hook enforces the freshness of, so regeneration ships in this task.

## Target Files

- modify: `src/hassette/config/models.py`
- modify: `src/hassette/config/config.py`
- modify: `hassette.schema.json`
- modify: `tests/unit/test_config_models.py`
- read: `design/specs/092-cli-remote-url/design.md`
- read: `design/specs/092-cli-remote-url/tasks/context.md`
- read: `scripts/export_schemas.py`
- read: `tools/check_schemas_fresh.py`

## Prompt

Add `CliConfig(ExcludeExtrasMixin, BaseModel)` to `src/hassette/config/models.py`, placed alongside the existing groups. Fields, all with docstrings below the field per the Convention Examples in `context.md`:

- `server_url: str | None = Field(default=None, json_schema_extra={"ui": {"label": "Server URL"}})`
- `verify_ssl: bool = Field(default=True, json_schema_extra={"ui": {"label": "Verify SSL"}})`
- `token_file: Path | None = Field(default=None, json_schema_extra={"ui": {"label": "Token File"}})`
- `auth_token: SecretStr | None = Field(default=None, json_schema_extra={"ui": {"label": "Auth Token"}})`

Set the group label on the model's own `model_config`, not on the field reference in `HassetteConfig`:

```python
model_config = ConfigDict(json_schema_extra={"ui": {"group_label": "CLI"}})
```

`WebApiConfig` carries a comment explaining why this placement is mandatory — a nested-model field is emitted as a `$ref`, and the server-side deref (`jsonref.replace_refs`) drops `$ref` sibling keys, so a `ui` block on the field is silently lost. Follow it.

`auth_token` is `SecretStr` for the same reason `web_api.auth_token` is: masked in logs, reprs, and the `GET /api/config` response, unwrapped only at point of use. `token_file` is a path, not a secret, so it stays a plain `Path`.

Wire it onto `HassetteConfig` in `src/hassette/config/config.py` alongside the existing group fields (`database`, `websocket`, `logging`, `lifecycle`, `web_api`, `apps`, `scheduler`, `file_watcher`, `blocking_io`):

```python
cli: CliConfig = Field(default_factory=CliConfig)
```

Add default-value tests to `tests/unit/test_config_models.py` following the shape of the existing `test_scheduler_job_timeout_seconds_default` / `test_file_watcher_watch_files_default` tests: assert each `CliConfig` field's default, and assert that `HASSETTE__CLI__SERVER_URL` and `HASSETTE__CLI__VERIFY_SSL` resolve through the normal pydantic-settings chain.

Then regenerate schemas:

```bash
uv run python scripts/export_schemas.py
git status --short
```

`export_schemas.py` writes three files: `hassette.schema.json`, `frontend/openapi.json`, and `frontend/ws-schema.json`. Adding a config group is expected to change only `hassette.schema.json`. **Check `git status` to confirm.** If `frontend/openapi.json` also changed, the frontend TypeScript types are now stale too — run `mise run worktree:setup` (worktrees do not share `node_modules/`) and re-run `uv run python scripts/export_schemas.py --types`, then include `frontend/src/api/generated-types.ts` in this task's changes. If only `hassette.schema.json` changed, no frontend work is needed.

## Focus

Do not implement any resolution logic here. This task adds the config surface only; `cli/target.py` (T03) reads it.

`nested_model_default_partial_update=True` is already set on `HassetteConfig.model_config` (`config/config.py:61`), so a partial `[hassette.cli]` TOML table will not wipe unset group defaults. Nothing extra is needed for that.

Env resolution comes free via `settings_customise_sources` — `HASSETTE__CLI__SERVER_URL`, `HASSETTE__CLI__VERIFY_SSL`, `HASSETTE__CLI__TOKEN_FILE`, `HASSETTE__CLI__AUTH_TOKEN` all work with no plumbing. Do not add a second lookup path.

`tests/integration/test_schema_freshness.py` will fail if the schema is not regenerated — that is the intended safety net, not a surprise.

`Path` and `SecretStr` are both already imported in `config/models.py`; check before adding imports.

Do not add a `cli` entry to `LoggingConfig`'s per-service log-level list in `tests/unit/test_config_models.py:170-186` — that list is per-service loggers, not config groups, and the CLI is not a service.

## Verify

- [ ] AC#13: `uv run python scripts/export_schemas.py` followed by `uv run python tools/check_schemas_fresh.py` exits 0, and `uv run pytest tests/unit/test_config_models.py -v` passes including the new `CliConfig` default and env-resolution tests.
