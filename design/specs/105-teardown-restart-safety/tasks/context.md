# Context: Teardown Restart Safety

## Problem & Motivation

Hassette currently treats lifecycle bookkeeping as proof that shutdown completed cleanly, even when hooks fail,
children time out, TaskBucket work survives cancellation, or a service task ignores cancellation. A later same-instance
restart can therefore overlap old and new work in one process. The lifecycle entry points also do not consistently
share in-flight initialization or shutdown attempts, so concurrent callers and caller cancellation can interrupt or
bypass the only teardown attempt. This feature adds explicit immutable teardown evidence and admits a new lifecycle
incarnation only after shutdown positively proves restart safety.

## Visual Artifacts

None.

## Key Decisions

1. Keep teardown eligibility separate from `ResourceStatus`. `STOPPED` remains terminal lifecycle bookkeeping, while
   only `TeardownReport.restart_safety` authorizes same-instance initialization.
2. Model completed teardown with a frozen, slotted `TeardownReport`; derive `RestartSafety` from immutable causes so
   contradictory state is impossible.
3. Give every Resource one initialization coordinator task and one shutdown coordinator task. Concurrent callers join
   those tasks through `asyncio.shield()`, so cancelling an awaiter does not cancel framework lifecycle work.
4. Keep lifecycle coordinator and shutdown-body tasks outside TaskBucket ownership. Shutdown cancels TaskBucket work,
   so owning the coordinator in that bucket would create circular self-cancellation.
5. Make public `initialize()` and `shutdown()` final coordinator front doors. Resource, Service, and Hassette provide
   internal bodies for their class-specific work.
6. Reject lifecycle re-entry from the active initialization coordinator, shutdown coordinator, or shutdown body with
   `LifecycleReentryError` before creating, joining, or cancelling another lifecycle task.
7. Require positive teardown evidence. Hook, cleanup, child, TaskBucket, service-task, force-terminal, body-timeout, and
   root-total-timeout failures all add monotonic restart-unsafe evidence.
8. Seal TaskBucket admission before cancellation and final inspection. Rejected coroutines/tasks are closed or
   cancelled and exception-observed, and pending task names are returned deterministically.
9. Retain and observe cancellation-resistant shutdown-body tasks until they actually complete; late evidence may add
   causes but can never restore restart safety.
10. Route `RestartRefusedError` in ServiceWatcher to one fatal outcome: record the reason, directly request root
    shutdown, best-effort emit `CRASHED`, and suppress all later retries through existing process-latched state.
11. Preserve clean same-instance restart, RestartSpec budgets, backoff, cooldown, and readiness reset behavior.
12. Accept that restart refusal cannot kill cancellation-resistant Python work. Process replacement remains the
    embedding host or supervisor's responsibility.

## Constraints & Anti-Patterns

- Do not add app reload/replacement behavior; issue #1689 owns that work.
- Do not claim termination proof for sync-executor threads or arbitrary untracked tasks.
- Do not add a root-wide draining gate, lifecycle generation object, general operation queue, or lifecycle controller.
- Do not add frontend, WebSocket, runtime-query, generated schema, database, configuration, or CLI changes.
- Do not add fresh in-process service replacement or a universal process hard-kill policy.
- Never clear `RestartSafety.UNSAFE` on the same object, including from test-reset helpers.
- Use bounded `asyncio.wait()` rather than `wait_for()` when cancellation acknowledgement is the evidence under test.
- Keep report aggregation pure, immutable, deduplicated, and deterministic.
- Keep lifecycle orchestration in module-level helpers so framework plumbing does not enter `App`'s public surface.
- Preserve hook order, reverse child order, root reverse dependency waves, status values, and status-event schemas.
- Use event gates and entered signals in timing tests; do not use `sleep(0)` as proof that a race boundary was reached.
- Do not edit `CHANGELOG.md`.

## Design Doc References

## Problem — explains how lifecycle bookkeeping currently permits unsafe same-instance overlap.
## Functional Requirements — defines the report, coordinator, evidence, refusal, and watcher contracts.
## Edge Cases — enumerates resistant tasks, failures, concurrency, re-entry, and monotonic evidence cases.
## Operational Lifecycle — defines how coordinator state, teardown reports, and initialization admission interact.
## Acceptance Criteria — maps deterministic unit/integration proof to the functional requirements.
## Key Constraints — limits the safety claim and prohibits broader lifecycle machinery.
## Architecture — specifies report types, lifecycle ownership, evidence collection, root fallback, and watcher refusal.
## Replacement Targets — identifies obsolete flag, boolean, log-only, and unconditional-restart paths to remove.
## Test Strategy — requires deterministic regressions, unit coverage, watcher integration coverage, and full local gates.
## Documentation Updates — requires lifecycle and maintainer documentation plus persona and accuracy reviews.
## Impact — inventories changed files, behavioral invariants, and blast radius.

## Convention Examples

### Immutable lifecycle payload

**Source:** `src/hassette/events/hassette.py:24-46`

```python
@dataclass(slots=True, frozen=True)
class ServiceStatusPayload:
    resource_name: str
    role: ResourceRole
    status: ResourceStatus
    previous_status: ResourceStatus | None = None
```

Use the same frozen, slotted shape for teardown evidence.

### Module-level lifecycle operation

**Source:** `src/hassette/resources/operations.py:63-67`

```python
async def restart(resource: "Resource") -> None:
    resource.logger.debug("Restarting '%s' %s", resource.class_name, resource.role)
    await resource.shutdown()
    await resource.initialize()
```

Extend this module-level pattern rather than adding app-visible framework methods.

### Bounded cancellation evidence

**Source:** `src/hassette/task_bucket/task_bucket.py:323-350`

```python
done, pending = await asyncio.wait(tasks, timeout=self.config_cancel_timeout)
for task in pending:
    self.logger.warning(
        "[%s] task %s refused to die within %.1fs",
        self.unique_name,
        task.get_name(),
        self.config_cancel_timeout,
    )
```

Return the pending names to lifecycle aggregation instead of discarding them after logging.

### Race-safe fatal escalation

**Source:** `src/hassette/core/service_watcher.py:202-220`

```python
self.hassette.record_fatal_reason(
    f"{role} '{name}' restart budget exhausted (PERMANENT)"
)
crashed_event = self.emit_service_status_event(
    name=name,
    role=role,
    status=ResourceStatus.CRASHED,
    previous_status=ResourceStatus.FAILED,
    source_payload=status_payload,
)
await self.hassette.send_event(crashed_event)
```

Record refusal before dispatch for the same reason: event handlers run asynchronously.
Request root shutdown at this decision site before best-effort event delivery; telemetry must not be the only fatal
control path.

### Event-gated lifecycle fixture

**Source:** `tests/unit/resources/lifecycle/conftest.py:35-39`

```python
class HangingChild(Resource):
    async def on_shutdown(self) -> None:
        await asyncio.Event().wait()
```

New race tests should add an entered event and a release event so assertions run only after the target coroutine reaches
the intended boundary.
