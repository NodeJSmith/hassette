# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: Only integration tests pin decide-under-lock

Status: open
Recorded: 2026-10-28 (3110)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_changes.py
- tests/unit/core/test_app_lifecycle_service_reload.py

Issue:
`TestApplyChangesLockScope` pins D1's lock release, and it passes on the pre-change code too. If a refactor of `apply_changes` moves `_decide_restart` back outside the app-key lock, no unit test fails. Only the two integration tests in `TestPerInstanceSelectiveRestart` would catch it: the stale plan recreating a stopped instance, and a replacement created over an index its own batch flagged.

Why deferred:
Those integration tests fail on the pre-change code, so the regression doesn't go unnoticed. It also needs a specific refactor to happen at all.

Recommended follow-up:
If the integration tests turn out to be skipped or flaky in CI, add a unit test whose `_plan_reload`/`_should_restart` stub asserts the key's lock is `locked()` when it is called.

Acceptance criteria:
- A unit test fails when `_decide_restart` runs without the key's app-key lock held.

## KI-002: A batch waiting on a busy app-key lock logs nothing

Status: open
Recorded: 2026-10-28 (3110)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_changes.py

Issue:
`apply_changes` waits on each changed key's lock while holding `_change_event_lock` and its earlier restart keys. Nothing is logged while it waits. If a lock holder hangs, config changes stop applying and the log doesn't say why.

Why deferred:
Every action that holds an app-key lock is bounded by the stop or startup deadline (D1's accepting clause), so the wait ends without intervention. The consequence is config applied late, not lost state.

Recommended follow-up:
If a lock holder is ever seen outliving its deadline, log at DEBUG or INFO before acquiring when `AppKeyLock.busy` is true, naming the app key being waited on.

Acceptance criteria:
- A config change blocked behind a held app-key lock leaves a log line naming the key it is waiting on.

## KI-003: An exception while deciding one key drops the whole batch

Status: open
Recorded: 2026-10-28 (3110)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_changes.py

Issue:
If `_should_restart` or `_plan_reload` raises for one key, `apply_changes` raises. The restarts already decided for earlier keys and the `new_apps` autostarts are dropped, and those apps stay on stale config until the next save.

Why deferred:
Not a regression: the pre-change code built every plan before any restart or autostart, so a raise there dropped exactly the same work. Both methods are pure planning code with no I/O, so this takes a bug in that code. The next save recovers it.

Recommended follow-up:
If a decision is ever seen raising in the field, catch it per key inside the `decision` stack, log it with `logger.exception`, release that key, and continue the batch.

Acceptance criteria:
- A decision that raises for one key leaves the other keys' restarts and the `new_apps` autostarts applied, with one logged error naming the key.
