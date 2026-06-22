---
task_id: "T06"
title: "Move telemetry_repository.py under core/telemetry/ (#1095)"
status: "planned"
depends_on: ["T05"]
implements: ["FR#14", "AC#10", "AC#11"]
---

## Summary
Co-locate the misplaced telemetry write helper with the read side: move
`core/telemetry_repository.py` into `core/telemetry/repository.py` and update its 6 importers (1
production + 5 test). Pure file relocation + import rewrite, no behavior change, no compat shim.
Then run the cluster's final cross-cutting verification gate.

## Target Files
- delete: `src/hassette/core/telemetry_repository.py` (moved)
- create: `src/hassette/core/telemetry/repository.py` (the moved file)
- modify: `src/hassette/core/command_executor.py` (import at line ~26)
- modify: `tests/integration/telemetry/test_telemetry_execution_id.py` (import ~line 13)
- modify: `tests/integration/test_dispatch_unification.py` (import ~line 24)
- modify: `tests/unit/core/test_command_executor_pipeline.py` (import ~line 26)
- modify: `tests/unit/core/test_telemetry_repository.py` (imports ~lines 12, 15)
- read: `design/specs/082-web-telemetry-dedup/design.md` (`## Architecture → #1095`, `## Non-Goals`)

## Prompt
Move `src/hassette/core/telemetry_repository.py` to `src/hassette/core/telemetry/repository.py`
(use `git mv` to preserve history). Update every importer of `telemetry_repository` /
`TelemetryRepository`:
- `src/hassette/core/command_executor.py` (production)
- `tests/integration/telemetry/test_telemetry_execution_id.py` (imports `TelemetryRepository` and
  `_execution_insert_params`)
- `tests/integration/test_dispatch_unification.py`
- `tests/unit/core/test_command_executor_pipeline.py`
- `tests/unit/core/test_telemetry_repository.py` (a module-level import and a symbol import)

Leave **no compat shim** at the old path (`coding-style.md`: migrate callers then delete). The moved
file's own imports of `hassette.schemas.telemetry_models` stay as-is — `telemetry_models.py` does
**not** move (see `## Non-Goals`). Note: `schemas/telemetry_models.py` contains a docstring
*reference* to `telemetry_repository` — that is prose, not an import; do not treat it as a caller.

Grep the whole repo for `telemetry_repository` and `from hassette.core.telemetry_repository` after
the move to confirm zero stale references.

**Final cluster verification gate (AC#11).** After the move: `uv run pyright` clean;
`uv run python scripts/export_schemas.py --types` produces zero diff; `uv run nox -s system` and
`uv run nox -s e2e` pass locally. These confirm the whole cluster (#1107 → #1108a → #1114 → #1095)
preserved behavior except the one intended `ValueError → 500` change.

## Focus
- This is the lowest-risk task — a mechanical move with a known, bounded importer list (no layer
  conflict, unlike the dropped `telemetry_models.py` move). Use `git mv` so the diff reads as a
  rename.
- `TelemetryRepository` is a single class (~662 lines). Do not refactor its contents — only move
  the file and fix imports.
- Confirm `command_executor.py` still type-checks; it is the one production importer.
- The new module sits beside `query_service.py`, the three query mixins, and `helpers.py` in
  `core/telemetry/`. Match the package's existing import style.

## Verify
- [ ] FR#14: `telemetry_repository.py` lives at `core/telemetry/repository.py`; all 6 importers
      updated; no compat shim; a repo-wide grep for the old path returns nothing.
- [ ] AC#10: `uv run pyright` is clean after the move.
- [ ] AC#11: across the cluster — zero `scripts/export_schemas.py --types` diff, Pyright clean, and
      `nox -s system` + `nox -s e2e` pass locally.
