---
task_id: "T04"
title: "App config endpoint: schema-driven masking, remove regex"
status: "planned"
depends_on: ["T02", "T03"]
implements: ["FR#2", "AC#2", "AC#4", "AC#5"]
---

## Summary
Bring the app config endpoint onto the same masking principle as the global one. Today it redacts secrets
with a field-name regex (`_SECRET_KEYS`) that is security theatre and only recurses one level. Replace it
with schema-driven masking via the shared builder: the app values are a raw TOML dict (not a live model),
so the schema-driven mask is essential here. Keep the `AppConfigResponse` shape stable so the app-config
CLI and frontend keep working — only how `app_config` is masked and that `config_schema` is now deref'd
changes.

## Target Files
- modify: `src/hassette/web/routes/apps.py` — remove `_SECRET_KEYS`, `_redact_dict`, `_redact_secrets`;
  build `app_config` + deref'd `config_schema` via the shared builder.
- read: `src/hassette/web/config_view.py` (T02 builder).
- modify: `tests/unit/cli/test_commands_app.py` — app CLI values are now schema-masked, not regex-masked;
  update any assertion that depended on name-based redaction.
- read: `src/hassette/test_utils/web_helpers.py` — `make_app_config_response` must still match
  `AppConfigResponse` (shape unchanged); update only if needed.
- create/modify: app-config masking test in the web-api test suite (type-driven demonstration).

## Prompt
Implement the app endpoint changes per the design doc's `## Architecture → Backend: one config-view
builder` (App endpoint paragraph) and `## Replacement Targets`.

1. `web/routes/apps.py`: delete `_SECRET_KEYS`, `_redact_dict`, and `_redact_secrets`. In
   `get_app_config`, build the view with the shared `build_config_view(schema, manifest.app_config)` where
   `schema = app_config_cls.model_json_schema()`. Return `AppConfigResponse` with `app_config` = the
   masked values and `config_schema` = the deref'd schema. Preserve the list-of-instances handling (when
   `app_config` is a list, mask each instance). Keep `AppConfigResponse`'s field set unchanged.
2. The masking is schema-driven: a field typed `SecretStr` on the app's `AppConfig` is masked; an untyped
   `str` field is not — even if its name looks secret. This is the accepted, documented tradeoff.
3. Tests:
   - A type-driven masking test: an app config with an untyped `api_key: str` shows the value unmasked,
     and the same field typed `SecretStr` shows masked.
   - An integration assertion that both endpoints return schema + values with the schema fully deref'd
     (no `$ref` in the body). Note the field names differ: the global endpoint uses `config_values`, the
     app endpoint keeps its existing `app_config` field (assert `app_config`, not `config_values`, for the
     app response).
   - Update `tests/unit/cli/test_commands_app.py` for schema-masked values. Confirm
     `make_app_config_response` still validates against `AppConfigResponse`.
   Run `uv run pytest -n 4 <files>`.

## Focus
The critical detail (design F1): `manifest.app_config` is a **raw TOML dict**, not a live `AppConfig`
instance, so `model_dump` masking is unavailable — the schema-driven mask in the builder is the only thing
that can redact it. The single-level recursion bug in the old `_redact_dict` is moot once the builder's
recursive mask replaces it. AC#2 spans both endpoints, so its integration test belongs here (after both
endpoints exist — global from T03, app from this task). `hassette app config` (`cli/commands/app.py`)
validates `AppConfigResponse`; its shape is unchanged so it keeps working, but the values it renders are
now schema-masked — check `test_commands_app.py` for assertions on specific redacted values.

## Verify
- [ ] FR#2: `GET /api/apps/{key}/config` returns the app's schema + values in the unified shape for every
  registered app, including the multi-instance (list) case.
- [ ] AC#2: both endpoints return schema + fully-deref'd values (no `$ref` in the body) — global as
  `{config_schema, config_values}`, app as `AppConfigResponse` with `config_schema` + `app_config`.
- [ ] AC#4: an untyped `api_key: str` renders unmasked; the same field typed `SecretStr` renders masked.
- [ ] AC#5: `_SECRET_KEYS`, `_redact_dict`, and `_redact_secrets` no longer exist in `web/routes/apps.py`.
