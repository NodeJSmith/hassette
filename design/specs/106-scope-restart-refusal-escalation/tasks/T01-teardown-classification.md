---
task_id: "T01"
title: "Add timeout-only classification to TeardownReport"
status: "done"
depends_on: []
implements: ["FR#1", "AC#1"]
---

## Target Files

- modify: `src/hassette/resources/teardown.py`
- modify: `tests/unit/resources/test_teardown.py`

## Prompt

Read the design doc's "Classify the refusal" subsection under `## Approach` (`design/specs/106-scope-restart-refusal-escalation/design.md`) for full rationale.

In `src/hassette/resources/teardown.py`:

1. Add a module-level constant, placed near the `TeardownCause` class definition:

   ```python
   TIMEOUT_ONLY_CAUSES: frozenset[TeardownCause] = frozenset({
       TeardownCause.CLEANUP_TIMED_OUT,
       TeardownCause.TASKS_PENDING,
       TeardownCause.SERVE_TASK_PENDING,
       TeardownCause.SHUTDOWN_BODY_TIMED_OUT,
   })
   ```

   Add a docstring-style comment (or class-level note) explaining these are the causes where a task might simply still be finishing up, as opposed to every other `TeardownCause` value, which represents an actual failure or a child's own unsafe report.

2. Add a property to `TeardownReport`, next to the existing `is_restart_safe` property:

   ```python
   @property
   def is_timeout_only_refusal(self) -> bool:
       """True when every recorded cause is a timeout-only cause (see TIMEOUT_ONLY_CAUSES).

       False when there are no causes at all (nothing to classify — use is_restart_safe for
       that case) or when any recorded cause falls outside the timeout-only set.
       """
       return bool(self.causes) and all(cause in TIMEOUT_ONLY_CAUSES for cause in self.causes)
   ```

In `tests/unit/resources/test_teardown.py`, add tests (follow the existing file's structure and fixtures — read the file first to match its conventions):

- A `TeardownReport` with only `causes=(TeardownCause.CLEANUP_TIMED_OUT,)` → `is_timeout_only_refusal` is `True`.
- A `TeardownReport` with `causes=(TeardownCause.TASKS_PENDING, TeardownCause.SERVE_TASK_PENDING)` (multiple timeout-only causes) → `is_timeout_only_refusal` is `True`.
- A `TeardownReport` with `causes=(TeardownCause.CLEANUP_TIMED_OUT, TeardownCause.CLEANUP_FAILED)` (one timeout-only cause mixed with one non-timeout cause) → `is_timeout_only_refusal` is `False`.
- A `TeardownReport` with `causes=(TeardownCause.FORCED_TERMINAL,)` (a purely non-timeout cause) → `is_timeout_only_refusal` is `False`.
- A default `TeardownReport()` (no causes, `is_restart_safe` is `True`) → `is_timeout_only_refusal` is `False`.

## Verify

- [ ] FR#1: `TeardownReport.is_timeout_only_refusal` exists and correctly classifies timeout-only vs. mixed vs. non-timeout vs. empty cause sets.
- [ ] AC#1: `uv run pytest tests/unit/resources/test_teardown.py -v` passes, including the new cases above.
