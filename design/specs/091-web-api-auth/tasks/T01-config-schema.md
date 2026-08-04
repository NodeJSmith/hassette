---
task_id: "T01"
title: "Add WebApiConfig auth fields and CORS wildcard validator"
status: "planned"
depends_on: []
implements: ["FR#15", "FR#19", "AC#10", "AC#11"]
---

## Summary

Adds the four new config fields the entire auth feature is built on: `auth_enabled`, `auth_token`,
`trusted_proxies`, `session_ttl` on `WebApiConfig`. Adds a validator that rejects `"*"` in
`cors_origins` at config load (closing audit finding AC#5 from issue #1117). Regenerates
`hassette.schema.json` and adds an `auth_enabled` parameter to `create_hassette_stub()` so every
downstream task (and the ~211 existing integration + ~165 e2e tests) has a stable, opt-in surface to
build against. Also adds the system test proving `auth_token` is never disclosed in plaintext by
`GET /api/config`, since declaring the field `SecretStr` is the entire mechanism — no new masking
code is needed.

## Target Files

- modify: `src/hassette/config/models.py` — add `WebApiConfig` fields, add CORS validator
- modify: `src/hassette/test_utils/web_mocks.py` — `create_hassette_stub(auth_enabled=False, ...)`
- modify: `hassette.schema.json` — regenerated (do not hand-edit)
- create: `tests/unit/config/test_web_api_config.py` — unit tests for the new fields and validator
- modify: `tests/system/test_web_api.py` — new `auth_token` non-disclosure test
- read: `src/hassette/config/config.py:142-151,248-256` — `SecretStr` field + `.get_secret_value()` pattern to mirror
- read: `src/hassette/config/models.py:323-358` — current `WebApiConfig` (fields, `model_config`, `Field(default=...)` + docstring + `ui.label`/`ui.group_label` pattern)

## Prompt

Read design.md's `## Architecture → Credential model` and `## Architecture → CORS validator`
sections, and `## Functional Requirements` FR#15 and FR#19.

In `src/hassette/config/models.py`, extend the `WebApiConfig` class (currently lines 323-358) with
four new fields, following the exact `Field(default=...)` + docstring-below + `json_schema_extra`
pattern already used by `host`, `port`, `cors_origins` in the same class:

- `auth_enabled: bool = Field(default=True)` — auth is on by default; a fresh install is protected
  with zero configuration (design.md Goals).
- `auth_token: SecretStr | None = Field(default=None)` — mirror `HassetteConfig.token`
  (`config/config.py:142-151`) exactly, including the docstring explaining `SecretStr` masking and
  `.get_secret_value()`-only-at-point-of-use discipline. When `None`, `WebApiService` resolves one at
  startup (see T02/T08) — this field only carries an explicit operator-configured value or the
  resolved value once loaded.
- `trusted_proxies: tuple[str, ...] = Field(default=())` — IP, CIDR, or hostname entries. This task
  only declares the field; parsing/validation of individual entries happens in T03 (trusted-proxy
  matching) and T08 (WebApiService startup wiring), not here.
- `session_ttl: int = Field(default=<short default, e.g. 3600>)` — seconds. Pick a short default
  consistent with design.md's "short default, configurable" language (User Scenarios, FR#8) — 3600
  (1 hour) is a reasonable default; document the choice in the field's docstring.

Add a `field_validator` (or `model_validator`) on `WebApiConfig` that raises a `ValueError` (which
Pydantic surfaces as a `ValidationError` at config load) when `"*"` appears in `cors_origins`. Per
design.md FR#15: `allow_credentials=True` is a fixed, hardcoded argument to `CORSMiddleware` in
`web/app.py:56` (not modified by this task) — the validator's only job is rejecting the wildcard
unconditionally, since the dangerous combination is otherwise always present.

Add `ui.label`/`ui.group_label` metadata for the new fields consistent with the existing pattern at
`config/models.py:323-359` so the dashboard's config editor can render them.

In `src/hassette/test_utils/web_mocks.py`, add an `auth_enabled: bool = False` parameter to
`create_hassette_stub()` (current signature at lines 79-103) and wire it into the `# web_api group`
block (lines 141-148) alongside the existing `run`, `run_ui`, `cors_origins`, etc. assignments:
`hassette.config.web_api.auth_enabled = auth_enabled`. Defaulting to `False` is what keeps the
existing ~211 integration and ~165 e2e tests passing unchanged — do not change the default.

Regenerate the schema: `uv run python scripts/export_schemas.py`. Do not hand-edit
`hassette.schema.json`.

Add the system test in `tests/system/test_web_api.py`, mirroring `test_config_endpoint_masks_token`
(lines 75-93) exactly but asserting on a configured `auth_token` value instead of the HA token —
confirm the plaintext value never appears in the `GET /api/config` response body and that the
returned field is masked the same way the HA `token` field is (via the existing `mask_values()`
mechanism, `web/config_view.py:74-98` — read but do not modify this file, it already handles any
`SecretStr` field generically).

## Focus

- This is the foundational task — every other backend task reads `WebApiConfig.auth_enabled` /
  `.auth_token` / `.trusted_proxies` / `.session_ttl`. Field names must match exactly what's used
  above; downstream tasks assume these names.
- `create_hassette_stub()`'s current `# web_api group` wiring block is at
  `src/hassette/test_utils/web_mocks.py:141-148` — add the new line there, not elsewhere in the
  function.
- Do not implement `trusted_proxies` entry parsing (IP/CIDR/hostname validation) in this task — that
  is T03's job. This task only declares the field as `tuple[str, ...]`.
- `allow_credentials=True` in `web/app.py:56` is a hardcoded `CORSMiddleware` kwarg, not a
  `WebApiConfig` field — do not add a config field for it; the validator here only checks
  `cors_origins`.
- The schema-freshness check (`tools/check_schemas_fresh.py`, wired into the pre-push hook) will fail
  if `hassette.schema.json` isn't regenerated after this change — run the regen command above before
  finishing this task.

## Verify

- [ ] FR#15: Config load with `cors_origins=("*",)` raises a `ValidationError` (unit test in `tests/unit/config/test_web_api_config.py`); config load with `cors_origins=("http://localhost:3000",)` succeeds.
- [ ] FR#19: `auth_token` is declared as `SecretStr | None` on `WebApiConfig`; a `WebApiConfig` instance with `auth_token` set renders it masked (not plaintext) via `repr()`/`str()`.
- [ ] AC#10: Unit test confirms `WebApiConfig(cors_origins=("*",))` raises at construction/validation time.
- [ ] AC#11: New system test in `tests/system/test_web_api.py` confirms `GET /api/config` (authenticated) never contains the plaintext `auth_token` value in its response body, mirroring the existing HA-token test at lines 75-93.
