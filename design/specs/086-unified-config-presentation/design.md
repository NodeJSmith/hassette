# Design: Unified Config Presentation in the Web UI

**Date:** 2026-06-25
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-06-25-config-ui-visibility-metadata/research.md (mechanical findings valid; its "Option A — preserve current shape" conclusion is superseded by the show-all decision)

## Problem

Hassette surfaces configuration to the web UI through two divergent code paths that do not
agree with each other, and the global one is actively disliked.

- **Global config** (`/api/config` → `pages/config.tsx`) is hand-maintained: `config_response_from`
  (`web/mappers.py:209-255`) copies ~27 of ~90 fields into parallel response classes
  (`web/models.py:405-470`), *restructures* them (flattens `apps.directory`, coerces `Path`→`str`,
  `tuple`→`list`), and silently **drops entire groups** — `database`, `websocket`, `blocking_io`
  never appear. The frontend then re-curates those fields into seven hand-written groups
  (`pages/config.tsx:36-101`). Adding a config field requires editing four places, and the page
  shows an incomplete, opinionated slice of the real configuration.
- **App config** (`/api/apps/{key}/config` → `components/app-detail/config-tab.tsx`) already does the
  right thing structurally: it ships `app_config_cls.model_json_schema()` plus the values and renders
  them generically (`config-tab.tsx:75` `SchemaConfigTable`). But it redacts secrets with a
  **field-name regex** (`apps.py:23` `_SECRET_KEYS`) that is security theatre — it masks `token` and
  `password` by name while missing `pat`, `connection_string`, or any innocuously-named secret, and
  its recursion only descends one level (`apps.py:33`).

So there are two renderers, two response shapes, and *three* inconsistent secret mechanisms
(omit-by-name for the global token, name-regex for app config, and the type system for nothing).
The global surface is the one the user wants replaced, and the app surface already proves the
pattern that should replace it.

## Goals

- Surface the **complete** configured picture for both the global `HassetteConfig` and every app's
  `AppConfig` — no field silently dropped.
- Unify both surfaces on **one** mechanism: expose each as an enriched JSON schema plus values, and
  render both with **one** generic, read-only component.
- Replace all three secret mechanisms with a single **type-driven** rule: fields declared `SecretStr`
  are masked; nothing is masked by name. The plaintext value never crosses the wire.
- Delete the hand-maintained global path (`config_response_from`, the `*ConfigResponse` classes, the
  curated frontend groups) rather than maintaining it alongside the new one.
- Keep real Home Assistant authentication working through the `SecretStr` migration — the change must
  not silently break REST/WebSocket auth while unit tests stay green.
- Ship the **presentation-metadata mechanism** (a `json_schema_extra` `ui` namespace) end to end — the
  field-level metadata #690 asked for — so the renderer reads `ui` hints and the tiering fast-follow
  becomes a pure data change, not a re-plumbing of these files.

## Non-Goals

Explicitly out of scope for this change (deferred to fast-follows or rejected):

- **Relevance tiering — the `tier` *values* and the "show advanced" affordance.** Deciding which fields
  are `common` vs `advanced` is ~90 judgment calls; that thought-work is deferred. The `tier` *key* is
  part of the `ui` namespace shape from day one (so the fast-follow is data-only), but **no field sets
  it and the renderer ignores it in MVP** — every field renders at one level, no collapse affordance.
  This is the one piece split out of the metadata mechanism: the plumbing ships now, the tier decisions
  do not. (See Architecture → the `ui` metadata mechanism.)
- **Reveal-secret button.** Requires the plaintext over the wire and is unsafe on the unauthenticated
  web API. Gated on the web API gaining authentication.
- **Web API authentication.** Out of scope.
- **Config editing / write-back.** Out of scope — collides with layered config sources
  (`config.py:76-83`), has no write-back infrastructure, and the API is unauthenticated.

## User Scenarios

### Operator: runs a Hassette instance, inspects its configuration in the dashboard
- **Goal:** see exactly how this instance is configured, including the parts that are usually invisible.
- **Context:** debugging behavior ("why is the websocket reconnecting?", "what's my retention window?")
  or verifying a deployment.

#### Inspect global configuration

1. **Open the Config page.**
   - Sees: every config group rendered as a labeled section — including `database`, `websocket`, and
     `blocking_io`, which the old page omitted.
   - Then: fields show their current values, formatted by type (booleans as yes/no, paths as code,
     durations humanized, lists expanded).
2. **Look for the Home Assistant token.**
   - Sees: the `token` field present, shown as a masked placeholder (not absent, not plaintext).
   - Decides: confirms a token is set without it leaking on screen.

#### Inspect an app's configuration

1. **Open an app detail page, Config tab.**
   - Sees: the same rendering as the global page — schema-driven, grouped, type-formatted.
   - Then: any field the app author typed `SecretStr` shows masked; ordinary fields show their values.

### App author: writes an `AppConfig` subclass with a secret field
- **Goal:** have their secret automatically hidden in the dashboard without configuring anything UI-specific.
- **Context:** writing an app that needs an API key.

#### Declare a secret

1. **Type the field `SecretStr` instead of `str`.**
   - Sees: in the Config tab, the field renders masked.
   - Decides: nothing else to do — masking follows the type, not a naming convention.

## Functional Requirements

- **FR#1** The global config endpoint returns the complete `HassetteConfig` as a JSON schema plus its
  current values, including every nested group (`database`, `websocket`, `blocking_io`, `lifecycle`,
  `web_api`, `apps`, `scheduler`, `file_watcher`, `logging`) and every flat top-level field — no field
  is omitted.
- **FR#2** The app config endpoint returns the app's config schema plus values in the same envelope
  shape, for every registered app, including the existing multi-instance (list) case.
