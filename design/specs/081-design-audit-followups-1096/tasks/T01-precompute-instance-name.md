---
task_id: "T01"
title: "Precompute instance_name to drop the executor hot-path lookup"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "AC#1", "AC#9"]
---

## Summary
The command executor resolves `instance_name` for logging by calling `hassette.app_handler.get(...)`
on every single handler/job execution — a cross-layer registry traversal on the hot path. This task
precomputes `instance_name` once at registration time (when the owning app instance is already in
scope) by adding a field to `ListenerIdentity` and `ScheduledJob`, then threads that value into
`CommandExecutor.bind_execution_context` so the per-execution `app_handler.get(...)` call is removed.
Logging and telemetry output must be byte-for-byte identical — only the resolution point moves.

## Target Files
- modify: `src/hassette/bus/listeners.py` — add `instance_name: str | None = None` to `ListenerIdentity`. NOTE: the `ListenerIdentity(...)` at `:614` is inside `create_cancel_listener`, a `source_tier="framework"` factory with no app instance in scope — leave `instance_name` at its `None` default there; it is NOT an app-registration site
- modify: `src/hassette/bus/bus.py` — populate `instance_name` at the real app-listener `ListenerIdentity(...)` registration construction (`:593`)
- modify: `src/hassette/scheduler/classes.py` — add `instance_name: str | None = None` field to `ScheduledJob`
- modify: `src/hassette/scheduler/scheduler.py` — populate `instance_name` at the `ScheduledJob(...)` construction (`:452`)
- modify: `src/hassette/core/command_executor.py` — change `bind_execution_context` (`:491-524`) to receive/read the precomputed `instance_name` and drop the `app_handler.get(...)` call (`:497`); update its callers `execute_handler`/`execute_job` to pass it
- modify: `src/hassette/test_utils/helpers.py` — `ListenerIdentity(...)` construction (`:517`) — supply/accept the new defaulted field
- modify: `src/hassette/test_utils/web_helpers.py` — `ScheduledJob(...)` construction (`:275`) — supply/accept the new defaulted field
- create: `tests/unit/core/` (or extend an existing executor test file) — test that `bind_execution_context` binds the right `instance_name` and does not call `app_handler.get`
- read: `design/specs/081-design-audit-followups-1096/design.md` — Architecture item 1
- read: `design/specs/081-design-audit-followups-1096/tasks/context.md`

## Prompt
Implement item 1 from the design (`## Architecture` → "1. Precompute `instance_name` (T9 — hot path)").

1. Add `instance_name: str | None = None` to `ListenerIdentity` (`src/hassette/bus/listeners.py`, the
   `@dataclass(slots=True)` at `:44`) and to `ScheduledJob` (`src/hassette/scheduler/classes.py`).
   Both are slotted/ordered dataclasses with `app_key`/`instance_index` defaults — add the new field
   consistently with a default so direct test constructions stay valid.
2. At each real **app-listener / app-job** registration construction site, resolve the owning app
   instance's `app_config.instance_name` and pass it in:
   - `src/hassette/bus/bus.py:593` (`ListenerIdentity(...)` — the app-listener registration path)
   - `src/hassette/scheduler/scheduler.py:452` (`ScheduledJob(...)`)
   Resolve it the same way the executor does today — from the app instance reachable via the
   `app_key`/`instance_index` in scope at registration. If the app instance is not resolvable at a
   given site, set `instance_name=None` (matching today's miss behavior — see Focus).
   Do NOT plumb an app instance into `src/hassette/bus/listeners.py:614`
   (`create_cancel_listener`): it is `source_tier="framework"` with no `app_key`/`instance_index`/app
   instance — `instance_name` is `None` there by definition; the field default covers it.
3. Change `CommandExecutor.bind_execution_context` (`src/hassette/core/command_executor.py:491-524`):
   its current signature is `(self, app_key: str | None, instance_index: int)`. Remove the
   `self.hassette.app_handler.get(app_key, instance_index)` lookup (`:497`) and the
   `instance_name = app_inst.app_config.instance_name` resolution. Instead accept the precomputed
   `instance_name` — add an `instance_name: str | None` parameter — and bind it directly into the
   structlog context vars and `ExecutionMarker`. Update both callers — `execute_handler` (`:541-542`)
   and `execute_job` (`:584`) — to read `instance_name` off the command's listener/job and pass it in.
4. Update the test-helper construction sites (`src/hassette/test_utils/helpers.py:517`,
   `src/hassette/test_utils/web_helpers.py:275`) so they still construct valid objects.
5. Add a unit test (in the executor/core unit test area) asserting that after `bind_execution_context`
   runs for a command with a known `instance_name`, the bound structlog context and `ExecutionMarker`
   carry that `instance_name`, AND that `hassette.app_handler.get` is **not** called during the bind
   (spy/mock on `app_handler.get` and assert `not called`).

Follow repo conventions in context.md (no `from __future__`, `X | None` not `Optional`, no lazy
imports). Keep the structlog binding and `ExecutionMarker` construction otherwise unchanged.

## Focus
- Before editing, grep `ListenerIdentity(` and `ScheduledJob(` across `src/hassette` to confirm no
  fourth construction site was missed beyond the ones named here (`bus.py:593`, `listeners.py:614`,
  `scheduler.py:452`, and the two test helpers). Planning found these five; verify at impl time.
- `bind_execution_context` currently receives scalars, not the command object. The precomputed value
  must be threaded as a new parameter from the callers, which DO have the listener/job in scope.
- **Edge case (must match today):** when `app_key == ""` or the app instance isn't registered yet,
  the current code's `app_handler.get(...)` returns `None` → `instance_name` is `None`. The precompute
  path must produce the same `None` in those cases — do not raise. Check whether any registration runs
  before the app instance exists; if so, `None` at registration is correct and unchanged from today.
- `scheduler/classes.py` has a docstring note (~`:226`) that "direct `ScheduledJob(...)` constructions
  in tests remain valid; the real resolution happens [elsewhere]" — keep that invariant; the new field
  must default so test constructions don't break.
- Behavioral invariant: per-execution structlog context and `ExecutionMarker` values must be identical
  to before. The new test pins this.
- Blast radius: this is an app-facing hot path (every handler/job execution). The risk is a subtle
  difference in the bound `instance_name`; the test guards it.

## Verify
- [ ] FR#1: `ListenerIdentity` and `ScheduledJob` each carry an `instance_name` field populated at registration time from the owning app instance.
- [ ] FR#2: `bind_execution_context` resolves `instance_name` from the passed-in precomputed value and contains no `app_handler` lookup.
- [ ] FR#3: A test confirms the bound structlog context and `ExecutionMarker` carry the same `app_key`/`instance_name`/`instance_index` as before.
- [ ] AC#1: A test asserts the expected `instance_name` is bound AND `app_handler.get` is not called during `bind_execution_context`.
- [ ] AC#9: The affected unit/integration suites pass for this task; core change — the branch-level `nox -s system`/`nox -s e2e` gate is green before push.
