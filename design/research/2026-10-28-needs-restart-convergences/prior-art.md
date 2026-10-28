---
topic: "Shutdown evidence after an abnormal teardown body, and the process-exit hard-exit trigger"
date: 2026-10-28
status: Draft
---

# Prior Art: Abnormal Teardown Evidence and the Hard-Exit Trigger

## The Problem

PR #3550's review converged on two mechanisms, each raised in more than one round.

1. **A shutdown body that ends abnormally loses its evidence.** When `_shutdown_body()` raises or is cancelled, `_run_shutdown_coordinator` (`src/hassette/resources/lifecycle.py`) replaces whatever it had collected with a bare `SHUTDOWN_BODY_FAILED` report. That cause isn't in `WORK_MAY_RUN_CAUSES` (`src/hassette/resources/teardown.py`), so the instance reads restart-safe and isn't flagged. A routine user hook reaches this: an `on_shutdown` that does `task.cancel(); await task` lets `CancelledError` escape, `run_hooks` re-raises it, and the task-bucket and child stages never run. This was accepted as KI-001 on the premise that only a framework bug reaches it. That premise doesn't hold.
2. **The hard exit reads a hand-kept list.** `exit_now_if_work_force_terminated` (`src/hassette/server.py`) calls `os._exit` only when `Hassette.force_terminated_work` is non-empty. Four sites write that list (stage deadlines, surviving executor threads, entry-deadline walk-aways, `AppHandler`'s exit). It can name work that finished long ago (134 F7, accepted). It also misses pending tasks of a flagged instance that no deadline owner walked away from (CodeRabbit on #3550).

Both live inside spec 134's milestone, which already plans to shrink `TeardownReport`. #3395 replaces its evidence tree with a small outcome: a result, the names of work still running, and a reason.

## How We Do It Today

- **Mechanism 1.** The coordinator drops `pending_tasks`, child reports and hook causes when the body raises or is cancelled. It keeps only `SHUTDOWN_BODY_FAILED` plus `INITIALIZATION_TASK_PENDING` if relevant. `run_hooks` (`src/hassette/resources/operations.py`) logs a user hook's `CancelledError` and always re-raises it, in both init and shutdown modes. A plain `Exception` is collected when `continue_on_error` is set.
- **Mechanism 2.** `_force_terminated_work` is a list on `Hassette`. Nothing records a resource whose body failed. 134 D19 ratified the hard exit "when work was force-terminated or executor threads survive", and accepted F7's staleness.

## Patterns Found

### Pattern 1 (M1): Later teardown stages always run; leftovers are logged

**Used by:** Home Assistant core `async_stop`, AppDaemon `terminate_app`, CPython `Runner.close`, Node-RED node close.

**How it works:** Each stage is bounded or wrapped in `try/finally`. An error or timeout in one stage logs and moves on to the next. AppDaemon catches only `Exception` around the user's `terminate()`, and its `finally` still cancels the app's futures and clears its callbacks, services and scheduler entries. So a raised or cancelled `terminate()` doesn't leak framework-owned work. Evidence is log text, such as HA's `_async_log_running_tasks` at a stage boundary, not a structured record of which stages ran.

**Strengths:** No new state. Removes the leak instead of describing it.

**Weaknesses:** Can't help a task that swallows cancellation, or a thread.

**Example:** https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/appdaemon/app_management.py ; https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/core.py

### Pattern 2 (M1): Tell a stray `CancelledError` from one aimed at you

**Used by:** asyncio and anyio guidance, and HA's stage 4, which has separate `CancelledError`, `TimeoutError` and `Exception` arms.

**How it works:** Since Python 3.11, `Task.cancelling()` counts pending cancel requests against the current task. If a hook's `CancelledError` arrives while `cancelling() == 0`, it came from an awaited child that was cancelled, not from the caller. It can then be treated like any other hook failure: logged, with teardown continuing. A real cancellation (`cancelling() > 0`) still propagates. The asyncio docs call swallowing a real cancellation "actively discouraged". Awaiting cleanup after a real cancellation needs shielding (`CancelScope(shield=True)` in anyio).

**Strengths:** Fixes the user-hook path at its source without swallowing real cancellation.

**Weaknesses:** It's subtle, and needs a test for each of the two cases.

**Example:** https://docs.python.org/3/library/asyncio-task.html ; https://anyio.readthedocs.io/en/stable/cancellation.html

### Pattern 3 (M1): Treat an abnormal teardown as "possibly still running"

**Used by:** HA, where a raised unload is non-recoverable (see `design/research/2026-10-27-needs-restart-ship-findings/prior-art.md`). AppDaemon and uvicorn cancel whatever is still attributable to the component.

**How it works:** A teardown that didn't finish normally proves nothing about its work, so the conservative verdict applies. No peer carries per-stage evidence to refine that verdict.

**Strengths:** One rule, no evidence plumbing.

**Weaknesses:** It flags some instances whose work did end. That costs a restart.

### Pattern 4 (M2): Derive survivors from the runtime at exit

**Used by:** Home Assistant core, AppDaemon and uvicorn.
- HA's `_cancel_all_tasks_with_timeout` waits 5 s on `asyncio.all_tasks()`, logs "Task could not be canceled and was still running after shutdown", and continues.
- HA's `deadlock_safe_shutdown` replaces `threading._shutdown` and joins non-daemon threads on a 10 s budget.
- AppDaemon waits 3 s, cancels, then waits 3 s more.

**How it works:** At exit, list `asyncio.all_tasks()` and the non-daemon threads, cancel or join each with a timeout, and log every survivor. No peer keeps a list of force-terminated names. The list is built at the moment of exit, so it can't go stale or miss leaked work.

**Strengths:** Answers both the staleness (F7) and the gap (CodeRabbit). HA's task helper is about 20 lines.

**Weaknesses:** Survivors can still hang interpreter exit unless something kills the process.

**Example:** https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/runner.py ; https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/util/thread.py

### Pattern 5 (M2): The supervisor enforces the final deadline

**Used by:**
- systemd `TimeoutStopSec`, then SIGKILL
- Docker stop
- Celery: warm shutdown, then cold, then KILL
- uvicorn: `force_exit` on a second SIGINT
- gunicorn `graceful_timeout`: not verified, the docs fetch failed

**How it works:** The process does its best-effort graceful stop, and the supervisor escalates. None of the HA files fetched calls `os._exit`. Only those files were searched, not all of HA core.

**Strengths:** No custom exit logic.

**Weaknesses:** An unsupervised `hassette run` in a terminal can hang until Ctrl+C.

**Example:** https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html ; https://docs.celeryq.dev/en/stable/userguide/workers.html

### Pattern 6 (M1, M2): Accept and document

**Used by:**
- Node-RED: a close timeout logs and continues.
- pyscript: running tasks survive a reload.
- CPython `asyncio.run`: a cancellation-swallowing task hangs it forever.
- Celery: warm shutdown waits forever.

**How it works:** Log, continue, and tell authors to re-raise `CancelledError`.

**Example:** https://nodered.org/docs/creating-nodes/node-js ; https://github.com/custom-components/pyscript/issues/103

## Anti-Patterns

- **Hand-maintained force-terminated name lists.** No peer uses one; they all derive survivors at exit.
- **`except Exception`-only teardown around user hooks with cleanup after the `await`.** `CancelledError` skips everything that isn't in `finally`. That is exactly how a user hook's `task.cancel(); await task` skips hassette's later stages.
- **Unbounded `gather` on cancelled tasks at exit** (stdlib `Runner._cancel_all_tasks`). One task that swallows cancellation hangs the process, which is why HA rewrote it with a timeout.

## Relevance to Us

- **Mechanism 1, keeping completed-stage evidence.** This builds more machinery than any peer: no peer carries a per-stage evidence record, and #3395 is deleting the tree that evidence would live in. The two small peer patterns both survive #3395:
  - Pattern 3: an abnormal body means "work may still be running". In #3395's shape that is `result=failed` with unknown leftovers.
  - Pattern 2: a stray `CancelledError` from a user hook doesn't abort the framework's stages.

  Pattern 2 also closes the leak for the common case rather than only flagging it, which is what AppDaemon's `finally` achieves.
- **Mechanism 2, CodeRabbit's fix.** It adds a fifth writer to the list that Pattern 4 says shouldn't exist. Deriving survivors at exit replaces the list and answers both F7 and CodeRabbit. It changes D19's ratified trigger, though, and it touches `server.py`'s exit path. That is outside #3109's scope. Its natural home is #3395, whose outcome already carries "names of work still running", or a follow-up in this milestone.

## Recommendation

- **Mechanism 1, in this PR:** add `SHUTDOWN_BODY_FAILED` to `WORK_MAY_RUN_CAUSES` (Pattern 3). It's one line, it's peer-backed (HA's raised unload is non-recoverable), it covers every abnormal-body path including CodeRabbit's raising `_shutdown_children`, and it maps directly onto #3395's outcome. Close KI-001, and add a 134 addendum noting that D18's "a raised body has ended" premise no longer holds.
  - Don't preserve evidence inside the body.
  - Optionally, also take Pattern 2 in `run_hooks`: a hook's `CancelledError` while `Task.cancelling() == 0` is handled as a hook failure. That keeps a routine `task.cancel(); await task` from skipping cleanup. It's small and stdlib-recommended, but it changes lifecycle cancellation semantics, so it is a separate decision, not a requirement of this PR.
- **Mechanism 2:** decline CodeRabbit's extra writer. Record it as a known issue next to 134 F7, and fold "derive survivors from `all_tasks()` and non-daemon threads at exit, bounded, then hard-exit only if anything survives" into #3395 or a milestone follow-up. Until then, the supervisor's kill is the backstop, which is what HA relies on.

**Coverage gaps:**
- NetDaemon not found.
- No peer won't-fix issues located.
- gunicorn wording not verified.
- The last part of HA's `core.py` was unread. Whether a stray `CancelledError` from a stop listener aborts HA's later stages is unconfirmed.
- Page summaries came from a fetch tool. Check the cited lines before quoting them in a ledger.

## Sources

URLs were not live-verified.

### Reference implementations
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/runner.py — `_cancel_all_tasks_with_timeout`, survivors logged at exit
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/util/thread.py — `deadlock_safe_shutdown` replacing `threading._shutdown`
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/util/executor.py — executor join, then SystemExit injection into survivors
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/core.py — `async_stop` staged teardown
- https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/appdaemon/app_management.py — `terminate_app` with `finally` cleanup
- https://raw.githubusercontent.com/python/cpython/main/Lib/asyncio/runners.py — `Runner._cancel_all_tasks`, unbounded
- https://raw.githubusercontent.com/encode/uvicorn/master/uvicorn/server.py — graceful timeout, `force_exit`

### Blog posts & writeups
- https://github.com/python/cpython/issues/113148 — interpreter hang on non-daemon threads at exit
- https://github.com/custom-components/pyscript/issues/103 — tasks surviving reload

### Documentation & standards
- https://docs.python.org/3/library/asyncio-task.html — `CancelledError`, `cancelling()`/`uncancel()`
- https://anyio.readthedocs.io/en/stable/cancellation.html — shielded cleanup
- https://appdaemon.readthedocs.io/en/latest/internals/lifecycle.html — AppDaemon lifecycle
- https://nodered.org/docs/creating-nodes/node-js — close timeout behaviour
- https://docs.celeryq.dev/en/stable/userguide/workers.html — warm/cold shutdown
- https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html — `TimeoutStopSec`