- **FR#3** A field declared `SecretStr` is masked in the response: a masked placeholder when set, and a
  "not set" / null indication when unset. The plaintext value never appears in any response body.
- **FR#4** Secret masking is determined by the field's declared type (its schema `writeOnly` /
  `format: "password"` markers), not by matching the field name.
- **FR#5** Nested-model schema references (`$ref` / `$defs`) are resolved server-side so the response
  schema is fully inlined; the frontend never walks a `$ref`.
- **FR#6** The web UI renders both the global Config page and the app Config tab with a single generic
  component driven by the `{schema, values}` pair.
- **FR#7** The renderer derives each field's label from its `ui.label` override when present, otherwise
  the humanized field name, and its help text from the schema `description` (field docstring) — not from
  raw snake_case keys alone.
- **FR#8** The renderer groups fields into sections by nested-model structure (one section per config
  group), with flat top-level fields under a core/general section.
- **FR#9** The renderer formats each value by its type: boolean, path, enum, duration, list/tuple, and
  nested object.
- **FR#10** Real Home Assistant authentication (REST headers and WebSocket `access_token`) continues to
  use the plaintext token after the `SecretStr` migration.
- **FR#11** A config field (global or app) can declare presentation metadata via a `json_schema_extra`
  `ui` namespace (`label`, `group_label`, `order`, `widget`); the metadata survives schema export to the
  frontend, and the renderer applies each hint when present and falls back to a schema-derived default
  when absent. The `ui.tier` key is part of the namespace shape but is unset and ignored in MVP.
- **FR#12** The `hassette config` CLI command continues to display the configuration after the endpoint
  change — now the complete set of groups and flat fields, with secrets masked — in both human and
  `--json` output.

## Edge Cases

- **App config served as a list** (multiple instances of one app): each instance is masked and rendered
  independently — the existing `isListConfig` path in `config-tab.tsx:209`.
- **App with no custom `AppConfig` fields** (default `AppConfig`): renders an empty/near-empty state,
  not an error.
- **Secret field unset** (`None` or empty string): renders "not set", not a mask placeholder. For the
  global `token`, both `None` and `""` are treated as "not set" — the existing `if not config.token`
  check at `server.py:15` stays correct after the `SecretStr` migration (verified: `SecretStr` truthiness
  falls back to `__len__`, so `""` is falsy).
- **Nested `SecretStr` inside an app's nested config model**: schema-driven masking recurses into nested
  objects and masks the field at depth (fixing the single-level recursion bug at `apps.py:33`).
- **Untyped secret** (`api_key: str`, not `SecretStr`): shown unmasked. This is the accepted, documented
  tradeoff of type-driven masking — honest about what it does, and it nudges authors toward `SecretStr`.
- **App schema generation fails** (`get_app_config` already wraps `model_json_schema()` in try/except at
  `apps.py:120-123`): the renderer falls back to a schema-less value table (existing `SimpleConfigTable`
  path), still with masking applied where the raw values allow.
- **Discriminated-union `$ref` mapping**: server-side deref must not mangle discriminator `mapping`
  refs. N/A for the current plain nested-model config groups, but the deref implementation must be
  re-checked if any config field ever becomes a discriminated union.
- **Very large / deeply nested value**: the renderer keeps the existing expand affordance (`ConfigValue`
  in `config-tab.tsx:37`).

## Acceptance Criteria

