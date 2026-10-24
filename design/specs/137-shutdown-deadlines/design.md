# Design: Shutdown Deadlines on Operations and Stages

**Date:** 2026-10-23
**Status:** built
**Mode:** sketch
**Issues:** #3104

## Summary

Breakdown item 1 of the Resource Lifecycle milestone ledger
(`design/specs/134-resource-lifecycle-outcomes/design.md`). Every decision this build implements is
ratified there (D5's timed-out stop outcome and cause, D10's shutdown row, D18's shutdown-budget,
timeout-merge, app-layer stop timeout and concurrent app shutdown items, and D19 whole); they are
carried into Assumed below, not redrafted. This ledger adds no decisions of its own. A change to one of
them reopens the milestone ledger.

Today `resources/shutdown_budget.py` divides each resource's `resource_shutdown_timeout_seconds` into a
hooks pool, task-cancel and cleanup allocations, a children floor and a coordinator margin, and every
coordinator, child batch, root wave, `AppHandler` hook and the app layer adds its own bound on the same
work. With defaults, `AppHandler.on_shutdown()` (which stops every app sequentially) gets a 2.5s pool, so
a second app whose `on_shutdown` takes 1.5s is cancelled (reproduced by
`tests/unit/core/test_app_handler_shutdown.py`).

The change replaces the allocation with operation-owned deadlines:

- **Deadline carrier** — `LifecycleMixin._shutdown_deadline` (`resources/mixins.py`), an absolute loop
  time on the shutdown attempt. The operation's owner sets it before calling `shutdown()`; a caller
  joining an attempt in flight can only tighten it. Reset when an accepted initialization clears the
  previous attempt (`resources/lifecycle.py`, beside `_shutdown_task = None`).
- **Leaf bounds** — `resources/shutdown_deadline.py` (replacing `shutdown_budget.py`): each user hook,
  the serve-task wait and the initializer observation get `min(shutdown_timeout_seconds, remaining)`;
  the task-cancel stage `min(task_cancellation_timeout_seconds, remaining)`; `cleanup()`
  `min(CLEANUP_SECONDS, remaining)`. A hook cut off by its own bound records the new
  `TeardownCause.SHUTDOWN_HOOK_TIMED_OUT` (`resources/teardown.py`), distinct from a raised hook.
- **Interior nodes** — the coordinator (`_run_shutdown_coordinator`) and `shutdown_batch()`
  (`resources/operations.py`) wait without a bound and pass the deadline to each child.
- **Root stages** — `Hassette._shutdown_body()` / `_shutdown_children()` (`core/core.py`): a stop stage
  (every child but the foundation services) under `total_shutdown_timeout_seconds -
  FOUNDATION_BUDGET_SECONDS`, which on expiry force-terminates what hasn't finished and logs one ERROR
  naming each; then a foundation stage that runs even after a stop-stage expiry: session finalize
  (moved out of `Hassette.before_shutdown()`), `DatabaseService` drain and close, `SyncExecutorService`
  join, then the shutdown snapshot outside the budget. `SessionManager`, `DatabaseService` and
  `SyncExecutorService` are the named foundation services.
- **Apps** — `AppHandler` (`core/app_handler.py`) stops registry apps concurrently in its child stage,
  through `AppLifecycleService`'s instance-stop path, merging their reports; its `_force_terminal()`
  reaches registry apps. App stop leaves `on_shutdown`.
- **Entry deadline** — `AppLifecycleService`'s instance operations (`core/app_lifecycle_instances.py`):
  the stop leg of a runtime stop or reload gets one deadline of the stop stage's length. On expiry it
  walks away, force-terminates the instance, removes its listeners and jobs by owner, reports it FAILED
  with a "timed out" reason and records an `AppRegistry` failure entry. Any timed-out stop is FAILED
  with a registry failure entry (D5).
- **Hard exit** — `Hassette` keeps a force-terminated-work record beside its fatal-reason latch,
  written by the root's stages, by `AppLifecycleService` on entry-deadline expiry and by the
  foundation stage when executor threads survive the join. `hassette.server.main()` (the `hassette run`
  path only) reads it after `run_forever()` and hard-exits after waiting for an in-flight snapshot.
- **Settings** — `LifecycleConfig` (`config/models.py`): `shutdown_timeout_seconds` (per hook, default
  10) replaces `app_shutdown_timeout_seconds` and `resource_shutdown_timeout_seconds`;
  `total_shutdown_timeout_seconds` default 45 with a floor above the foundation budget;
  `sync_executor_shutdown_timeout_seconds` and its validator go. Carried through the dev/prod TOMLs,
  `hassette.schema.json`, `hassette.testing.config`, the frontend config fixture, the Docker compose
  `stop_grace_period` (60s) and the Docker stop-grace test.

