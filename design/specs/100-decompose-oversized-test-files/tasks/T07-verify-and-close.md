---
task_id: "T07"
title: "Verify no production code changed and lint is clean across all six splits"
status: "done"
depends_on: ["T01", "T02", "T03", "T04", "T05", "T06"]
implements: ["AC#7"]
---

## Target Files

- (verification only — no files created or modified by this task)

## Prompt

All six test-file splits (T01-T06) are complete. This task is the integration check that ties
them together: confirm the batch as a whole introduced no production code changes and passes
lint.

Run:

1. `git diff --stat main -- src/` — must produce no output. If it produces any output, one of the
   prior tasks touched production code, which violates this batch's scope (test-only reorg). Stop
   and report which file(s) changed under `src/` rather than trying to fix it yourself — that's a
   scope violation to flag, not silently revert.
2. `prek -a` — runs ruff, import ordering, and every hook staged for regular commits. Fix any
   formatting/import-order issues it flags; automatic fixes re-stage files, so re-run `prek -a`
   until it passes clean, per this repo's standard pre-commit workflow (see CLAUDE.md's
   "Pre-commit Hook Validation"). Then run `prek pyright -a --stage pre-push` separately — pyright
   is staged to `pre-push` in `prek.toml`, so a bare `prek -a` does **not** run it, and skipping
   this step would leave the new/moved imports and relative-import paths across ~15 changed test
   files completely type-unchecked.
3. Confirm every file listed across T01-T06's Target Files is under 800 lines:
   `wc -l tests/integration/websocket/*.py tests/unit/test_logging*.py tests/unit/test_autodetect_apps*.py tests/unit/test_validate_apps.py tests/unit/cli/test_client*.py tests/unit/core/test_app_lifecycle_service*.py tests/unit/core/test_command_executor_pipeline*.py`
   — every line count in the output must be under 800.

## Verify

- [ ] AC#7: `git diff --stat main -- src/` is empty. `prek -a` passes clean. `prek pyright -a --stage pre-push` passes clean. Every file named in the `wc -l` check above is under 800 lines.
