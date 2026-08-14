# Design: Deduplicate bus test scaffolding

**Date:** 2026-08-13
**Status:** approved
**Mode:** sketch

## Problem

`uv run python tools/check_duplicate_code.py` (PMD CPD-backed, `MIN_OCCURRENCES=3`) currently
flags 50 clusters touching `tests/unit/bus/` and 47 touching `tests/integration/bus/` — verified
by running the checker locally, not the unconfirmed ~47/~43 estimate from issue #1562's original
write-up. The dominant contributors are:

- **`tests/unit/bus/test_invocation.py`** — appears in ~15 of the 50 unit/bus clusters. Nearly
  every test repeats: build `executor`/`config_resolver`/`listener`/`event`, call
  `build_tracked_invoke_fn(...)`, `await invoke_fn()`, then extract
  `cmd = executor.execute.call_args[0][0]`.
- **`tests/unit/bus/test_handler_invoker.py`** — ~6 clusters. Nearly every test repeats:
  `task_bucket = make_task_bucket()`, build `ListenerOptions(...)`, call `HandlerInvoker.create(...)`.
- **`tests/unit/bus/test_duration_hold.py`** — ~7 clusters, all intra-file: repeated
  "build listener with `duration_config` + attach a `MagicMock` timer" setup blocks across
  `TestStartDurationTimer` and `TestCreateCancelListener`.
- **`tests/unit/bus/test_duration_timer.py`** — 3 clusters, intra-file setup/teardown repeats.
- **`tests/integration/bus/test_bus_duration.py`** and **`test_bus_immediate.py`** — the two
  largest integration contributors (several clusters each, including two clusters spanning both
  files). Nearly every test repeats: `received: list[...] = []`, `fired = asyncio.Event()`, an
  async handler that appends to `received` and calls
  `hassette.task_bucket.post_to_loop(fired.set)`, then `await asyncio.wait_for(fired.wait(), ...)`.
- **`tests/integration/bus/test_bus.py`**, **`test_bus_emit.py`**, **`test_bus_error_handler.py`**
  — smaller but real instances of the same "collecting handler" pattern, in files that don't
  import `tests/integration/bus/helpers.py` at all today.
- **`tests/integration/bus/test_bus_error_handler_combos.py`** — several intra-file clusters from
  the register → `send_state_change`/`seed` → wait boilerplate repeated across on_error
  duration/immediate combinations.

Issue #1562's original hypothesis — that `test_duration_hold.py`, `test_duration_timer.py`, and
`test_duration_config.py` share overlapping local factories (`make_manager`, `make_timer`,
`make_event`, etc.) that should merge into one shared `conftest.py` — does not hold up: those
three files build three different production classes (`DurationHoldManager`, `DurationTimer`,
`DurationConfig`) with constructor signatures that don't overlap. Forcing those factories together
would violate `.claude/rules/test-conventions.md`'s guidance against merging things that build
genuinely different shapes. This design targets the clusters the checker actually reports instead.

## Goals

