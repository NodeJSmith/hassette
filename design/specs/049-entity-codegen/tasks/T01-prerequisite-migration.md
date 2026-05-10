---
task_id: "T01"
title: "Migrate features.py and sync facade into codegen package"
status: "planned"
depends_on: []
implements: ["FR#1"]
# Note: T01 is a prerequisite migration. FR#1 is also implemented by T04 (extraction) and T07 (generation).
# T01 handles the manual dissolution of features.py; T04+T07 handle the generator's ability to produce colocated enums going forward.
---

## Summary
Prerequisite migration before the generator can run. Two changes: (1) dissolve `features.py` by moving each IntFlag enum into its domain's state model file and updating all imports, (2) move `tools/generate_sync_facade.py` into the new `codegen/` package structure. This establishes the target codebase state the generator will maintain going forward.

## Prompt
Two migration steps:

**Step 1: Dissolve features.py**

Move each IntFlag enum from `src/hassette/models/states/features.py` into its domain's state file:
- `LightEntityFeature` → `src/hassette/models/states/light.py`
- `FanEntityFeature` → `src/hassette/models/states/fan.py`
- `ClimateEntityFeature` → `src/hassette/models/states/climate.py`
- `CoverEntityFeature` → `src/hassette/models/states/cover.py`
- `LockEntityFeature` → `src/hassette/models/states/lock.py`
- `MediaPlayerEntityFeature` → `src/hassette/models/states/media_player.py`
- `VacuumEntityFeature` → `src/hassette/models/states/vacuum.py`

Update all imports:
- 7 domain state files: change `from .features import XEntityFeature` → define inline
- `src/hassette/models/states/__init__.py`: update re-exports to import enums from domain files
- `tests/unit/test_supported_features.py`: update `from hassette.models.states.features import (...)` to per-domain imports

Delete `features.py` after all imports are updated.

**Step 2: Scaffold codegen/ package**

Create `codegen/` at the repo root with:
- `pyproject.toml` — package name `hassette-codegen`, `requires-python = ">=3.14"`, deps: `jinja2`, `pyyaml`. Entry point: `hassette-codegen = "hassette_codegen.__main__:main"`
- `src/hassette_codegen/__init__.py` — empty
- `src/hassette_codegen/__main__.py` — minimal CLI skeleton with argparse (--ha-core-path, --ha-release-tag, --check, --domain)
- `ha-version.txt` — content: `2026.5.1`

Move `tools/generate_sync_facade.py` into `codegen/src/hassette_codegen/sync_facade.py` (copy as-is, update shebang/imports minimally). Wire a `sync-facade` subcommand in the CLI (`__main__.py`) so it's invocable as `hassette-codegen sync-facade [--check]`. Update CI workflow to invoke from new location. Update `tests/unit/tools/test_generate_sync_facade.py` imports.

The `codegen/` package is NOT a dev dependency of hassette (incompatible Python version bounds). It has its own venv and is invoked standalone: `cd codegen && uv sync && uv run hassette-codegen`.

## Focus
- `src/hassette/models/states/features.py` has 7 enums, each ~10-20 lines
- Each domain state file already imports from features.py at line 6 — replace that import with the enum definition above the Attributes class
- The `AttributesBase._has_feature()` method (in `base.py`) takes an IntFlag member — it doesn't care where the enum is defined, just that it's an IntFlag
- `test_supported_features.py` is the only test importing by absolute path from features
- `generate_sync_facade.py` is 1234 lines with 37 functions — move as-is initially, shared utility extraction happens in T02
- The CI workflow at `.github/workflows/lint.yml` references `tools/generate_sync_facade.py` — update to `codegen/` invocation

## Verify
- [ ] FR#1: IntFlag enums are defined in their domain state files (e.g., `LightEntityFeature` in `light.py`), not in a separate `features.py`
