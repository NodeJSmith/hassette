---
task_id: "T01"
title: "Define the teardown safety contract"
status: "done"
depends_on: []
implements: ["FR#2", "FR#8", "FR#14"]
---

## Summary

Add the immutable types and typed errors that carry teardown safety evidence through the framework. The report must
derive restart safety from its causes, merge evidence without mutation, and expose deterministic bounded details to
callers. Export only the public data types and errors, leaving coordinator helpers internal.

## Target Files

- read: `design/specs/105-teardown-restart-safety/design.md`
- read: `src/hassette/events/hassette.py`
- create: `src/hassette/resources/teardown.py`
- modify: `src/hassette/exceptions.py`
- modify: `src/hassette/resources/__init__.py`
- create: `tests/unit/resources/test_teardown.py`

## Prompt

Implement the `Architecture → Teardown report` and `Implementation Preferences` sections. Define `RestartSafety`,
`TeardownCause`, and frozen/slotted `TeardownReport` in `src/hassette/resources/teardown.py`. Add the smallest pure
constructor/merge helpers needed by later tasks; preserve insertion order while deduplicating every tuple, return new
reports, derive `restart_safety`, and never copy exception tracebacks into the report. Add `RestartRefusedError` carrying
`resource_name` and the exact report plus `LifecycleReentryError` in `src/hassette/exceptions.py`. The refusal message must
include causes and populated bounded detail fields. Re-export teardown data types from `hassette.resources`, but do not
export coordinator helpers. Write deterministic unit tests before implementation and confirm they fail for the absent
contract before making them pass.

## Focus

- Match the frozen, slotted payload convention in `src/hassette/events/hassette.py`.
- `None` means no completed teardown; the report has only SAFE and UNSAFE final states.
- Parent aggregation must be able to merge child causes/details and then add a parent-specific cause in later tasks.
- Keep imports arranged to avoid the existing `base.py`/`operations.py` circular dependency.
- Error messages are supporting observability; tests should primarily assert typed fields and report identity.

## Verify

- [ ] FR#2: `uv run pytest tests/unit/resources/test_teardown.py -q` proves safety is derived from causes and immutable merges cannot remove negative evidence.
- [ ] FR#8: `uv run pytest tests/unit/resources/test_teardown.py -q` proves `RestartRefusedError` retains resource identity and the exact teardown report with useful bounded details.
- [ ] FR#14: `uv run pytest tests/unit/resources/test_teardown.py -q` proves Python callers can import and inspect the public teardown types and typed errors.