- Cut `tests/unit/bus/` cluster count from 50 as far as reachable via T03/T04's scope. The
  original ≤25 target is **not fully met**: the final count is 27. T05's investigation confirmed
  T03/T04's helper adoption is complete (zero remaining un-adopted instances of the patterns those
  tasks targeted, one deliberate sequencing exception in `test_invocation.py` already documented).
  The 27-vs-25 gap is structural: 19 of 27 clusters sit entirely in 14 files never targeted by this
  design (`test_once_listener_tracking.py`, `test_router.py`, `test_predicate_details.py`,
  `test_if_exists.py`, `test_accessors.py`, `test_listeners.py`, `test_execution_mode_guard.py`,
  `test_bus_where.py`, `test_bus_coroutine_conversion.py`, `test_bus_error_handler.py`,
  `test_bus_registration_edge_cases.py`, `test_registration_errors.py`, `test_predicates.py`,
  `test_bus.py`) — the original investigation's cluster count (50) included a long tail spread
  thin across many small files, not concentrated in the two "dominant contributor" files this
  design targeted. 6 are the `test_duration_hold.py` residual already accepted as out-of-scope
  during T04 (see below). The remaining **2** are a case the mid-run CONTESTED narrative initially
  omitted (caught by T05's spec reviewer, since 19+6=25 not 27): `test_invocation.py` — a T03
  target — clusters against `tests/unit/core/test_bus_service_error_handler.py` and
  `test_bus_service_timeout.py`, two files entirely outside this design's scope. T03's helper
  (`invoke_and_get_cmd`) collapsed the intra-`test_invocation.py` duplication FR#5 targeted, but
  PMD CPD also matches the surviving per-test result-extraction lines against an analogous pattern
  in those two `tests/unit/core/` files — cross-directory duplication no task in this design was
  ever scoped to address. 19+6+2=27. 50→27 is still a 46% reduction, just short of the ≥50% goal.
- Cut `tests/integration/bus/` cluster count from 47 as far as reachable. The original ≤23
  (≥50% reduction) target is **known unreachable** via this task set: T02's investigation
  (evidence in `tasks/T02-integration-widen-adoption.md`'s CONTESTED resolution) proved the T01
  collecting-handler helper is architecturally scoped to `on_state_change`/`on_attribute_change`
  (its handler is hard-typed `RawStateChangeEvent`, and the DI layer in
  `src/hassette/bus/injection.py` actively converts/rejects non-matching event types) and cannot
  serve `bus.on(topic=...)` registrations with other payload types or `on_error` callback
  patterns — confirmed via trial-adoption that failed at runtime, then reverted. After T01+T02 the
  count is 40, not ≤23, with nothing further reducible inside T01/T02's scope. The remaining
  clusters live in files never targeted by this design (`test_execution_modes.py`,
  `test_execution_modes_guards.py`, `conftest.py`) or in `test_bus_error_handler_combos.py`
  (deliberately left alone per the Approach section's guidance not to redesign its existing
  `_ErrorCollector` abstraction). T05 reports the actual final count as an honest measurement,
  not a pass/fail gate against ≤23.
- Zero test behavior change — every existing test still passes with the same assertions, and the
  same number of tests collect: 697 in `tests/unit/bus/`, 125 in `tests/integration/bus/`
  (measured via `uv run pytest tests/unit/bus/ --collect-only -q` /
  `uv run pytest tests/integration/bus/ --collect-only -q` on this branch before any refactor task
  began).
- New shared helpers land in the existing shared-registry location for integration bus tests
  (`tests/integration/bus/helpers.py`) per `.claude/rules/test-conventions.md`. No unit-bus
  duplication identified in this design is shared across 3+ files, so no new helper is added to
  `tests/unit/bus/conftest.py` — every unit-bus fix (FR#5-#8) is a file-local helper instead.

## Functional Requirements

- **FR#1** `tests/integration/bus/helpers.py` gains a shared "collecting handler" factory (a
  function that returns an async handler which appends received events/data to a list and signals
  an `asyncio.Event` via `task_bucket.post_to_loop`) that replaces the repeated
  list+Event+handler+`wait_for` block in integration bus tests.
- **FR#2** `test_bus_duration.py` and `test_bus_immediate.py` adopt the FR#1 helper wherever the
  collecting-handler pattern currently appears.
- **FR#3** `tests/integration/bus/helpers.py`'s `seed()` accepts optional keyword arguments
  (e.g. `attributes`, `last_changed`) forwarded to `make_state_dict`, and `test_bus_immediate.py`
  adopts `seed()` at call sites that only need entity_id/state_value/attributes/last_changed
  instead of calling `harness.seed_state(entity_id, make_state_dict(...))` directly.
- **FR#4** `test_bus.py`, `test_bus_emit.py`, `test_bus_error_handler.py`, and
  `test_bus_predicate_failure.py` adopt the FR#1 collecting-handler helper wherever applicable,
  even though these files don't import `helpers.py` today.
- **FR#5** `tests/unit/bus/test_invocation.py`'s repeated
  build-`invoke_fn`-then-invoke-then-extract-`cmd` pattern collapses into one file-local helper.
- **FR#6** `tests/unit/bus/test_handler_invoker.py`'s repeated
  `make_task_bucket()` + `ListenerOptions(...)` + `HandlerInvoker.create(...)` pattern collapses
  into one file-local helper.
- **FR#7** `tests/unit/bus/test_duration_hold.py`'s repeated "listener with `duration_config` +
  mock timer attached" setup blocks collapse into one file-local helper, without merging with
  `test_duration_timer.py` or `test_duration_config.py`'s factories.
- **FR#8** `tests/unit/bus/test_duration_timer.py`'s repeated intra-file setup blocks collapse
  into file-local helper(s) where the checker still flags them after FR#7.
- **FR#9** `tests/unit/bus/CLAUDE.md` and `tests/integration/bus/CLAUDE.md` document every new
  shared or file-local helper introduced by this change.
- **FR#10** No production code (`src/hassette/**`) changes — this is test-file-only.

## Acceptance Criteria

- **AC#1** `uv run python tools/check_duplicate_code.py` — report the actual count of clusters
  whose fragments include a `tests/unit/bus/` path. Final result: 27, not ≤25 (see Goals for the
  structural explanation — accepted as satisfied by an honest final measurement rather than a
  literal ≤25, consistent with AC#2's precedent).
- **AC#2** `uv run python tools/check_duplicate_code.py` — report the actual count of clusters
  whose fragments include a `tests/integration/bus/` path as of the final task (T05). The original
  ≤23 target is known unreachable via this task set (see Goals) — AC#2 is satisfied by an honest
  final measurement plus a check that the count did not regress above 40 (the count already
  reached after T01+T02), not by hitting ≤23.
- **AC#3** `uv run pytest tests/unit/bus/ --collect-only -q` reports exactly 697 tests collected,
  `uv run pytest tests/integration/bus/ --collect-only -q` reports exactly 125 tests collected
  (both baselines fixed pre-refactor — see Goals), and
  `uv run pytest tests/unit/bus/ tests/integration/bus/ -n 4` passes with zero failures.
- **AC#4** `prek -a` passes clean on every modified file (ruff + pyright, per CLAUDE.md's Code
  Style section).
- **AC#5** `git diff -- src/hassette/` is empty — confirms FR#10 (no production code touched).

## Approach

**Integration bus (`tests/integration/bus/`):** Add one new function to the existing
`helpers.py` (already the shared home for `seed`, `send_state_change`, `fire`, `pump_event_loop`,
per its module docstring and `tests/integration/bus/CLAUDE.md`) that builds the collecting-handler
closure. Something like:

```python
def make_collector(task_bucket: TaskBucket) -> tuple[Callable[[Event], Coroutine], list, asyncio.Event]:
    """Build a handler that appends events and signals completion via task_bucket.post_to_loop."""
```

The exact signature is an implementation detail for the executor — match whatever shape lets
`test_bus_duration.py`'s and `test_bus_immediate.py`'s existing call sites drop in with minimal
surrounding-line changes (some tests need the raw event, some need `event.payload.data`; check
both usages before settling on one shape, or provide two thin variants if a single shape can't
serve both cleanly). Widen `seed()`'s signature at the same time — it currently only takes
`(harness, entity_id, state_value)` and calls `make_state_dict(entity_id, state_value)`;
`test_bus_immediate.py` needs `attributes=` and `last_changed=` passed through.

Adopt the new helper(s) first in the two dominant files (`test_bus_duration.py`,
`test_bus_immediate.py`), then in the four files that don't import `helpers.py` at all today
(`test_bus.py`, `test_bus_emit.py`, `test_bus_error_handler.py`, `test_bus_predicate_failure.py`).
`test_bus_error_handler_combos.py` already has a well-designed `_ErrorCollector` abstraction for
its own pattern — leave that file's structure alone unless the checker still flags it as a
cluster after the other files are fixed; don't force a redesign of code that's already using a
reasonable local abstraction.

**Unit bus (`tests/unit/bus/`):** `test_invocation.py` and `test_handler_invoker.py` each get one
file-local helper matching their own repeated pattern (build-invoke-extract for the former,
build-task_bucket-options-invoker for the latter). `test_duration_hold.py` gets a file-local
helper for its listener+mock-timer setup. Do not add any of these to the shared
`tests/unit/bus/conftest.py` or to `src/hassette/test_utils/` — per `.claude/rules/test-conventions.md`,
shared placement is for patterns reused across 3+ files; these are single-file repeats. Do not
touch `test_duration_config.py` (no clusters reported there) or attempt to unify
`test_duration_hold.py`/`test_duration_timer.py`'s factories — confirmed in investigation that
they build different production classes.

**Verification loop:** after each file's changes, re-run
`uv run pytest tests/unit/bus/<file> tests/integration/bus/<file> -n 4` (or the whole
`tests/unit/bus/ tests/integration/bus/` suite at the end) to confirm zero behavior change, per
CLAUDE.md's "Run fixed tests before committing." Re-run `check_duplicate_code.py` after all tasks
to confirm the AC#1/AC#2 thresholds.

## Dependencies and Assumptions

- `uv run python tools/check_duplicate_code.py` needs Java 21+ on PATH (already confirmed present
  in this worktree) and downloads a cached PMD binary on first run (~50MB, shared across
  worktrees).
- The 50/47 baseline was measured on this branch after merging `origin/main` (which had already
  merged #1613's `test_execution_modes.py` split) — re-verify the baseline is unchanged before
  starting if significant time passes before execution begins.
- Reducing clusters is a real-code-quality goal, not a hard CI gate today — `duplicate-code` runs
  with `continue-on-error: true` in `.github/workflows/lint.yml` (a pre-existing, already-triaged
  backlog per CLAUDE.md's "Known-failing lint checks" section). This work reduces that backlog for
  the bus test directories specifically; it does not need to zero out the whole repo's count.

## Changed Files

- `tests/integration/bus/helpers.py` — modify: add collecting-handler factory, widen `seed()`.
- `tests/integration/bus/test_bus_duration.py` — modify: adopt collecting-handler helper.
- `tests/integration/bus/test_bus_immediate.py` — modify: adopt collecting-handler helper + widened `seed()`.
- `tests/integration/bus/test_bus.py` — modify: adopt collecting-handler helper.
- `tests/integration/bus/test_bus_emit.py` — modify: adopt collecting-handler helper.
- `tests/integration/bus/test_bus_error_handler.py` — modify: adopt collecting-handler helper.
- `tests/integration/bus/test_bus_predicate_failure.py` — modify: adopt collecting-handler helper where applicable.
- `tests/integration/bus/CLAUDE.md` — modify: document new helper(s).
- `tests/unit/bus/test_invocation.py` — modify: extract file-local invoke helper.
- `tests/unit/bus/test_handler_invoker.py` — modify: extract file-local invoker-setup helper.
- `tests/unit/bus/test_duration_hold.py` — modify: extract file-local listener+timer setup helper.
- `tests/unit/bus/test_duration_timer.py` — modify: extract file-local setup helper if clusters remain after FR#7.
- `tests/unit/bus/CLAUDE.md` — modify: document new file-local helpers.
