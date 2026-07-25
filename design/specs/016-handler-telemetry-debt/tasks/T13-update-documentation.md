---
task_id: "T13"
title: "Update documentation for split files"
status: "planned"
depends_on: ["T02", "T05", "T10", "T11", "T12"]
implements: ["AC#9"]
---

## Summary

Update `tests/TESTING.md` and `.claude/rules/test-conventions.md` with the new `web_helpers` submodule paths and factory locations. Also run the full verification suite to confirm AC#9 (all lints, type checks, and tests pass).

## Target Files

- modify: `tests/TESTING.md`
- modify: `.claude/rules/test-conventions.md`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

**Update `tests/TESTING.md`:**
- Find the factory guide section that references `web_helpers.py` and update paths to the new submodules (`web_manifest_helpers.py`, `web_job_helpers.py`, `web_response_helpers.py`, `web_telemetry_helpers.py`)
- Update any import examples that reference `from hassette.test_utils.web_helpers import`
- If `make_job`, `make_real_job`, and `make_scheduled_job` disambiguation section references `web_helpers`, update the paths

**Update `.claude/rules/test-conventions.md`:**
- Update the "Canonical factories and where they live" section: replace the `src/hassette/test_utils/web_helpers.py` entry with 4 entries for the new submodules
- Update each factory's listed path to its new location
- Keep the factory descriptions and usage notes unchanged

**Full verification:**
Run `prek -a` (lint + type check) and `ptest -- tests/unit tests/integration -n 4` to confirm everything passes. For frontend: `cd frontend && npm run build && npm test`.

## Focus

- Search both files for every occurrence of `web_helpers` AND `telemetry_models` to ensure nothing is missed — both paths changed.
- The factory names and descriptions don't change — only the file paths.
- This task is intentionally last among the backend tasks to catch any residual issues.

## Verify

- [ ] AC#9: `prek -a` passes; `ptest -- tests/unit tests/integration -n 4` passes; `cd frontend && npm run build && npm test` passes
