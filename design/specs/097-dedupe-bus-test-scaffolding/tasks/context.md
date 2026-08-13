# Context: Deduplicate bus test scaffolding

## Problem & Motivation

`uv run python tools/check_duplicate_code.py` (PMD CPD-backed) flags 50 clusters touching
`tests/unit/bus/` and 47 touching `tests/integration/bus/` — verified by running the checker
locally on this branch. The dominant contributors are `test_invocation.py` and
`test_handler_invoker.py` (unit) and `test_bus_duration.py`/`test_bus_immediate.py` (integration),
each repeating the same multi-line setup block many times per file. Goal: cut both counts by
≥50% with zero test behavior change, closes GitHub issue #1562.

## Key Decisions

1. Integration bus tests get one new shared "collecting handler" factory in the existing
   `tests/integration/bus/helpers.py` (already the shared home for `seed`, `send_state_change`,
   `fire`, `pump_event_loop`) — it replaces the repeated
   `received: list = []; fired = asyncio.Event(); async def handler(...): received.append(...); hassette.task_bucket.post_to_loop(fired.set)`
   block that recurs across `test_bus_duration.py`, `test_bus_immediate.py`, `test_bus.py`,
   `test_bus_emit.py`, `test_bus_error_handler.py`, and `test_bus_predicate_failure.py`.
2. `helpers.py`'s `seed()` is widened to accept optional kwargs (`attributes`, `last_changed`)
   forwarded to `make_state_dict`, so `test_bus_immediate.py` can adopt it instead of calling
   `harness.seed_state(entity_id, make_state_dict(...))` directly.
3. Unit bus dedup targets are **file-local** helpers, not shared ones: `test_invocation.py`,
   `test_handler_invoker.py`, and `test_duration_hold.py` each get one helper matching their own
   repeated pattern. These do NOT go in `tests/unit/bus/conftest.py` or
   `src/hassette/test_utils/` — per `.claude/rules/test-conventions.md`, shared placement is for
   patterns reused across 3+ files, and these are single-file repeats.
4. Issue #1562's original hypothesis — that `test_duration_hold.py`, `test_duration_timer.py`,
   and `test_duration_config.py` have overlapping local factories that should merge — is
   **rejected**. Verified during design that these three files build three different production
   classes (`DurationHoldManager`, `DurationTimer`, `DurationConfig`) with non-overlapping
   constructor signatures. Do not force a merge.

## Constraints

- No production code (`src/hassette/**`) changes — test files only.
- Before adding any new helper, check `src/hassette/test_utils/factories.py` and
  `src/hassette/test_utils/helpers.py` — this work is about eliminating local duplicates, not
  creating new ones outside the established registry. New bus-specific shared helpers belong in
  `tests/unit/bus/conftest.py` or `tests/integration/bus/helpers.py`, not the global registry,
  unless a pattern is genuinely reusable outside the bus suite (none identified here).
- Do not touch `test_duration_config.py` (no clusters reported there).
- Do not merge `test_duration_hold.py` and `test_duration_timer.py`'s factories together.
- `test_bus_error_handler_combos.py` already has a well-designed `_ErrorCollector` class for its
  own pattern — leave its structure alone unless the checker still flags a cluster in it after
  the other tasks land.
- Every task must leave `tests/unit/bus/` and `tests/integration/bus/` fully green
  (`uv run pytest tests/unit/bus/ tests/integration/bus/ -n 4`) before moving to the next task.
- Fixed pre-refactor collect-count baselines (measured on this branch before any task started):
  697 tests in `tests/unit/bus/`, 125 tests in `tests/integration/bus/`. T05's final gate checks
  both counts are unchanged.
- Update `tests/unit/bus/CLAUDE.md` and `tests/integration/bus/CLAUDE.md` to document any new
  helper before the branch ships.
