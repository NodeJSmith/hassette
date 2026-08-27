---
task_id: "T03"
title: "Coordinate shared lifecycle attempts"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#4", "FR#5", "FR#6", "FR#7", "FR#14", "FR#15", "FR#16", "FR#17", "AC#4"]
---

## Summary

Replace mutable lifecycle admission flags with one resource-owned initialization task, one shutdown task, and a
retained shutdown-body task. Make public lifecycle methods cancellation-shielded coordinator front doors, split
class-specific work into internal bodies, reject self-re-entry, and migrate diagnostic properties and reset fixtures.
This task establishes ownership and joining; later tasks enrich the class-specific shutdown evidence.

## Target Files

- read: `design/specs/105-teardown-restart-safety/design.md`
- modify: `src/hassette/resources/mixins.py`
- modify: `src/hassette/resources/lifecycle.py`
- modify: `src/hassette/resources/operations.py`
- modify: `src/hassette/resources/base.py`
- modify: `src/hassette/resources/service.py`
- modify: `src/hassette/core/core.py`
- modify: `src/hassette/test_utils/reset.py`
- modify: `tests/unit/resources/lifecycle/conftest.py`
- modify: `tests/unit/resources/lifecycle/test_init.py`
- modify: `tests/unit/resources/lifecycle/test_shutdown.py`
- modify: `tests/unit/resources/lifecycle/test_total_timeout.py`
- modify: `tests/unit/resources/test_shutdown_edge_cases.py`
- modify: `tests/unit/resources/test_service_edge_cases.py`
- modify: `tests/unit/resources/test_lifecycle_transitions.py`
- modify: `tests/unit/core/conftest.py`
- modify: `tests/unit/core/test_logging_service.py`
- modify: `tests/integration/test_lifecycle_propagation.py`
- read: `tests/unit/resources/test_task_bucket_ownership.py`
- read: `tests/unit/resources/test_service_lifecycle.py`

## Prompt

Implement `Architecture → Minimal lifecycle coordinator` while preserving the existing Resource, Service, and Hassette
hook order. Add `_shutdown_task`, `_shutdown_body_task`, and `_teardown_report` ownership to `LifecycleMixin`; derive
`initializing`, `shutting_down`, and `shutdown_completed` as read-only diagnostics. Create/join lifecycle tasks directly
with `asyncio.Task`, install done callbacks that consume exceptions, and shield every external join. Make final public
`Resource.initialize()` and `Resource.shutdown()` coordinator-only and move class-specific behavior into
`_initialize_body()`/`_shutdown_body()` overrides for Resource, Service, and Hassette. `start()` must synchronously check
re-entry/refusal and spawn only a joiner for public `initialize()`; it must not assign `_init_task` or reset shutdown
evidence. `restart()` must require a SAFE report before coordinated initialization. Cancel and boundedly observe an
active initializer before shutdown hooks. Reject calls from `_init_task`, `_shutdown_task`, or `_shutdown_body_task`
with `LifecycleReentryError` before any state change. Retain resistant body tasks and merge late failure evidence
monotonically. Migrate test reset code and constructor-bypassing fixtures instead of adding property setters. Add
event-gated RED tests for the exact concurrency/re-entry races before implementing the coordinator.

## Focus

- Task check-and-assignment must have no intervening `await`; event-loop atomicity is the only synchronization needed.
- A shutdown in progress blocks initialization until its report exists; UNSAFE is sticky, while the first accepted SAFE
  initialization clears the old report/task, reopens TaskBucket, and clears `shutdown_event`.
- Repeated shutdown returns the same stored report and does not rerun hooks.
- Coordinator cancellation is converted to an UNSAFE return only when force evidence was stored first.
- `src/hassette/test_utils/reset.py` may reset only a requested-but-not-started shutdown; it must reject any active
  shutdown task or teardown report on root or descendants.
- Gap: migrate `_init_task` and lifecycle-flag assumptions in `tests/unit/resources/test_lifecycle_transitions.py`.
- Gap: `tests/unit/core/test_logging_service.py` bypasses Resource construction and assigns fields that become derived.
- `tests/unit/core/conftest.py`, `test_total_timeout.py`, and service edge tests also construct/reset lifecycle state
  directly and must be made coordinator-shaped so this intermediate task leaves its affected suite green.
- Do not add a compatibility setter for obsolete mutable admission flags.

## Verify

- [ ] FR#4: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py -q` proves concurrent shutdown callers share one shielded task/report and cancelling one joiner does not cancel teardown.
- [ ] FR#5: `uv run pytest tests/unit/resources/lifecycle/test_init.py tests/unit/resources/test_lifecycle_transitions.py -q` proves direct initialize and start callers share one authoritative initialization task.
- [ ] FR#6: `uv run pytest tests/unit/resources/lifecycle/test_init.py -q` proves initialization waits for active shutdown before evaluating the stored report.
- [ ] FR#7: `uv run pytest tests/unit/resources/lifecycle/test_init.py tests/unit/resources/lifecycle/test_shutdown.py -q` proves initialize, start, and restart reject a pre-existing UNSAFE report without clearing state or starting hooks.
- [ ] FR#14: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py -q` proves callers can inspect the returned report and the read-only current `teardown_report`.
- [ ] FR#15: `uv run pytest tests/unit/resources/lifecycle/test_init.py -q` proves shutdown cancels and observes an active initializer before entering shutdown hooks.
- [ ] FR#16: `uv run pytest tests/unit/resources/lifecycle/test_init.py tests/unit/resources/lifecycle/test_shutdown.py -q` proves every lifecycle front door raises `LifecycleReentryError` from initialization and shutdown bodies without self-join or duplicate task creation.
- [ ] FR#17: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py -q` proves a resistant shutdown body stays retained and exception-observed after external joiners leave.
- [ ] AC#4: `uv run pytest tests/unit/resources/lifecycle/test_init.py tests/unit/resources/lifecycle/test_shutdown.py -q` passes deterministic entered/release-gated concurrency, cancellation, initializer-observation, and re-entry scenarios.
