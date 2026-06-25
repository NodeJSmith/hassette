# Context: Unified Config Presentation in the Web UI

## Problem & Motivation

Hassette surfaces configuration to the web UI through two divergent code paths. The global config
(`/api/config` → `pages/config.tsx`) is hand-maintained: `config_response_from` copies ~27 of ~90 fields
into parallel response classes, restructures them, and silently drops whole groups (`database`,
`websocket`, `blocking_io`). The user dislikes this incomplete, opinionated view. The app config
(`/api/apps/{key}/config` → `config-tab.tsx`) already renders generically from a JSON schema, but redacts
secrets with a field-name regex (`_SECRET_KEYS`) that is security theatre — it misses innocuously-named
secrets and only recurses one level. The goal: unify both surfaces on one mechanism (a JSON schema +
values, rendered by one component), replace all secret handling with a single type-driven rule
(`SecretStr` is masked, nothing is masked by name), and ship the `ui` presentation-metadata mechanism so
field-level metadata (#690's ask) lands and the later tiering work is a pure data change.

## Visual Artifacts

None yet. The first frontend task (T06) produces an HTML mockup of the full `HassetteConfig` render to
set the renderer's quality bar before the component is locked. No mockup exists at planning time.

## Key Decisions

1. **Read-only, show-all.** Every config field is exposed (no curation, no omission). Editing, reveal-secret,
   and web-API auth are explicitly out of scope.
2. **One config-view builder.** A shared backend helper (`web/config_view.py`) takes a schema + values and
   returns `{config_schema (deref'd), config_values (masked)}`. Both endpoints call it.
3. **Server-side `$ref` deref via `jsonref`.** `jsonref.replace_refs()` inlines `$defs`/`$ref` so the
   frontend never walks a ref. A library, not a hand-roll — `$ref` edge cases (cycles, sibling keys) are
   already solved. New dependency in `pyproject.toml`.
4. **Type-driven masking.** Mask fields the schema marks `writeOnly: true` / `format: "password"` (i.e.
   `SecretStr`-typed). Applied uniformly to both surfaces. Accepted tradeoff: an untyped `api_key: str` is
   no longer masked — secrets must be typed `SecretStr`.
5. **`SecretStr` migration sequenced first.** `HassetteConfig.token` → `SecretStr | None`. This can
   silently break real HA auth while unit tests (which mock the boundary) stay green, so it lands first and
   is verified on `nox -s system`/`e2e`.
6. **`ui` metadata mechanism ships; tier values do not.** Fields declare presentation metadata via a
   `json_schema_extra` `ui` namespace (`label`, `group_label`, `order`, `widget`). The `tier` key is part
   of the shape but unset on every field and ignored by the renderer — populating it (the ~90
   common/advanced judgment calls) and the "show advanced" affordance are the deferred fast-follow.
7. **Delete the legacy global path.** `config_response_from`, the `*ConfigResponse` classes, and
   `config.tsx`'s hand-written groups are removed, not kept alongside the new path.
8. **The CLI consumes the global endpoint too.** `hassette config` (`cli/commands/misc.py` → `cmd_config`)
   validates the deleted `ConfigResponse` today. It migrates to validate the new `ConfigSchemaResponse`
   envelope and render `config_values` via a dict-capable helper extracted from `render_detail`
   (`cli/output.py`). Result: `hassette config` now shows the complete config (all groups), `token`
   masked. `hassette app config` keeps working — `AppConfigResponse`'s shape is preserved.
9. **Nested-group fields need `use_attribute_docstrings`.** It is set on `HassetteConfig` but NOT on the
   nested-group models (which inherit `ExcludeExtrasMixin`) or on `AppConfig` — so ~90 nested fields and
   all app-author fields generate no schema `description` (no help text). Enable it on `ExcludeExtrasMixin`
   (`config/classes.py:75`) and `AppConfig` (`app/app_config.py:10`). This is the same gap that slipped
   through the earlier config-split PR. Verify with a schema test asserting `database.retention_days`
   carries a non-empty `description`.

## Payload shape ({config_schema, config_values})

Both endpoints return two parallel structures. `config_schema` is the `model_json_schema()` output
(deref'd) — structure + metadata (types, titles, descriptions-from-docstrings, secret markers, `ui`
hints); derived from the class, identical for every instance. `config_values` is `model_dump(mode="json")`
(global) or the raw TOML dict (app) — the current values, masked; derived from the instance. The renderer
joins them by walking `config_schema.properties` and looking up each key in `config_values`, recursing
into nested groups in lockstep. Schema = template (what to draw and how); values = data (what to fill in).
They are kept separate because they are two different Pydantic outputs, it matches the existing app-config
endpoint, and it keeps the values a plain dict the CLI can render directly. **Field names differ by
endpoint:** the global `/api/config` returns `{config_schema, config_values}`; the app
`/api/apps/{key}/config` keeps its existing `AppConfigResponse` shape with `config_schema` + **`app_config`**
(not `config_values`). Assert the right field name per endpoint.

## Constraints & Anti-Patterns

- **No field-name secret matching.** The `_SECRET_KEYS` regex must not be reintroduced in any form. Masking
  is type-driven only.
- **Plaintext token must never reach the wire.** Masking failures are a security regression. The masked
  path is the only path — no reveal in MVP.
- **Ship the metadata mechanism, not the tier decisions.** Do not set `ui.tier` on any field, do not build
  a show-advanced affordance, do not collapse/hide by tier. Do not annotate all ~90 fields — add `ui` hints
  only where the schema-derived default renders poorly.
- **Do not preserve the current global wire shape.** No compatibility shim that re-flattens or re-curates.
- **Out of scope (do not implement):** relevance tier values + show-advanced affordance, reveal-secret
  button, web API authentication, config editing / write-back.

## Design Doc References

- `## Problem` / `## Goals` — what's broken and what success looks like.
- `## Architecture` — the three layers (view builder, endpoint adapters, frontend renderer), the `SecretStr`
  migration (with the verified blast-radius), the `ui` metadata mechanism, and schema-export/freshness.
- `## Replacement Targets` — exactly what code is deleted vs migrated.
- `## Migration` — the `str`→`SecretStr` type change and the breaking-change note.
- `## Test Strategy` — existing tests to adapt (with paths), new coverage mapped to FRs, tests to remove.
- `## Impact` — changed files, behavioral invariants (HA auth must keep working), blast radius.

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
generalizes it and adds `ui`-hint consumption and secret masking. (Deref is done server-side, so the
component receives a fully-inlined schema.)

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

The global endpoint adopts the same schema+values shape (minus the regex redaction, plus deref + the
shared builder).

### Pydantic field with attribute docstring → schema description

**Source:** `src/hassette/config/models.py`

```python
class DatabaseConfig(ExcludeExtrasMixin, BaseModel):
    retention_days: int = Field(default=7, ge=1)
    """Number of days to retain execution records in the ``executions`` table."""
```

With `use_attribute_docstrings=True`, this docstring becomes the field's schema `description` — so help
text needs no extra metadata, and the label defaults to the humanized field name. A `ui` override looks
like `Field(default=..., json_schema_extra={"ui": {"label": "Web API Port"}})`.

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
