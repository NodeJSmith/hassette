---
task_id: "T05"
title: "ui metadata mechanism + nested-group field descriptions"
status: "planned"
depends_on: ["T02"]
implements: ["FR#11", "AC#10", "AC#12"]
---

## Summary
Ship the backend half of the `ui` presentation-metadata mechanism and fix the nested-group description
gap. Fields declare optional presentation metadata via a `json_schema_extra` `ui` namespace
(`label`, `group_label`, `order`, `widget`, plus a reserved-but-unused `tier`). Enable
`use_attribute_docstrings=True` on the nested-group base and `AppConfig` so their field docstrings become
schema descriptions (today only top-level `HassetteConfig` fields get them). Add the metadata-shape test
that guards the `ui` namespace — the freshness gap the OpenAPI check does not cover.

## Target Files
- modify: `src/hassette/config/classes.py` — `use_attribute_docstrings=True` on `ExcludeExtrasMixin`.
- modify: `src/hassette/app/app_config.py` — `use_attribute_docstrings=True` on `AppConfig`.
- modify: `src/hassette/config/config.py` and `src/hassette/config/models.py` — add `ui` metadata
  (`json_schema_extra`) to the handful of fields/groups whose default label renders poorly.
- create: `tests/unit/web/test_config_metadata.py` — `ui` round-trip + shape test + nested-description test.
- read: `src/hassette/web/config_view.py` (T02 — deref must preserve `ui`).

## Prompt
Implement per the design doc's `## Architecture → The ui presentation-metadata mechanism` and `## Architecture
→ Field descriptions on nested groups`.

1. **Descriptions fix.** Enable `use_attribute_docstrings=True` on `ExcludeExtrasMixin`
   (`config/classes.py:75`) by giving it `model_config = ConfigDict(use_attribute_docstrings=True)` —
   `ConfigDict` is already imported in that file. All nine nested groups inherit `ExcludeExtrasMixin`, so
   they pick it up. Also set it on `AppConfig`'s `model_config` (`app/app_config.py`). If mixin
   propagation does not take for some group, fall back to setting the flag on each group's `model_config`.
2. **`ui` namespace.** Add `ui` presentation metadata via `json_schema_extra={"ui": {...}}` only on the
   fields/groups whose default render is poor — chiefly `label`/`group_label` for acronyms and multi-word
   names the humanizer can't infer (e.g. "Web API", "CORS Origins", "Blocking I/O"). Do NOT annotate all
   fields, and do NOT set `ui.tier` on anything. The allowed `ui` keys are `label`, `group_label`,
   `order`, `widget`, and a reserved `tier` (`common`/`advanced`, unused).
3. **Tests** (`uv run pytest -n 4 <test file>`):
   - **Round-trip:** a field with `json_schema_extra={"ui": {"label": "X"}}` keeps its `ui` block after
     `model_json_schema()` and after passing through `build_config_view` (jsonref deref preserves
     non-`$ref` keys). Assert the `ui` block is present and intact in the built view.
   - **Shape:** walk the served config schema and assert every `ui` block uses only allowed keys with
     correct value types, and that `tier` (if ever present) is only `common`/`advanced`. Add a comment
     (here and in `config_view.py`) that the OpenAPI freshness check does NOT cover `ui` content — this
     test is the sole guard.
   - **Nested description:** assert a nested-group field (e.g. `database.retention_days`) carries a
     non-empty `description` in the served schema.

## Focus
This is the mechanism, not the tier decisions — populating `ui.tier` (the ~90 common/advanced judgment
calls) and the show-advanced affordance are deferred. `ExcludeExtrasMixin` is a plain mixin class (not a
BaseModel); Pydantic v2 merges `model_config` from bases, so the flag propagates to subclasses that don't
override it. `AppManifest` (also uses the mixin) already sets `use_attribute_docstrings=True` in its own
config — Pydantic's class-level setting takes precedence, so no conflict. Verify `jsonref` preserves the
`ui` block through deref (it only replaces `$ref` nodes, leaving other keys intact) — the round-trip test
catches it if not. The frontend consumption of `ui` hints is T06.

## Verify
- [ ] FR#11: a field's `json_schema_extra={"ui": {...}}` (`label`/`group_label`/`order`/`widget`) survives
  `model_json_schema()` + deref into the built view; `ui.tier` is unset on every field.
- [ ] AC#10: the `ui` block survives the round-trip intact, and the metadata-shape unit test asserts every
  block's allowed keys, value types, and `tier` restricted to `common`/`advanced`.
- [ ] AC#12: a nested-group field (e.g. `database.retention_days`) carries a non-empty `description` in
  the served schema (the `use_attribute_docstrings` fix).
