---
task_id: "T07"
title: "Reword spec tokens in integration tests (excluding bus)"
status: "planned"
depends_on: ["T02", "T03"]
implements: ["FR#8", "AC#7"]
---

## Summary
Reword the ~158 leaked spec tokens in `tests/integration/` (excluding `tests/integration/bus/`, handled in T04) so docstrings and comments describe behavior rather than planning IDs. Includes the large `test_scheduler_mode.py` and the telemetry suite. (Live count via the checker is the source of truth — the named files below under-sum the total; run the checker for the exact set.)

## Target Files
Run `check_spec_tokens.check_file` over `tests/integration/` (excluding `bus/`) for the live list. Reconnaissance:
- modify: `tests/integration/test_scheduler_mode.py` — ~73 tokens (largest single file in the repo).
- modify: `tests/integration/telemetry/**/*.py` — ~39 tokens across ~3 files.
- modify: `tests/integration/test_thread_leaked_observability.py` — ~12 tokens.
- modify: `tests/integration/test_registration.py` — ~7 tokens.
- modify: `tests/integration/test_fatal_shutdown.py` — ~6 tokens.
- modify: other `tests/integration/*.py` with 1–4 tokens each (test_state_proxy, test_sync_facades, web_api, test_command_executor, test_scheduler, test_app_harness_simulation, test_dispatch_unification, test_drain_iterative, test_schema_freshness, test_core — run the checker for the exact set).

## Prompt
For every hit reported by `check_spec_tokens.check_file` over `tests/integration/` **except** `tests/integration/bus/` (that subtree belongs to T04), reword the surrounding comment or docstring to describe what the test verifies and drop the planning code, per the design doc (`design/specs/077-extend-linter-scope/design.md`, FR#8 and `## Key Constraints`).

- Keep the sentence accurate and readable; do not invent behavior.
- No suppression — reword every hit.

Verify zero spec-token hits remain across `tests/integration/` excluding `bus/` via the imported `check_spec_tokens.check_file` (see `context.md`), then run `uv run pytest tests/integration/ --ignore=tests/integration/bus -q` (or the equivalent scoped run).

Production `SCAN_DIRS` stays `["src"]` here — verification is via the imported `check_file`. Widening happens in T09.

## Focus
- `test_scheduler_mode.py` (~73) is the densest single file — expect heavy docstring rewording there.
- Explicitly exclude `tests/integration/bus/` — T04 owns it. Touching it here would create a cross-task write conflict.
- Files here are disjoint from T04 (bus), T05 (core), T06, T08.
- Some integration tests are slow/Docker-backed; if a full scoped pytest run is impractical locally, run the checker-import verification plus a representative subset, and note which suites were not executed.

## Verify
- [ ] FR#8: every reworded docstring/comment in `tests/integration/` (excl. `bus/`) describes verified behavior, not a planning ID (spot-check 3).
- [ ] AC#7: importing `check_spec_tokens.check_file` and running it over `tests/integration/` excluding `bus/` reports zero hits.