Out of scope: init-timeout teardown and the needs-restart flag (issue 6, #3109), outcomes on action
responses (#3111), the reload lock (#3110).

## Posture

Inherited from the milestone ledger's Posture: loud failure, break freely (pre-V1; removed settings
are rejected at load), minimal scope, ship outright, project-default hardening with no silent states.

- **Altitude:** build; this ledger is built in the session that wrote it.

## Decisions

None of its own. The decisions this build implements are the milestone ledger's D5 (timed-out stop
outcome and cause), D10 (shutdown row), D18 (shutdown budget, timeout merge, app-layer stop timeout,
concurrent app shutdown) and D19, listed in Assumed.

## Assumed

- **Milestone D19, whole (ratified).** Operation-owned deadlines: a stop stage and a foundation stage at
  process exit, an entry deadline for runtime instance operations; hooks inline under cancel-and-wait,
  clamped to `min(shutdown_timeout_seconds, what is left)`; interior nodes unbounded; only the root (per
  stage) and `AppLifecycleService` (entry deadline) walk away; the foundation budget is the 5s finalize
  + 5s drain + 10s executor join = 20s; the snapshot runs last, unbounded, after the join; the hard exit
  on `hassette run` only, exit 0 when abandoned work is the only problem; `total_shutdown_timeout_seconds`
  45 (25s stop stage); Docker `stop_grace_period` 60s; three removed settings rejected at load.
  Evidence: milestone ledger D19 Settings, Stop stage, Foundation stage, Entry deadline, Apps and
  Process exit bullets.
- **Milestone D5 (ratified).** A timed-out stop is reported FAILED whether or not work is still pending,
  with an `AppRegistry` failure entry; the resource object itself ends STOPPED; the teardown report
  records a timed-out hook as its own cause. Evidence: milestone ledger D5.
- **Milestone D10 shutdown row (ratified).** Each shutdown hook is cancelled at its own deadline,
  clamped to its operation's deadline. Evidence: milestone ledger D10.
- **Milestone D18 (ratified).** The shutdown budget allocation goes; the app and resource shutdown
  timeouts merge; the app layer's own stop timeout goes; apps stop concurrently at exit, and no app's
  hooks are cut short by other apps' hooks. Evidence: milestone ledger D18 "In the milestone" table.
- Unknown config keys raise `ConfigError` at load, so the removed keys are rejected with no new code.
  Evidence: `check_unknown_keys()` in `config/checks.py`.
- `SessionManager.finalize_session()` reads drop counters from `CommandExecutor`, which needs no
  running service. Evidence: `Hassette.before_shutdown()`'s counters read.
- The snapshot opens its own connection to the database file, so it is safe after the service's
  connections close. Evidence: `write_snapshot` in `core/database_snapshot.py`.
- `TeardownCause` is internal to hassette (no wire, client or frontend reference), so removing
  `TOTAL_TIMEOUT` and `SHUTDOWN_BODY_TIMED_OUT` is not a published change. Evidence: grep of `wire/`,
  `client/`, `frontend/src`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**

- Foundation services opt out of the per-hook timeout via `shutdown_hook_timeout_applies = False`: D19 gives their framework steps fixed caps of their own, which `shutdown_timeout_seconds` would otherwise cut short.
- The DB drain and the executor join clamp their fixed caps (`SHUTDOWN_DRAIN_TIMEOUT_SECONDS`, `SYNC_EXECUTOR_JOIN_TIMEOUT_SECONDS`) to the foundation stage's deadline: they are leaves, and a session finalize that ran long must not push them past the stage's walk-away.
- `shutdown_batch()` takes an explicit `deadline` keyword so the foundation stage passes its own deadline rather than the root's stop-stage deadline.
- Runtime instance stops in `shutdown_instances()` run concurrently, the same path exit uses.
- A raised (not timed-out) `on_shutdown` still reports STOPPED: D5 covers timed-out stops only, and outcomes for raised hooks belong to #3111.
- `EX_CONFIG` moved to `hassette.server` so the hard exit maps exit codes the same way `hassette run` does.
- Session finalize moved from `Hassette.before_shutdown()` into the foundation stage, so it runs even when the stop stage timed out.
- `AppHandler._force_terminal()` names and records the registry apps whose stop hadn't finished: at exit the root's stage timer and an app's own stop deadline are the same instant, and the root's path is the one that reliably runs, so D19's "registry apps included" lives there.
- `SessionManager` keeps `shutdown_hook_timeout_applies = False` though it has no hooks: a test pins "foundation service ⇔ opt-out flag", and the rule stays symmetric for any hook added later.
- Concurrent instance stops await every sibling before re-raising (`gather_all()`), so a stop that raises never leaves another running detached.
- The entry-deadline walk-away bounds its registration cleanup with `failed_instance_cleanup_timeout_seconds`, the same bound failed-init cleanup uses.