- **AC#1** `GET /api/config` returns keys for every `HassetteConfig` field and nested group defined in
  `config/config.py` and `config/models.py` — specifically including `database`, `websocket`, and
  `blocking_io`, which the current response omits. (maps FR#1)
- **AC#2** Both `GET /api/config` and `GET /api/apps/{key}/config` return schema + values with the schema
  fully inlined (no `$ref` in the body) — the global endpoint as `{config_schema, config_values}`, the app
  endpoint as `AppConfigResponse` keeping its existing `config_schema` + `app_config` fields (the app
  values field is `app_config`, not `config_values`). (maps FR#2, FR#5)
- **AC#3** `token` appears in `GET /api/config` as a masked placeholder, and the plaintext token string
  is absent from the response body. (replaces `test_token_not_in_response`; maps FR#3)
- **AC#4** An app whose config has an untyped `api_key: str` shows that value unmasked, while the same
  field typed `SecretStr` shows masked — demonstrating type-driven, not name-driven, masking. (maps
  FR#4)
- **AC#5** The `_SECRET_KEYS` regex and the `_redact_dict` / `_redact_secrets` helpers no longer exist
  in `web/routes/apps.py`. (maps FR#4)
- **AC#6** The `*ConfigResponse` classes and `config_response_from` no longer exist, and `pages/config.tsx`
  no longer contains a hand-written `groups` array. (maps FR#1, FR#6)
- **AC#7** A live Hassette authenticates to Home Assistant over both REST and WebSocket with the
  `SecretStr` token — verified on `nox -s system` and `nox -s e2e`, not only unit tests. (maps FR#10)
- **AC#8** `preserve_config` snapshots and restores a `SecretStr` token across a test scope without
  poisoning it to the masked value. (maps FR#10)
- **AC#9** The Config page and the app Config tab render through the same component, with labels from
  docstrings, sections grouped by nested structure, and type-formatted values; the Config page displays
  the previously-hidden `database`, `websocket`, and `blocking_io` groups. (maps FR#6, FR#7, FR#8, FR#9,
  FR#1)
- **AC#10** Each active `ui` hint changes the render and falls back when absent: `ui.label` sets the
  field's display name (un-annotated → humanized name), `ui.group_label` sets a section title,
  `ui.order` sets within-section sort order, and `ui.widget` overrides the type-derived format. The `ui`
  block survives the schema-export round-trip (deref + envelope) intact, and a unit test asserts every
  `ui` block's shape (allowed keys, value types, `tier` only `common`/`advanced`). No field sets
  `ui.tier` and the renderer applies no tier-based collapsing. (maps FR#11)
- **AC#11** `hassette config` (human and `--json`) renders `config_values` from the new
  `ConfigSchemaResponse` envelope without error, shows the previously-omitted groups (`database`,
  `websocket`, `blocking_io`), and displays `token` masked. (maps FR#12)
- **AC#12** A nested-group field carries a non-empty `description` in the served schema — e.g.
  `database.retention_days` has its docstring as `description` — so nested fields render with help text,
  not just a title. (maps FR#7)

## Key Constraints

- **No field-name secret matching.** The removed `_SECRET_KEYS` regex must not be reintroduced in any
  form (server or client). Masking is type-driven only.
- **Plaintext token must never reach the wire.** Masking failures are a security regression, not a
  cosmetic bug. The masked-value path is the only path; there is no "reveal" in MVP.
- **Ship the metadata mechanism, not the tier decisions.** The `json_schema_extra` `ui` namespace and
  the renderer's consumption of it are in MVP. What stays out: setting `ui.tier` on any field (the ~90
  judgment calls) and building the "show advanced" affordance. Do not collapse or hide fields by tier in
  MVP, and do not populate `ui` hints field-by-field as a rule — only where the default render is poor.
- **Do not preserve the current global wire shape.** The restructuring in `config_response_from` is
  being removed deliberately; do not keep a compatibility shim that re-flattens or re-curates.

## Dependencies and Assumptions

- **Pydantic v2 schema behavior:** `model_json_schema()` emits `$defs`/`$ref` for nested models and
  marks `SecretStr` fields with `writeOnly: true` and `format: "password"`. Masking and deref both
  rely on these. `model_dump(mode="json")` natively renders `SecretStr` as `"**********"`.
- **`use_attribute_docstrings=True`** turns a field's docstring into its schema `description`. It is set
  on `HassetteConfig` (`config.py:61`) **but not on the nested-group models** (`DatabaseConfig`,
  `WebSocketConfig`, …) — verified: `HassetteConfig.model_json_schema()` gives `base_url`/`token` a
  `description` but gives `database.retention_days` **none**. So only the ~22 top-level fields get help
  text today; the ~90 nested-group fields (the bulk of the config) get a title but no description. This
  must be fixed (see Architecture → Field descriptions on nested groups). Labels still default to the
  humanized field name regardless; the `ui` namespace overrides where that default reads poorly.
- **No persisted config.** `HassetteConfig` is loaded fresh from layered sources each run; there is no
  stored config to migrate.
- **Server-side deref uses `jsonref`** (a new dependency, added to `pyproject.toml`).
  `jsonref.replace_refs()` already handles the `$ref` / `$defs` / cycle / sibling-key edge cases, so we
  don't re-find and re-fix them. Not currently installed.
- **No external app authors confirmed**, but project memory warns "grep for callers ≠ zero users" — so
  the `str`→`SecretStr` behavior change ships with a documented breaking-change note regardless.

## Architecture

The change has three layers — a shared backend view builder, two thin endpoint adapters, and one
shared frontend renderer — plus a `SecretStr` migration that is sequenced first and the `ui`
presentation-metadata mechanism that rides through all three layers.

### Backend: one config-view builder, two callers

Introduce a single helper (e.g. `web/config_view.py`) that produces the unified payload from a model
class and a values source:

```
build_config_view(schema: dict, values: dict) -> {"config_schema": <deref'd>, "config_values": <masked>}
```

It does two things:

1. **Deref the schema** via `jsonref.replace_refs()`, producing a fully self-contained schema. Using the
   library (not a hand-rolled walk) means the `$ref`/`$defs`/cycle/sibling-key edge cases are already
   solved. The one known caveat: `jsonref` can mangle discriminator `mapping` refs under discriminated
   unions — N/A for the current plain nested-model config groups, but re-check if any config field ever
   becomes a discriminated union (see Edge Cases). (The current app renderer does not resolve `$ref` at
   all — `config-tab.tsx:66` `resolveType` only handles `anyOf` — so nested groups like
   `HassetteConfig`'s nine sub-models require this.)
2. **Mask by type.** Walk the deref'd schema; for any property marked `writeOnly: true` or
   `format: "password"` (i.e. `SecretStr`-typed), replace the corresponding value in the values dict
   with the mask sentinel when set, leave it null/absent when unset. Recurse into nested objects. This
   is the single masking rule for both surfaces.

**Global endpoint** (`web/routes/config.py`): build the view from `HassetteConfig.model_json_schema()`
and `hassette.config.model_dump(mode="json")`. `model_dump(mode="json")` already masks `SecretStr`
natively; the schema-driven mask is then idempotent over it — both surfaces end up masked by the same
declared rule. Return a typed `ConfigSchemaResponse` envelope. `config_response_from` and all
`*ConfigResponse` classes are deleted.

**App endpoint** (`web/routes/apps.py`): the values are a **raw TOML dict** (`manifest.app_config`), not
a live `AppConfig` instance — so `model_dump` masking is unavailable and the schema-driven mask is
*essential* here. Build the view from the already-generated `config_schema` and the raw dict. Remove
`_SECRET_KEYS`, `_redact_dict`, and `_redact_secrets` entirely. Preserve the list-of-instances handling.
The endpoint keeps returning `AppConfigResponse` (its `app_key`/`filename`/`class_name`/`enabled`/
`app_config`/`config_schema` shape is unchanged — only how `app_config` is masked and that
`config_schema` is now deref'd changes), so the app-config CLI and frontend consumers keep working.

### CLI consumer: `hassette config`

The global endpoint is consumed not only by the web UI but by the `hassette config` CLI command
(`cli/commands/misc.py` → `cmd_config`), which today does `client.get("/api/config", ConfigResponse)` and
renders the model with `render_detail`. Deleting `ConfigResponse` and changing the response shape breaks
it, so the migration carries the CLI:

- `cmd_config` validates the new `ConfigSchemaResponse` envelope and renders **`config_values`** (the
  masked, nested values dict). It does not need `config_schema`.
- `render_detail` (`cli/output.py:237`) currently requires a `BaseModel` but its rendering body already
  handles nested dicts as sections. Extract that body into a dict-capable helper (e.g.
  `render_detail_dict(data, title, json_mode)`) operating on a plain dict — dropping the two
  model-specific lines (`item.model_dump(mode="json")` becomes the passed-in dict; the
  `_resolve_cli_formatters(type(item))` field-formatter lookup is dropped, harmless since the deleted
  `ConfigResponse` carried no `CliFormat` fields) — and have `cmd_config` call it with `config_values`.
  This keeps the sectioned key-value panel rather than downgrading to `render_raw`'s JSON dump.
  `_humanize_*` helpers are reused; the `ConfigResponse` example in `_humanize_model_name`'s docstring is
  illustrative only and needs no change.
- Result: `hassette config` now shows the **complete** config (all groups, previously-omitted ones
  included) with `token` masked — consistent with the web UI's show-all. Raw snake_case keys stay (the
  terminal convention; `ui` labels are a web-only concern). `--json` mode dumps `config_values`.

### The `ui` presentation-metadata mechanism (mechanism in MVP, tier values deferred)

Fields declare optional presentation metadata through Pydantic's `json_schema_extra` under a single
`ui` namespace:

```python
port: int = Field(default=8126, json_schema_extra={"ui": {"label": "Web API Port"}})
```

The namespace shape is fixed now so the tiering fast-follow is a data-only addition:

| key | meaning | MVP status |
|---|---|---|
| `label` | field display name override | **active** — used where the humanized field name is poor |
| `group_label` | section title override (set on a nested-group field) | **active** |
| `order` | integer sort order within a section | **active** |
| `widget` | formatting-hint override (force a non-default render for a type) | **active** |
| `tier` | `common` \| `advanced` relevance tier | **reserved — defined in the shape, unset on every field, ignored by the renderer.** Populating it (the ~90 judgment calls) and the "show advanced" affordance are the deferred fast-follow. |

**Round-trip.** `json_schema_extra` is merged verbatim into the field's node by `model_json_schema()`,
survives `jsonref.replace_refs()` deref, and rides inside the response. So the `ui` block reaches the
frontend on both surfaces with no extra plumbing. It applies to app authors' `AppConfig` fields too —
the mechanism is shared, not global-only.

**Population in MVP is by need, not by rule.** Do not annotate all ~90 fields. Add `ui` hints only where
the schema-derived default renders poorly — chiefly `label`/`group_label` for acronyms and multi-word
names the humanizer can't infer ("Web API", "CORS Origins", "Blocking I/O"), and `order`/`widget` for the
occasional field that needs it. Everything else derives from the plain schema. This keeps the mechanism
populated by real callers (not speculative) while leaving the per-field judgment-heavy `tier` work out.

**Why the mechanism ships now but tier values don't:** the plumbing (namespace shape, round-trip,
renderer consumption) is mechanical and touches the same files this change already rewrites; deferring it
would force the fast-follow to re-open them. Deciding `common` vs `advanced` per field is judgment work
with no mechanical shortcut, so it waits. The split is mechanism-now / decisions-later.

### Backend: `SecretStr` migration (sequenced first — see Test Strategy)

Change `HassetteConfig.token` from `str | None` to `SecretStr | None` (`config.py:131`). Verified against
Pydantic 2.12.3: `SecretStr` defines `__len__` but **not** `__bool__` (truthiness falls back to length),
is **not** subscriptable, is **not** JSON-serializable, `str(SecretStr)` renders `"**********"`, and
`SecretStr(...) == "<str>"` is `False`. The migration touches two distinct classes of site.

**Source sites — break real HA auth (unit tests mock these; verify on `nox -s system`/`e2e`):**

- `config.py:235` `auth_headers` — `f"Bearer {self.token}"` interpolates to `"Bearer **********"`, sending
  a masked header → use `self.token.get_secret_value()`.
- `config.py:243-251` `truncated_token` — `len(self.token)` works (SecretStr has `__len__`), but the
  slicing `self.token[:n]` raises `TypeError` (`SecretStr` is not subscriptable) → operate on
  `.get_secret_value()`.
- `core/websocket_service.py:557,564` — `send_json({"access_token": token})` raises `TypeError`
  (`SecretStr` is not JSON-serializable), breaking WS auth → use `.get_secret_value()`.

**Not a change:** `server.py:15` `if not config.token` is safe as-is — `SecretStr`'s `__len__`-based
truthiness treats both `None` and `""` as falsy, preserving the missing-token check. (Do not "fix" it.)

**Test sites — break at unit-test time** (`SecretStr(...) == "<str>"` is `False`); update each to compare
`.get_secret_value()` or construct `SecretStr` fixtures:

- `test_utils/mock_hassette.py:89` — `config.token == "test-token"`.
- `tests/unit/test_make_test_config.py:16,32` — `config.token == TEST_TOKEN`.
- `tests/unit/test_config_token_optional.py:36,49` — `== "env-token-value"` / `== "ha-token-value"`.
- `tests/unit/cli/test_commands_run.py:63` — `config.token == "test-token"`.
- `tests/integration/test_websocket_service.py:247` — passes `config.token` as the `access_token` dict
  value that the test then asserts on.

**Snapshot:** `test_utils/harness.py:181` `preserve_config` — snapshot via `config.model_copy(deep=True)`
instead of `model_dump()`: a deep copy preserves the `SecretStr` object and structurally removes the risk
of restoring a masked value under `validate_assignment=True` (`config.py:62`).

**Regression guard:** the existing `truncated_token` tests (`tests/unit/test_config.py:525-552`) must
still pass unchanged — they pin that the migrated `truncated_token` produces the same masked strings
(`"<not set>"`, `"***"`, `"abc***"`, `"abcdef...ghijkl"`).

### Field descriptions on nested groups

`use_attribute_docstrings=True` is set on `HassetteConfig` but **not** on the nested-group models, so
their fields generate no schema `description` — `database.retention_days` and ~90 sibling fields render
with a title but no help text. (This is the same gap that slipped through the earlier config-split work.)
Fix it at the shared base: enable `use_attribute_docstrings=True` for the nested groups via their common
`ExcludeExtrasMixin` (`config/classes.py:75`) so all nine groups inherit it — falling back to per-model
config if mixin propagation doesn't take. Do the same on the `AppConfig` base (`app/app_config.py:10`) so
app authors' field docstrings become help text for free too. Verify with a schema test asserting a
nested field (e.g. `database.retention_days`) carries a non-empty `description`.

### Frontend: one schema renderer for both surfaces

Generalize the app tab's `SchemaConfigTable` + `ConfigValue` (`config-tab.tsx:37-160`) into a shared
component (e.g. `components/shared/config-schema-view.tsx`) consuming `{schema, values}`. Both
`pages/config.tsx` and `config-tab.tsx` render through it. `config.tsx`'s hand-written `groups` array is
removed; grouping comes from the schema's nested-object structure.

**Quality bar (prose; the mockup is deferred to the first build step).** The renderer must be a net
improvement over today's curated `config.tsx`, not a JSON blob:

- **Labels** from `ui.label` when set, else the humanized field name; `description` (the docstring) as
  help text — not raw snake_case keys alone.
- **Grouped sections** mirroring the nested-model structure (one section per group: database, websocket,
  …), titled by `ui.group_label` when set, with flat top-level fields under a "core"/"general" section,
  ordered by `ui.order` then declaration order.
- **Type-driven value formatting:** booleans as a badge/toggle, `Path` as code, enums as a badge,
  durations humanized, lists/tuples expanded, nested objects via the existing expand affordance —
  overridable per field by `ui.widget`.
- **Masked secrets** rendered as a distinct muted placeholder (e.g. `••••••••`), visually marked as a
  secret, with "not set" when unset.

The renderer reads each `ui` hint with a schema-derived fallback (so an un-annotated field still renders
well) and **ignores `ui.tier`** in MVP — no field sets it and there is no show-advanced affordance yet.
The first build task produces an HTML mockup of the full `HassetteConfig` render against this bar before
the renderer is locked.

### Schema export and freshness

The `ConfigSchemaResponse` envelope is a typed response model, so its *shape* flows through
`scripts/export_schemas.py` → `openapi.json` → `generated-types.ts` and the freshness check. The schema
*content* — including the `ui` metadata — rides inside a `dict[str, Any]` field, so the OpenAPI freshness
check does **not** see it: a field's `ui` block can change or break without the generated types drifting.
Because the `ui` mechanism ships in MVP, this gap is live now, not deferred. Close it with a dedicated
unit test that builds the config view and asserts every `ui` block matches the expected schema (allowed
keys, value types, `tier` only ever `common`/`advanced`). Document that the OpenAPI check does not cover
`ui` annotations. This test is MVP scope.

## Replacement Targets

- **`config_response_from`** (`web/mappers.py:209-255`) and the **`*ConfigResponse` classes** +
  **`ConfigResponse`** (`web/models.py:405-470`) → replaced by direct `HassetteConfig.model_json_schema()`
  exposure through the shared view builder and a `ConfigSchemaResponse` envelope. **Remove outright.**
- **`_SECRET_KEYS` regex, `_redact_dict`, `_redact_secrets`** (`web/routes/apps.py:23-33`) → replaced by
  schema-driven masking in the shared view builder. **Remove outright.**
- **`pages/config.tsx` `groups` array** (`config.tsx:36-101`) and its `formatValue` curation → replaced
  by the shared schema renderer. **Remove/rewrite.**
- **`cmd_config`** (`cli/commands/misc.py`) consuming the deleted `ConfigResponse` → **migrate** to
  validate `ConfigSchemaResponse` and render `config_values` (see Architecture → CLI consumer). The test
  helper **`make_config_response`** (`test_utils/web_helpers.py:385`) builds the deleted model →
  **remove/rework** to the new shape.
- **`render_detail`** (`cli/output.py:237`, `BaseModel`-only) → **migrate** by extracting its rendering
  body into a dict-capable helper so `cmd_config` can render the plain `config_values` dict (additive; the
  existing model path stays for other callers).
- **`SchemaConfigTable` / `ConfigValue`** (`config-tab.tsx:37-160`) → **migrate** into the shared
  component (generalized, not duplicated); `config-tab.tsx` becomes a thin caller.
- **`preserve_config` `model_dump()` snapshot** (`harness.py:181`, call site at `:186`) → **migrate** to
  `model_copy(deep=True)`.
- **`truncated_token` manual slicing** (`config.py:243-251`) → **migrate** to operate on
  `.get_secret_value()` (kept, not replaced).

## Migration

No persisted-data migration — config is loaded fresh each run. The one migration is a **type change**:
`HassetteConfig.token: str | None` → `SecretStr | None`, plus the documented behavior change that app
config secrets are now masked by type rather than name.

- **What changes for app authors:** a secret field previously masked because its *name* matched
  `(token|password|secret|api_key|apikey|credential)` is no longer masked unless it is typed `SecretStr`.
  Conversely, a `SecretStr` field with any name is now masked.
- **Reversible:** revert the type change and restore the regex helper. No data is transformed.
- **Breaking-change note required:** ship a `BREAKING CHANGE:` footer documenting the `str`→`SecretStr`
  expectation for secret fields, regardless of the "no external users yet" inference.

## Convention Examples

### Schema-driven generic rendering (the pattern to generalize)

**Source:** `frontend/src/components/app-detail/config-tab.tsx`

```tsx
function SchemaConfigTable({ config, schema }: { config: ConfigRecord; schema: ConfigSchema }) {
  const properties = schema.properties ?? {};
  const propKeys = Object.keys(properties);
  const extraKeys = Object.keys(config).filter((k) => !propKeys.includes(k));
  const allKeys = [...propKeys, ...extraKeys];
  // ...renders Key / Type / Value rows from (schema.properties, config values)
}
```

This is the existing proof that schema-driven generic rendering works in-repo. The shared component
generalizes it and adds `$ref` resolution (done server-side) and secret masking.

### Unified `{schema, values}` endpoint shape (the convention to match)

**Source:** `src/hassette/web/routes/apps.py`

```python
@router.get("/apps/{app_key}/config", response_model=AppConfigResponse)
async def get_app_config(app_key: str, hassette: HassetteDep) -> AppConfigResponse:
    schema = type(app_instance).app_config_cls.model_json_schema()
    return AppConfigResponse(
        app_key=app_key, filename=manifest.filename, class_name=manifest.class_name,
        enabled=manifest.enabled, app_config=_redact_secrets(manifest.app_config), config_schema=schema,
    )
```

The global endpoint adopts the same schema+values shape (minus the regex redaction, plus deref).

### Pydantic field with attribute docstring → schema description

**Source:** `src/hassette/config/models.py`

```python
class DatabaseConfig(ExcludeExtrasMixin, BaseModel):
    retention_days: int = Field(default=7, ge=1)
    """Number of days to retain execution records in the ``executions`` table."""
```

With `use_attribute_docstrings=True`, this docstring becomes the field's schema `description` — so help
text needs no extra metadata, and the label defaults to the humanized field name. The `ui` namespace
(below) overrides the label only where that default reads poorly. **Note:** the nested groups don't have
this flag set today — enabling it is part of this change (see Architecture → Field descriptions on nested
groups).

### Endpoint integration test (the convention for the new AC tests)

**Source:** `tests/integration/web_api/test_endpoints.py`

```python
async def test_token_not_in_response(self, client: "AsyncClient", mock_hassette) -> None:
    response = await client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "token" not in data
```

This exact test **inverts** under the new design (token present-but-masked; assert the plaintext is
absent, not the key).

## Alternatives Considered

- **Preserve the current global wire shape, add visibility metadata (research brief Option A).** Rejected:
  the user explicitly dislikes the current presentation, so anchoring on it is the wrong target. Show-all
  dissolves the "response restructures the source" obstacle entirely.
- **Defer the entire `ui` metadata mechanism (mechanism + tier values together).** Rejected: deciding
  `common`/`advanced` per field is judgment work worth deferring, but the `ui` *plumbing* is mechanical
  and touches the same files this change rewrites — deferring it forces the fast-follow to re-open them.
  So the split is mechanism-now / tier-decisions-later. The opposite extreme — **keep full tiering in
  MVP** — is also rejected: it front-loads ~90 common-vs-advanced decisions the user explicitly wants to
  defer.
- **A third-party schema renderer (RJSF / JSONForms / json-viewer) via `preact/compat`.** Rejected after
  a build-vs-reuse survey (recorded in `brief.md`). `preact/compat` *would* load them, but form engines' "read-only" is
  disabled inputs (not text display), schema-viewers impose their own design system, and Web-Component
  value-viewers wall off the CSS-Modules tokens behind Shadow DOM and render raw JSON keys. No library
  delivers labels + grouping + masking + the design system together; a ~100–200-line custom renderer is
  smaller and the only way to get all four. Escape hatch: re-evaluate JSONForms-via-compat *if* editing
  is ever un-deferred.
- **Hand-roll the deref.** Rejected: `$ref` inlining has real edge cases (cycles, sibling keys, `$defs`
  at depth, discriminator mappings) that `jsonref` has already solved. Reinventing them invites the same
  bugs for no benefit; the dependency pays for itself.
- **Do nothing.** Rejected: the global page stays incomplete and disliked, and the name-regex keeps
  giving false confidence about secret coverage.

## Test Strategy

Sequenced as a proof sequence: the `SecretStr` migration lands first (it can silently break real auth),
verified on system/e2e, before the presentation refactor builds on it.

### Existing Tests to Adapt

- `tests/integration/web_api/test_endpoints.py` — `test_token_not_in_response` **inverts**: assert the
  plaintext token is absent but the masked `token` key is present. Adapt the other config-shape tests
  (`test_response_has_nested_groups`, `test_dir_fields_present_as_strings`, `test_get_config`) to the new
  `{config_schema, config_values}` envelope and the now-present `database`/`websocket`/`blocking_io`
  groups.
- **Token `== str` comparison sites** — all the "Test sites" listed in Architecture
  (`test_utils/mock_hassette.py:89`, `tests/unit/test_make_test_config.py:16,32`,
  `tests/unit/test_config_token_optional.py:36,49`, `tests/unit/cli/test_commands_run.py:63`,
  `tests/integration/test_websocket_service.py:247`) break because `SecretStr(...) == "<str>"` is `False`.
  Update each to compare `.get_secret_value()` or use `SecretStr` fixtures. These break at unit-test
  time, not only system/e2e — do not defer them.
- `frontend/src/components/app-detail/config-tab.test.tsx:14,48` — fixture `token: "supersecret123"`
  asserts the **plaintext** renders; rewrite to assert the masked placeholder.
- `frontend/src/pages/config.test.tsx` (10 tests) — rewrite against the shared renderer and the new
  endpoint shape; the hand-curated group assertions no longer apply.
- `frontend/src/test/factories.ts:289` `createSystemConfig` and `frontend/src/test/handlers.ts:174` —
  build the old `ConfigResponse` shape; rework to produce the `{config_schema, config_values}` envelope.
- `tests/unit/cli/test_commands_misc.py` and `tests/unit/cli/test_commands_app.py` — assert against the
  old `ConfigResponse` / `AppConfigResponse` rendering; update for the new envelope (misc) and
  schema-masked values (app), along with the `make_config_response` / `make_app_config_response` helpers.
- `tests/integration/test_hot_reload.py` and `tests/integration/test_service_watcher.py` — exercise
  `preserve_config`; confirm they still pass after the `model_copy(deep=True)` change.
- `tests/unit/test_config.py:525-552` — `truncated_token` regression guard; must keep passing unchanged.
- `tests/system/test_cli_smoke.py` — `test_config_deserializes` imports the deleted `ConfigResponse` and
  asserts `isinstance(result, ConfigResponse)`; adapt to `ConfigSchemaResponse` (import break otherwise).
- `tests/system/test_web_api.py` — `test_config_endpoint` asserts top-level `web_api`/`logging` keys;
  adapt to the new envelope (those keys now live under `config_values`).
- `tests/e2e/test_config.py` — asserts the deleted curated section names (`general`, `connection`,
  `buffers`, `timeouts`, `paths`) and renamed keys (`app_dir`); rewrite for the schema-driven group names
  and real field paths.

### New Test Coverage

- **Unit (backend):** schema-driven masking masks a `SecretStr` field and leaves an untyped `str` field
  unmasked, on both a live-model dump and a raw dict, recursing into nested objects (FR#3, FR#4).
- **Unit (backend):** `$ref`/`$defs` deref inlines nested groups with no `$ref` remaining and terminates
  on cycles (FR#5).
- **Integration:** `GET /api/config` includes `database`, `websocket`, `blocking_io` and masks `token`
  (AC#1, AC#3); both endpoints return the deref'd envelope (AC#2).
- **Integration:** `preserve_config` round-trips a `SecretStr` token without poisoning (AC#8).
- **System (`nox -s system`):** a live Hassette authenticates over REST + WebSocket with the `SecretStr`
  token (AC#7) — the boundary unit tests mock.
- **E2E (`nox -s e2e`):** the Config page and an app Config tab render via the shared component, showing
  masked secrets and previously-hidden groups (AC#9).
- **Frontend (unit):** the shared renderer formats by type, groups by nested structure, masks secrets,
  and applies each active `ui` hint — `label`, `group_label`, `order`, `widget` — with a schema-derived
  fallback when the hint is absent (FR#6, FR#7, FR#8, FR#9, FR#11).
- **Unit (backend):** the `ui` namespace round-trips — a field's `json_schema_extra={"ui": {...}}` survives
  `model_json_schema()` + deref into the built view; and the metadata-shape test asserts every `ui` block
  uses only allowed keys with correct value types and never sets `tier` outside `common`/`advanced`
  (AC#10, FR#11). This is the freshness gap the OpenAPI check does not cover.
- **Unit (backend):** a nested-group field carries a non-empty `description` in the served schema — e.g.
  `database.retention_days` — confirming the `use_attribute_docstrings` fix on the nested-group base
  (AC#12, FR#7).
- **Unit (CLI):** `cmd_config` renders the new `ConfigSchemaResponse` envelope's `config_values` (human
  and `--json`), shows previously-omitted groups, and masks `token` (AC#11, FR#12). Update
  `tests/unit/cli/test_commands_misc.py` and the `make_config_response` helper to the new shape.

### Tests to Remove

- Any assertion tied specifically to the deleted `*ConfigResponse` shape or the `_SECRET_KEYS` regex
  (e.g. a test asserting a `password`-named field is masked by name) is removed, not adapted — that
  behavior is intentionally gone.
- `tests/unit/web/test_mappers.py` — the `config_response_from` tests (≈ lines 542-582) and their
  `config_response_from`/`ConfigResponse` imports are removed with the function.

## Documentation Updates

- **Docs site — web UI / config page:** update the page documenting the Config view to describe show-all,
  grouped sections, and masked secrets. Regenerate `docs/_static/web_ui_config.png` via
  `scripts/capture_screenshots.py --only web_ui_config` and capture the app Config tab if documented.
- **App-author docs (AppConfig / secrets):** document that secret fields should be typed `SecretStr` to be
  auto-masked in the dashboard, that name-based masking is gone, and that authors can set `ui` metadata
  (`label`, `group_label`, `order`, `widget`) on their `AppConfig` fields to control how they render —
  the same mechanism the framework's own config uses. Note that `ui.tier` is **reserved** (must be
  `common`/`advanced`, has no effect yet) so authors don't repurpose the key before the tiering fast-follow.
- **Freshness-check limitation:** record — in a comment on the `ui` metadata-shape unit test and the
  `config_view` builder — that the OpenAPI freshness check does **not** cover `ui` annotation content (it
  rides in a `dict[str, Any]`), so that test is the sole guard against `ui`-shape drift.
- **Docstrings:** `token` field docstring notes it is a `SecretStr`; `truncated_token` / `auth_headers`
  docstrings note they unwrap via `get_secret_value()`.
- **CHANGELOG via commit/PR title:** `feat!:` with a `BREAKING CHANGE:` footer for the `str`→`SecretStr`
  secret-masking change. Do not hand-edit `CHANGELOG.md` (release-please owns it).

## Impact

### Changed Files

Shared / cross-cutting (higher risk) first:

- `src/hassette/config/config.py` — **modify** — `token: SecretStr | None`; `auth_headers` +
  `truncated_token` unwrap via `get_secret_value()`.
- `src/hassette/web/config_view.py` — **create** — shared deref (`jsonref`) + schema-driven masking view
  builder.
- `pyproject.toml` — **modify** — add the `jsonref` runtime dependency.
- `src/hassette/web/models.py` — **modify** — delete `ConfigResponse` + all `*ConfigResponse` classes;
  add `ConfigSchemaResponse` envelope.
- `src/hassette/web/mappers.py` — **modify** — delete `config_response_from`.
- `src/hassette/web/routes/config.py` — **modify** — return the unified view from `model_json_schema()` +
  `model_dump(mode="json")`.
- `src/hassette/config/config.py` and `src/hassette/config/models.py` — **modify** — add `ui` metadata
  (`json_schema_extra`) to the handful of fields/groups whose default label renders poorly (acronyms,
  multi-word group titles); most fields get nothing. (Same `config.py` file as the `SecretStr` change.)
- `src/hassette/config/classes.py` — **modify** — enable `use_attribute_docstrings=True` on
  `ExcludeExtrasMixin` so all nested groups get field descriptions.
- `src/hassette/app/app_config.py` — **modify** — enable `use_attribute_docstrings=True` on `AppConfig`
  so app-author field docstrings become descriptions.
- `src/hassette/web/routes/apps.py` — **modify** — remove `_SECRET_KEYS`/`_redact_dict`/`_redact_secrets`;
  build the view via the shared builder.
- `src/hassette/cli/commands/misc.py` — **modify** — `cmd_config` validates `ConfigSchemaResponse` and
  renders `config_values` via the dict-capable detail helper.
- `src/hassette/cli/output.py` — **modify** — extract `render_detail`'s body into a dict-capable helper
  (additive).
- `src/hassette/core/websocket_service.py` — **modify** — `access_token` via `get_secret_value()`.
- `src/hassette/test_utils/harness.py` — **modify** — `preserve_config` → `model_copy(deep=True)`.
- `src/hassette/test_utils/mock_hassette.py` — **modify** — token fixture/comparison for `SecretStr`.
- `src/hassette/test_utils/web_helpers.py` — **modify** — rework/remove `make_config_response` (builds the
  deleted `ConfigResponse`); confirm `make_app_config_response` still matches `AppConfigResponse`.
- `frontend/src/components/shared/config-schema-view.tsx` — **create** — shared renderer.
- `frontend/src/components/app-detail/config-tab.tsx` — **modify** — call the shared renderer.
- `frontend/src/pages/config.tsx` — **modify** — remove curated groups; call the shared renderer.
- `frontend/src/api/endpoints.ts` — **modify** — `getConfig` return type → new envelope.
- `frontend/src/api/generated-types.ts`, `frontend/openapi.json` — **regenerate** — via
  `scripts/export_schemas.py --types`.
- Test files per Test Strategy — **modify/create**.
- `docs/` config page + `docs/_static/web_ui_config.png` — **modify/regenerate**.

<!-- Gap check 2026-06-25: 3 reverse-dependency gaps found and included — CLI hassette config
(cli/commands/misc.py:13, consumes deleted ConfigResponse) → T03; make_config_response helper
(test_utils/web_helpers.py:385) + tests/unit/cli/test_commands_misc.py → T03; frontend test infra
(test/factories.ts:289 createSystemConfig, test/handlers.ts:174) → T06. Lower-risk, noted not gapped:
cli/commands/app.py (AppConfigResponse shape preserved) → T04 Focus; cli/output.py:320 docstring example
(no change). -->


### Behavioral Invariants

- Real HA REST + WebSocket authentication must keep working (FR#10) — the migration's central risk.
- The plaintext token must never appear in any API response (tightened, not relaxed: previously absent,
  now present-but-masked).
- The app config multi-instance (list) rendering path keeps working.
- The `hassette config` CLI command and the `hassette app config` CLI command keep working (the former
  migrates to the new envelope; the latter relies on `AppConfigResponse`'s shape staying stable).
- The schema-export freshness checks (`tools/check_schemas_fresh.py`, CI git-diff on generated TS) stay
  green.

### Blast Radius

- **HA connection layer** — `auth_headers`, `truncated_token`, WS auth all read the token; a botched
  `SecretStr` unwrap breaks the live connection while unit tests pass.
- **Both config UI surfaces** change rendered output → triggers the visual-evidence requirement
  (`design-completeness.md`, `tools/frontend/check_pr_screenshots.py`); regenerate the doc screenshot.
- **CLI** — `hassette config` consumes the deleted `ConfigResponse` and must migrate; `hassette app
  config` validates `AppConfigResponse` (shape preserved, values now schema-masked). Their tests
  (`tests/unit/cli/test_commands_misc.py`, `test_commands_app.py`) and the `make_config_response` /
  `make_app_config_response` helpers in `test_utils/web_helpers.py` need updating.
- **Test harness** — `preserve_config` is used by module-scoped reuse tests; the snapshot change touches
  any test relying on it.
- **App authors** (external, unconfirmed) — secret fields stop being masked by name; `SecretStr` typing
  becomes the contract.

## Open Questions

None. Resolution of the brief's Open Questions:

- **Metadata key shape** — settled: a single `json_schema_extra` `ui` namespace with `label`,
  `group_label`, `order`, `widget`, and a reserved-but-unused `tier` key.
- **Schema round-trip of `ui` metadata** — in MVP scope; the metadata-shape unit test covers the gap the
  OpenAPI freshness check leaves.
- **Tier taxonomy / tier map** — deferred (the judgment work); `tier` is `common`/`advanced` in the
  shape, populated in the fast-follow.
- **Grouping** = nested-class structure (with `ui.group_label` overrides). **Value formatting**,
  **frontend placement**, **`SecretStr` blast radius**, and the **internal-fields** question are all
  settled above.
