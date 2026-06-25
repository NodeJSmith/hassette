---
task_id: "T06"
title: "Shared frontend config renderer, both pages, ui consumption, docs"
status: "planned"
depends_on: ["T03", "T04", "T05"]
implements: ["FR#6", "FR#7", "FR#8", "FR#9", "FR#11", "AC#6", "AC#9", "AC#10"]
---

## Summary
Build the one generic, read-only renderer that serves both the global Config page and the app Config tab,
consuming `{config_schema, config_values}`. Generalize the app tab's existing `SchemaConfigTable` into a
shared component that derives labels (from `ui.label` / humanized name + docstring help text), groups by
nested structure (titled by `ui.group_label`, ordered by `ui.order`), formats values by type (overridable
by `ui.widget`), and shows masked secrets distinctly. Rewire both pages, regenerate frontend types, fix
the frontend test infrastructure, and update the docs + screenshots. Start with an HTML mockup to set the
quality bar before locking the component.

## Target Files
- create: `frontend/src/components/shared/config-schema-view.tsx` — the shared renderer (+ co-located
  `.module.css` if needed).
- modify: `frontend/src/components/app-detail/config-tab.tsx` — call the shared renderer.
- modify: `frontend/src/pages/config.tsx` — remove the hand-written `groups` array; call the shared renderer.
- modify: `frontend/src/api/endpoints.ts` — `getConfig` return type → the new envelope; `SystemConfig` type.
- regenerate: `frontend/src/api/generated-types.ts`, `frontend/openapi.json` — via
  `uv run python scripts/export_schemas.py --types`.
- modify: `frontend/src/test/factories.ts` (`createSystemConfig`), `frontend/src/test/handlers.ts` — new envelope.
- modify: `frontend/src/pages/config.test.tsx`, `frontend/src/components/app-detail/config-tab.test.tsx`.
- modify: `tests/e2e/test_config.py` — its section assertions (`general`/`connection`/`paths`/`timeouts`
  and renamed keys like `app_dir`) are tied to the deleted hand-curated grouping; rewrite them for the
  new schema-driven sections (nested-model group names: `database`, `websocket`, `web_api`, `logging`,
  `lifecycle`, …; `app_dir` is now `directory` under the apps group).
- modify: `docs/` config page (web UI) + app-author docs (SecretStr, `ui` metadata, `tier` reserved).
- regenerate: `docs/_static/web_ui_config.png` — via `scripts/capture_screenshots.py --only web_ui_config`.
- read: `design/specs/086-unified-config-presentation/design.md` (`## Architecture → Frontend`, quality bar).

## Prompt
Implement the frontend renderer + docs per the design doc's `## Architecture → Frontend: one schema
renderer for both surfaces` (including the **Quality bar**) and `## Documentation Updates`.

This is a worktree — run `cd frontend && npm install` once before building (worktrees don't share
`node_modules`).

1. **Mockup first.** Produce an HTML mockup of the full `HassetteConfig` render against the quality bar
   (grouped sections, labels from docstrings, masked secrets, type-formatted values). Use it to set the
   bar before locking the component. Save it under the feature dir or `/tmp` and reference it in the PR.
2. **Shared renderer** `components/shared/config-schema-view.tsx`: consume `{schema, values}`. Generalize
   the existing `SchemaConfigTable` + `ConfigValue` from `config-tab.tsx`. The schema arrives fully
   deref'd (no `$ref` to walk — server-side). Apply each `ui` hint with a schema-derived fallback:
   `ui.label` else humanized field name; `description` as help text; sections by nested-object structure
   titled by `ui.group_label`, ordered by `ui.order` then declaration order; type-driven value formatting
   (bool badge/toggle, `Path` as code, enum badge, duration humanized, lists expanded, nested objects via
   the expand affordance) overridable by `ui.widget`; masked secrets as a distinct muted placeholder with
   "not set" when unset. **Ignore `ui.tier`** — no field sets it, no collapse/show-advanced affordance.
3. **Wire both pages:** `config-tab.tsx` becomes a thin caller; `pages/config.tsx` drops its `groups`
   array and `formatValue`, fetches the new envelope, and renders through the shared component.
4. **Types:** update `endpoints.ts` `getConfig`/`SystemConfig` to the new envelope, then regenerate with
   `uv run python scripts/export_schemas.py --types` and `cd frontend && npm run build` to verify.
5. **Frontend tests:** rework `test/factories.ts` `createSystemConfig` and `test/handlers.ts` to the new
   envelope; rewrite `config.test.tsx` against the shared renderer; rewrite `config-tab.test.tsx:14,48`
   (fixture `token: "supersecret123"`) to assert the masked placeholder, not plaintext. Run
   `cd frontend && npm test`.
6. **E2E tests:** rewrite `tests/e2e/test_config.py` — it asserts the deleted curated section names
   (`general`/`connection`/`buffers`/`timeouts`/`paths`) and curated keys (`app_dir`); update to the
   schema-driven group names and real field paths. Run via `uv run nox -s e2e` (or rely on CI).
7. **Docs:** update the web UI config docs page (show-all, grouped sections, masked secrets) and
   app-author docs (type secrets as `SecretStr`; name-based masking is gone; `ui` metadata keys; `ui.tier`
   is reserved/unused). Regenerate `docs/_static/web_ui_config.png` with
   `scripts/capture_screenshots.py --only web_ui_config`.

## Focus
The schema is deref'd server-side, so the renderer never handles `$ref` (the current `resolveType` only
handles `anyOf`). The renderer must be a net improvement over the curated `config.tsx`, not a JSON blob —
that's the F5 risk the mockup de-risks. Follow the CSS-module conventions in CLAUDE.md (co-located
`.module.css`, `clsx`, `:global()` for shared classes, no bare `ht-*` in module CSS). A PR touching
`frontend/src/**/*.tsx`/`*.css` needs visual evidence (`tools/frontend/check_pr_screenshots.py`) — the
regenerated screenshot satisfies it. Use the shared `Badge`/`Card`/`Chip` components rather than raw
`ht-*` class strings. Preserve the page title (`useDocumentTitle("Config")` → "Config - Hassette") and the
`config-page` / `nav-config` testids so `tests/e2e/test_navigation.py` stays green (it asserts the title
and that the page loads); only the section/key assertions in `tests/e2e/test_config.py` change.

## Verify
- [ ] FR#6: the global Config page and the app Config tab render through the same shared component.
- [ ] FR#7: labels come from `ui.label` when set, else the humanized name; help text from `description`
  (including nested-group fields, per T05's fix).
- [ ] FR#8: fields are grouped into sections by nested-model structure, titled by `ui.group_label` when set.
- [ ] FR#9: values are formatted by type (bool, path, enum, duration, list, nested), overridable by `ui.widget`.
- [ ] FR#11: the renderer applies each active `ui` hint (`label`/`group_label`/`order`/`widget`) when
  present and falls back to a schema-derived default when absent; `ui.tier` is ignored (no collapsing).
- [ ] AC#6 (frontend half): `pages/config.tsx` no longer contains a hand-written `groups` array.
- [ ] AC#9: both surfaces render via the shared component; the Config page shows the previously-hidden
  `database`, `websocket`, `blocking_io` groups (verified via the regenerated screenshot / e2e). An HTML
  mockup was produced first (per the Prompt) to set the quality bar before the component was locked.
- [ ] AC#10: a `ui.label` override renders; an un-annotated field falls back to the humanized name; the
  other active hints (`group_label`, `order`, `widget`) take effect with fallbacks (frontend unit test).
