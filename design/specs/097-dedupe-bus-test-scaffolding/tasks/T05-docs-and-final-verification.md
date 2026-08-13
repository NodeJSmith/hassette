---
task_id: "T05"
title: "Document new helpers in both CLAUDE.md files and run final verification"
status: "planned"
depends_on: ["T01", "T02", "T03", "T04"]
implements: ["FR#9", "FR#10", "AC#1", "AC#2", "AC#3", "AC#4", "AC#5"]
---

## Target Files

- modify: `tests/unit/bus/CLAUDE.md`
- modify: `tests/integration/bus/CLAUDE.md`

## Prompt

T01-T04 introduced new helpers:
- A shared collecting-handler helper and a widened `seed()` in `tests/integration/bus/helpers.py`
  (T01), adopted across `test_bus_duration.py`, `test_bus_immediate.py`, `test_bus.py`,
  `test_bus_emit.py`, `test_bus_error_handler.py`, `test_bus_predicate_failure.py` (T01+T02).
- File-local helpers in `test_invocation.py` and `test_handler_invoker.py` (T03).
- File-local helpers in `test_duration_hold.py` and possibly `test_duration_timer.py` (T04).

Read the actual final state of all the modified files (helper names and signatures were left as
implementation decisions for T01-T04's executors — don't assume the exact names from those task
prompts survived unchanged).

Update `tests/integration/bus/CLAUDE.md`'s "Shared helpers" section to list the new
collecting-handler helper and the widened `seed()` signature, matching the existing bullet style
already in that file (see current `seed`/`fire`/`pump_event_loop` bullets for the format).

Update `tests/unit/bus/CLAUDE.md` — it currently only documents `hassette_with_bus`/`bus` fixtures
and `mock_add_listener`. Add a note (new section or extend "Key conventions") that
`test_invocation.py`, `test_handler_invoker.py`, and `test_duration_hold.py` (and
`test_duration_timer.py` if T04 added a helper there) each carry a file-local helper for their own
repeated setup pattern — file-local, not exported via `conftest.py`, so a reader looking at
`conftest.py` alone won't find them. Name each helper and which file it's in.

Then run the full final verification sweep:

1. `uv run python tools/check_duplicate_code.py` — confirm bus-directory cluster counts (parse
   output for lines containing `tests/unit/bus/` or `tests/integration/bus/`, same approach used
   during design investigation) are ≤25 for `tests/unit/bus/` and ≤23 for `tests/integration/bus/`
   (47×0.5=23.5, so ≤23 is required for a true ≥50% reduction — not ≤24).
   If either threshold isn't met, go back and check whether an earlier task's helper adoption was
   incomplete (grep for `asyncio.Event()` / repeated setup patterns in files that were supposed to
   be covered).
2. `uv run pytest tests/unit/bus/ --collect-only -q` — must report exactly 697 tests collected
   (the fixed pre-refactor baseline recorded in `design.md`'s Goals section). If the count differs,
   a helper introduced in T01-T04 changed test collection (e.g. swallowed a parametrize case,
   accidentally renamed a `test_*` function) — find and fix it before proceeding.
3. `uv run pytest tests/integration/bus/ --collect-only -q` — must report exactly 125 tests
   collected, same reasoning as step 2.
4. `uv run pytest tests/unit/bus/ tests/integration/bus/ -n 4` — zero failures.
5. `prek -a` — clean on every modified file.
6. `git diff --stat -- src/hassette/` — must be empty output (confirms no production code changed).

## Verify

- [ ] FR#9: both `CLAUDE.md` files document every new helper introduced by T01-T04, by name and
      file.
- [ ] FR#10 / AC#5: `git diff --stat -- src/hassette/` produces no output.
- [ ] AC#1: `tests/unit/bus/` cluster count ≤25.
- [ ] AC#2: `tests/integration/bus/` cluster count ≤23.
- [ ] AC#3: `uv run pytest tests/unit/bus/ --collect-only -q` reports exactly 697 tests,
      `uv run pytest tests/integration/bus/ --collect-only -q` reports exactly 125 tests, and
      `uv run pytest tests/unit/bus/ tests/integration/bus/ -n 4` passes with zero failures.
- [ ] AC#4: `prek -a` passes clean.
