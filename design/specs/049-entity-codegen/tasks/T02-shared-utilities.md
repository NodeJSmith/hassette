---
task_id: "T02"
title: "Extract shared utilities from sync facade"
status: "planned"
depends_on: ["T01"]
implements: ["FR#20"]
---

## Summary
Extract the reusable codegen infrastructure from the sync facade into shared internal modules. These utilities (ruff formatting pipeline, per-file validation, drift checking) become the foundation both generators use. The sync facade is then refactored to import from these shared modules rather than defining them inline.

## Prompt
Extract from `codegen/src/hassette_codegen/sync_facade.py` into shared modules:

**`codegen/src/hassette_codegen/output.py`** — file output utilities:
- `_run_ruff_step(cmd, step_name)` → `run_ruff_step()`
- `_format_via_ruff(content)` → `format_via_ruff()`
- `_atomic_write_generated(out_path, content)` → `atomic_write(path, content)` — update to validate (ruff + py_compile) independently per file, skip with warning on failure, write on success
- `_check_drift(target_path, generated_content, label)` → `check_drift(path, content)` — returns bool

Refactor `sync_facade.py` to import from `output.py` instead of using its own copies. Verify the sync facade still works (run its existing tests).

Add unit tests for the extracted utilities in `codegen/tests/test_output.py`:
- `format_via_ruff` produces valid Python
- `atomic_write` creates the file on success
- `atomic_write` does NOT create the file on validation failure (inject a syntax error)
- `check_drift` returns True when content matches, False when it differs

## Focus
- `_run_ruff_step` is at line 365, `_format_via_ruff` at 388, `_atomic_write_generated` at 439, `_check_drift` at 1118
- `_format_via_ruff` uses `subprocess.run` with `timeout=30` — preserve this
- `_atomic_write_generated` writes to a NamedTemporaryFile then renames — preserve atomic behavior
- `_check_drift` normalizes both sides through ruff before comparing — critical for determinism
- The sync facade tests at `tests/unit/tools/test_generate_sync_facade.py` must still pass after refactor

## Verify
- [ ] FR#20: Each generated file is validated independently (ruff + py_compile) — files that fail are skipped with a warning; files that pass are written
