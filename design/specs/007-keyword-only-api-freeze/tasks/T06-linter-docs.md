---
task_id: "T06"
title: "Add registration signature linter, update docs and examples"
status: "planned"
depends_on: ["T02", "T03"]
implements: ["FR#12", "AC#10", "AC#11"]
---

## Summary
Create the AST-based regression prevention linter that enforces `*` placement and required `name` on registration methods, wire it into pre-commit, and update all doc snippets and example apps to include `name=` on scheduler and bus calls. Remove auto-naming references from prose. Run `prek -a` to verify everything is clean.

## Target Files
- create: `tools/check_registration_signatures.py`
- modify: `.pre-commit-config.yaml`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_run_once.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_run_daily.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_run_hourly.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_run_minutely.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_custom_trigger.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_schedule_examples.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_error_handler_app.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_error_handler_per_job.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_cancel_job.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_job_groups.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_jitter.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_overlapping_jobs.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_run_cron.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_where_job_arg.py`
- modify: `docs/pages/core-concepts/scheduler/snippets/scheduler_where_state_check.py`
- modify: `docs/pages/core-concepts/cache/snippets/cache_api_response.py`
- modify: `docs/pages/core-concepts/cache/snippets/cache_complex_data.py`
- modify: `docs/pages/core-concepts/apps/snippets/apps_run_hourly.py`
- modify: `docs/pages/getting-started/snippets/first_automation_step4.py`
- modify: `docs/pages/migration/snippets/scheduler_migration.py`
- modify: `docs/pages/migration/snippets/bus_migration_state_changes.py`
- modify: `docs/pages/migration/snippets/bus_migration_service_calls.py`
- modify: `docs/pages/migration/snippets/bus_name_missing.py`
- modify: `docs/pages/operating/snippets/timeout_overrides.py`
- modify: `docs/pages/recipes/snippets/daily_notification.py`
- modify: `docs/pages/recipes/snippets/daily_notification_handler.py`
- modify: `docs/pages/core-concepts/bus/snippets/filtering_increased_decreased.py`
- modify: `docs/pages/core-concepts/bus/snippets/filtering_simple_start.py`
- modify: `docs/pages/core-concepts/bus/snippets/filtering_combined_and.py`
- modify: `docs/pages/core-concepts/bus/snippets/handlers_service_extract.py`
- modify: `examples/cover_scheduler.py`
- create: `tests/unit/tools/test_check_registration_signatures.py`
- read: `tools/check_lazy_imports.py` (linter pattern to follow)
- read: `tests/unit/tools/test_check_lazy_imports.py` (test pattern to follow)

## Prompt
**1. Create `tools/check_registration_signatures.py`:**

Follow the `tools/check_lazy_imports.py` AST-based pattern exactly:
- Parse `src/hassette/bus/bus.py` and `src/hassette/scheduler/scheduler.py` with `ast.parse`
- For each class definition (`Bus`, `Scheduler`), find all public methods (not `_`-prefixed) that have a parameter named `name`
- Check two invariants:
  1. `*` separator appears before the `name` parameter in the signature
  2. The `name` parameter has no default value (no `ast.Constant`, no `ast.Attribute`, etc. in `default`/`kw_defaults`)
- Exit 0 if clean, exit 1 with `file:line — violation description` for each failure
- Usage: `python tools/check_registration_signatures.py` (no arguments — files are hardcoded)

**2. Wire into `.pre-commit-config.yaml`:**

Add a new hook entry near the existing `check_*` hooks. Follow the repo convention — use kebab-case id and `language: system` (matching `check-lazy-imports`, `check-missing-attribute`, etc.):
```yaml
  - id: check-registration-signatures
    name: Check registration method signatures
    entry: ./tools/check_registration_signatures.py
    language: system
    files: ^src/hassette/(bus/bus|scheduler/scheduler)\.py$
    stages: [pre-commit, pre-push]
    pass_filenames: false
```

**2b. Add linter tests:**

Create `tests/unit/tools/test_check_registration_signatures.py` following the pattern of `tests/unit/tools/test_check_lazy_imports.py`. Test with sample inputs:
- Valid signatures (method with `*` before `name`, no default) → exit 0
- Invalid: `name` before `*` → exit 1
- Invalid: `name` with a default value → exit 1
- Methods without `name` parameter (e.g., `on_error`) → should not be flagged

**3. Update ALL doc snippets and examples:**

Find every file under `docs/` and `examples/` with scheduler or bus registration calls missing `name=`:
```bash
grep -rln 'scheduler\.\(schedule\|run_in\|run_once\|run_every\|run_daily\|run_cron\|run_minutely\|run_hourly\)(' docs/ examples/ | sort
grep -rln 'bus\.\(on_state_change\|on_attribute_change\|on_call_service\|on\b\)(' docs/ examples/ | sort
```

For each file, add `name="descriptive_name"` to calls that omit it. Use context-appropriate names (e.g., `name="weather_poll"` for a weather polling schedule, `name="light_change"` for a light state change listener).

Special cases:
- `docs/pages/migration/snippets/bus_name_missing.py` — this is a "before" example showing what NOT to do. It should stay WITHOUT `name=` as it demonstrates the error case. Verify that the corresponding "correct" example (`bus_name_correct.py`) has `name=`.
- Remove any prose references to "auto-naming" or "auto-derived names" in scheduler concept pages and migration docs.

**4. Run `prek -a`** to verify all pre-commit hooks pass (including the new linter, ruff, pyright on all files including snippets).

## Focus
The linter needs to handle the `Bus.on()` method (named `on`, not `on_something`) — the scan is structural (has a `name` parameter), not name-prefix-based.

Methods like `Bus.on_error()` and `Scheduler.on_error()` do NOT have a `name` parameter, so the structural check naturally excludes them.

Doc snippets are Pyright-checked in CI, so missing `name=` on required parameters will fail pyright. Update them all.

The target files list above covers the major snippets found during reconnaissance. Use grep to find any additional files not listed — there may be more in bus/scheduler concept page subdirectories.

## Verify
- [ ] FR#12: `tools/check_registration_signatures.py` exits 0 on current (correct) `bus.py` and `scheduler.py`
- [ ] AC#10: `prek -a` passes (all hooks including the new linter)
- [ ] AC#11: The linter exits 1 when given a test input with `name` before `*` or with a default value
