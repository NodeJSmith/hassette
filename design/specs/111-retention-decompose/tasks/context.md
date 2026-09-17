# Context: Retention/Size-Failsafe Decomposition

## Problem & Motivation

`database_service.py` has two delete paths (age-based retention cleanup and size-based failsafe) that share no infrastructure despite operating on the same `_RETENTION_TABLES` registry. The size-failsafe path lacks error handling. Extracting shared helpers and fixing the failsafe error handling reduces duplication and complexity independent of any downstream work.

## Key Decisions

1. The two paths have intentionally different transaction patterns — retention uses BEGIN/commit/rollback for atomicity; failsafe commits per-batch so vacuum/checkpoint can reclaim space. The shared delete functions do NOT manage transactions.
2. Two separate delete functions (`_execute_target_delete` for age-based, `_execute_failsafe_delete` for oldest-first batch) rather than one function with mode switching — the SQL patterns are fundamentally different.
3. No speculative extensibility points — the helpers take exactly the parameters the current code needs.
4. `_run_failsafe_tier` is a method on `DatabaseService` (needs `self.get_db_size_mb()` and `self.logger`), not a module-level function.
5. Error handling in the failsafe path is per-target within a batch — a failure on one table logs and continues, not per-batch or per-tier.
6. Six hardcoded module-level constants are replaced with reads from `DatabaseConfig` fields — the config fields already exist but were never wired. Module constants are removed; test patches update from constant to config field.
7. `rollback()` calls are wrapped in their own try/except so a rollback failure doesn't mask the original exception.
8. Test coverage gaps for `_insert_log_records` error path and `run_size_failsafe()` entry point are filled alongside the other test additions.

## Constraints

- No modifications to existing test assertions — all existing tests must pass unmodified (pin-behavior-first). New tests may be added.
- No changes to the parent-guard deletes (listeners/scheduled_jobs NOT EXISTS queries) — those stay inline in `_do_run_retention_cleanup`
- No new files — all extractions stay within `database_service.py`
- No changes to public API (`run_retention_cleanup`, `run_size_failsafe`, `get_db_size_mb`)
- `_RetentionBatchError` does not exist on main — do not reference it
- Comb findings #2/#3 (reporting bugs with `failed_labels`, `capped_tier_label`) do not apply to main — do not address them
