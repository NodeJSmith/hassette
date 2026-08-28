---
task_id: "T06"
title: "Classify root shutdown timeout evidence"
status: "done"
depends_on: ["T05"]
implements: ["FR#3", "FR#10", "FR#13", "FR#17", "AC#7"]
---

## Summary

Finish Hassette's root-specific shutdown body and reverse dependency-wave aggregation. Convert the total timeout
fallback from bookkeeping-only completion into explicit restart-unsafe evidence while preserving force-finalization,
STOPPED handling, and event-stream closure on both ordinary and timeout paths.

## Target Files

- read: `design/specs/105-teardown-restart-safety/design.md`
- modify: `src/hassette/core/core.py`
- modify: `tests/unit/resources/lifecycle/test_total_timeout.py`
- modify: `tests/unit/core/test_core_coverage.py`
- read: `tests/system/test_shutdown.py`
- read: `tests/system/conftest.py`

## Prompt

Implement `Architecture → Force-terminal and root timeout` for Hassette. Keep the public inherited shutdown coordinator
as the only report store/return path and put root dependency-wave teardown in the root `_shutdown_body()`. Aggregate
each child report by reverse dependency wave, preserve completed child evidence, record exceptions/timeouts with child
identity, and force only unfinished resources. Wrap the complete root body in `total_shutdown_timeout_seconds`; before
force-finalizing descendants, merge `TOTAL_TIMEOUT` and `FORCED_TERMINAL` into the root report. Then run the existing
terminal fallback in its required order: `handle_stop()`, close event streams, ensure STOPPED/not-ready bookkeeping.
Neither a late child/body completion nor the fallback may overwrite timeout evidence. Add the failing root timeout
report regression before implementation and preserve ordinary shutdown tests.

## Focus

- T03 mechanically moved root work behind the shared coordinator; this task completes report aggregation rather than
  adding another public `shutdown()` wrapper.
- Root waves still shut down dependents before dependencies and run each wave concurrently.
- Total timeout evidence must be stored before coordinator/body cancellation so all shielded joiners receive UNSAFE.
- Event stream closure is mandatory on both clean and timeout paths but is not itself restart-safety evidence.
- Existing system tests read `shutdown_completed`; keep that derived diagnostic behavior without mutable assignment.
- System tests are a regression reference, not a new required local suite for this task.

## Verify

- [ ] FR#3: `uv run pytest tests/unit/resources/lifecycle/test_total_timeout.py tests/unit/core/test_core_coverage.py -q` proves root child failures, wave timeouts, and total timeout retain concrete causes and affected resources.
- [ ] FR#10: `uv run pytest tests/unit/resources/lifecycle/test_total_timeout.py -q` proves root force-terminal evidence is recorded before descendant cancellation and STOPPED bookkeeping.
- [ ] FR#13: `uv run pytest tests/unit/resources/lifecycle/test_total_timeout.py tests/unit/core/test_core_coverage.py -q` proves total timeout returns/stores UNSAFE with total-timeout and force-terminal causes while closing streams.
- [ ] FR#17: `uv run pytest tests/unit/resources/lifecycle/test_total_timeout.py -q` proves late root body completion cannot erase timeout evidence and remains exception-observed.
- [ ] AC#7: `uv run pytest tests/unit/resources/lifecycle/test_total_timeout.py tests/unit/core/test_core_coverage.py -q` passes root total-timeout and ordinary fallback-order regressions.
