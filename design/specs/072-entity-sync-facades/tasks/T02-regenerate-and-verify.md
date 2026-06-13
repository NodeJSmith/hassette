---
task_id: "T02"
title: "Regenerate entity files and verify freshness and types"
status: "planned"
depends_on: ["T01"]
implements: ["FR#6", "AC#1", "AC#6", "AC#7"]
---

## Summary

Regenerate all domain entity files and `__init__.py` from the updated template,
then verify the output: the codegen freshness `--check` exits 0, Pyright is clean
across the regenerated files, and the new facade classes import successfully. This
task produces the generated artifacts (25+ changed files) and commits them
separately from the template change so the large generated diff is reviewable on
its own.

## Prompt

Depends on T01 (the template must already emit facades).

1. **Ensure an HA core checkout exists** at the pinned version. There is none in
   the worktree. From the repo root:
   ```bash
   if [ ! -d ha-core ]; then
     git clone --depth 1 --branch "$(cat codegen/ha-version.txt)" \
       https://github.com/home-assistant/core.git ha-core
   fi
   ```
   (`codegen/ha-version.txt` pins `2026.5.1`.)

2. **Regenerate** all entity files:
   ```bash
   cd codegen && uv run hassette-codegen generate --ha-core-path ../ha-core
   ```
   This overwrites every `src/hassette/models/entities/{domain}.py` (service-bearing
   domains) and `src/hassette/models/entities/__init__.py`. The `__init__.py`
   export of the new `{Domain}EntitySyncFacade` classes is automatic — the export
   generator (`codegen/src/hassette_codegen/generators/exports.py`) scans every
   non-underscore `ClassDef`. Do NOT hand-edit any generated file.

3. **Verify freshness** (must exit 0):
   ```bash
   cd codegen && uv run hassette-codegen generate --ha-core-path ../ha-core --check
   ```

4. **Verify types** (must be clean — Pyright runs in `basic` mode with
   `reportReturnType` enabled, the exact gate the missing facade return annotation
   was designed to satisfy):
   ```bash
   uv run pyright
   ```

5. **Verify imports** resolve:
   ```bash
   uv run python -c "from hassette.models.entities import CoverEntitySyncFacade, ClimateEntitySyncFacade, LightEntitySyncFacade; print('ok')"
   ```

If Pyright reports errors in generated files, the fix goes in the **template**
(T01), not the generated files — regenerate after fixing.

## Focus

- Generated targets: `src/hassette/models/entities/*.py` (all service-bearing
  domains — alarm_control_panel, climate, cover, fan, light, lock, media_player,
  etc.) and `__init__.py`. State-only domains (e.g. `sensor`) have no entity file.
- Pre-flight already confirmed no domain file hand-defines `.sync` today (only
  `base.py`), so regeneration overwrites nothing bespoke.
- The regenerated `__init__.py` should gain `{Domain}EntitySyncFacade` entries
  next to each `{Domain}Entity`. The current `__init__.py` already exports
  `BaseEntitySyncFacade` from base — confirming the ClassDef scan picks up facade
  classes.
- Likely Pyright pitfalls to watch (all should be prevented by the T01 template
  design, but verify): a `-> None` annotation slipping onto a facade method
  (`reportReturnType`); a redeclared `entity` attribute
  (`reportIncompatibleVariableOverride`); a missing `cast` import.
- Commit the generated files in this task's commit, separate from T01's template
  commit, so reviewers see the template diff and the regenerated diff distinctly.

## Verify

- [ ] FR#6: `src/hassette/models/entities/__init__.py` exports every
      `{Domain}EntitySyncFacade` (regenerated, not hand-edited).
- [ ] AC#1: `from hassette.models.entities import CoverEntitySyncFacade,
      ClimateEntitySyncFacade, LightEntitySyncFacade` succeeds.
- [ ] AC#6: `cd codegen && uv run hassette-codegen generate --ha-core-path
      ../ha-core --check` exits 0 (no drift).
- [ ] AC#7: `uv run pyright` exits 0 with no new errors in the regenerated entity
      files.
