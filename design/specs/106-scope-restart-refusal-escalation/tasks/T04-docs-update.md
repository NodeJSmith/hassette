---
task_id: "T04"
title: "Update lifecycle docs for the new restart-refusal decision flow"
status: "planned"
depends_on: ["T03"]
implements: ["FR#6"]
---

## Target Files

- modify: `docs/pages/core-concepts/internals/lifecycle.md`

## Prompt

Read the design doc's "Docs" subsection under `## Approach` (`design/specs/106-scope-restart-refusal-escalation/design.md`) for the exact changes required, and read `docs/pages/core-concepts/internals/lifecycle.md` in full first to match its existing voice and structure.

Make two changes:

1. **State diagram** (the `stateDiagram-v2` block, currently listing transitions like `FAILED --> EXHAUSTED_DEAD : TEMPORARY budget exhausted`): add a new transition line reflecting the new outcome — **from `STOPPED`, not `FAILED`**:

   ```
   STOPPED --> EXHAUSTED_DEAD : timeout-only refusal, confirmed quiescent (TRANSIENT/TEMPORARY)
   ```

   The source state is `STOPPED` because by the time this new path fires, `restart()` has already called `resource.shutdown()`, which drives status to `STOPPED` (via `handle_stop()` or `_force_terminal()`) before `RestartRefusedError` is ever raised — see T02's `VALID_TRANSITIONS[ResourceStatus.STOPPED]` addition, which this transition line documents. Place it near `STOPPED --> [*]`, not near the existing `FAILED --> EXHAUSTED_DEAD` lines (those describe a different, unrelated path — budget exhaustion, which fires before `shutdown()` completes).

2. **"Restart refusal" section**: the current prose states that `ServiceWatcher` treats every `RestartRefusedError` as an unconditional fatal outcome ("records a fatal reason, requests shutdown of the whole process directly... It does not retry, enter cooldown, or attempt another restart for that service"). Replace this with a description of the actual decision flow now implemented by T03:
   - A refusal whose `TeardownReport` contains only timeout-related causes (`CLEANUP_TIMED_OUT`, `TASKS_PENDING`, `SERVE_TASK_PENDING`, `SHUTDOWN_BODY_TIMED_OUT`), for a service with `restart_spec.degrade_on_confirmed_quiescent_refusal` set to `True` (the default for `TRANSIENT`/`TEMPORARY` services), gets a bounded wait — half of `resource_shutdown_timeout_seconds`, since the full value already governed the original teardown attempt — to confirm nothing from the failed teardown is still running.
   - If confirmed, only that service moves to `EXHAUSTED_DEAD` — the rest of the framework is unaffected.
   - Any other refusal (a genuine failure cause, an unconfirmed wait, or a service that opts out via `degrade_on_confirmed_quiescent_refusal=False` — the `PERMANENT` services `BusService`/`SchedulerService`/`SyncExecutorService`, and `WebsocketService` despite being `TRANSIENT`, since it's the framework's sole connection to Home Assistant) still triggers the fatal, root-wide shutdown path exactly as before.

   Keep the existing `!!! warning` block about cooperative cancellation immediately after — it remains accurate and now also explains why the confirmation wait is bounded rather than indefinite (a task that ignores cancellation will never confirm quiescent, so the wait must give up and fall back to root shutdown eventually).

Do not invent new terminology beyond what T03 actually implemented — describe the code as it exists after T03, not an idealized version.

## Verify

- [ ] FR#6: `docs/pages/core-concepts/internals/lifecycle.md`'s state diagram and "Restart refusal" prose accurately describe the classify-wait-degrade-or-escalate flow from T03, including the `PERMANENT`-service exclusion.
- [ ] The docs page still renders correctly — run `uv run mkdocs build --strict` (or equivalent project doc-build check) and confirm no new warnings/errors from the edited page.
