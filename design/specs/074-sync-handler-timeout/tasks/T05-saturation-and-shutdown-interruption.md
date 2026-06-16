---
task_id: "T05"
title: "Add saturation warnings and shutdown interruption behavior"
status: "done"
depends_on: ["T03", "T04"]
implements: ["FR#4", "FR#6", "FR#7", "AC#3", "AC#4", "AC#5", "AC#6"]
---

## Summary
Give `SyncExecutorService` its runtime behavior: a two-trigger pool-saturation warning (a submission-time check plus a periodic probe in `serve()`, because a submission-only check goes silent exactly when the pool is fully starved) and the end-to-end shutdown interruption (Python-level workers interrupted within budget, C-blocked workers logged and abandoned at budget expiry). Now that routing (T04) exists, real worker threads can be produced, so this task carries the integration tests for both saturation and shutdown. Also document the `SystemExit`/`finally` contract.

## Prompt
1. **Submission-time saturation check** — in `TaskBucket.run_in_thread` (or a helper the service exposes), after submitting work, compute active-vs-ceiling occupancy from the dedicated executor and emit a rate-limited WARNING when it crosses ~75%. Mirror the **write-queue** capacity-warning pattern in `command_executor.enqueue_record` (`command_executor.py:328-346`), which rate-limits with a single global timestamp (`_last_capacity_warn_ts`) and the `_CAPACITY_WARN_THRESHOLD`/`_CAPACITY_WARN_RATE_LIMIT_SECS` constants — pool saturation is a global condition, so use the global-timestamp model, NOT the per-entity dict in `log_timeout_rate_limited` (`:290-326`). Active-worker count is an approximation from the executor's accounting — comment it as such.

2. **Periodic probe** — fill in the `serve()` loop extension point left by T03: every ~30s, read pool occupancy and emit the same rate-limited WARNING while saturation persists, yielding to `shutdown_event` between cycles. The probe is the live "8/8 workers stuck" signal when submissions have stopped. Add a co-located code comment at the probe and at the rate-limit constant tying the two together: the probe cadence must be ≥ the rate-limit suppress window, or the probe self-suppresses and the operator sees nothing. Picking a probe interval shorter than the suppress window silently couples the two — the comment is what prevents a future maintainer from doing that.

3. **Shutdown interruption** — ensure the service's shutdown hook (from T03) calls `self.executor.shutdown(timeout=budget)` where `budget` is `sync_executor_shutdown_timeout_seconds` (capped at the remaining total shutdown budget if the lifecycle tracks one). The `InterruptibleThreadPoolExecutor` (T01) handles join-then-`async_raise(SystemExit)` with the straggler stack logged. Verify the whole shutdown completes within `total_shutdown_timeout_seconds` even with C-blocked workers.

4. **Document the `SystemExit`/`finally` contract** — add a note to the user-facing docs (sync vs async handlers / execution timeouts page under `docs/pages/`) that a worker interrupted at shutdown runs its `finally`/`__exit__` blocks before terminating, so `finally` is not proof of clean completion. Also document the two new config fields. Run `doc-persona-review` and `doc-accuracy-review` on any touched `docs/pages/` slugs per `.claude/rules/doc-rules.md`.

Integration tests (use the project's `asyncio.Event` gate pattern from CLAUDE.md to hold workers across boundaries):
- Saturation: with the pool near ceiling, a submission emits the rate-limited WARNING; it does not spam every submission. With all workers blocked and submissions stopped, the periodic probe still emits the WARNING.
- Shutdown / Python-level: a worker running a pure-Python busy loop at shutdown is interrupted within the budget; its name and stack are logged; shutdown completes.
- Shutdown / C-blocked: a worker in `time.sleep(...)` at shutdown is logged and abandoned at budget expiry; total shutdown still completes within `total_shutdown_timeout_seconds`.
- Config: a non-default `sync_executor_max_workers` and `sync_executor_shutdown_timeout_seconds` change behavior; defaults apply when unset.

Run affected files with `uv run pytest <files> -v` (never `-n auto`). Because this touches `src/hassette/core/`, also run `uv run nox -s system` before the task is considered done (do not run e2e here unless a UI surface changed).

## Focus
- The periodic probe lives in the `SyncExecutorService.serve()` loop created in T03 — extend it, don't add a second background task.
- `InterruptibleThreadPoolExecutor.shutdown(timeout=...)` is from T01; this task wires the configured budget into it and tests the end-to-end behavior, it does not re-implement the interrupt loop.
- Total-pool-starvation is a real failure shape (all sync handlers for all apps stall, queue grows unbounded until a slot frees or shutdown). The probe is the operator's recovery signal; recourse is raising `sync_executor_max_workers` or fixing/async-ifying the handler. This is intended, contained-not-smaller behavior — see the design's Edge Cases.
- C-blocked threads cannot be interrupted; the budget cap is what prevents shutdown from hanging on them.
- Keep saturation logging at WARNING with rate-limiting — do not log on every submission.

## Verify
- [ ] FR#4: a rate-limited saturation WARNING fires when the dedicated pool nears its ceiling, via both the submission-time check and the periodic probe.
- [ ] AC#3: the saturation WARNING is rate-limited (not emitted on every submission) and the periodic probe still fires when submissions have stopped.
- [ ] FR#6: a Python busy-loop worker alive at shutdown is interrupted within the budget, with its name and stack logged.
- [ ] AC#4: shutdown completes after interrupting a Python-level worker; the process/shutdown path exits cleanly.
- [ ] FR#7: shutdown interruption never raises out of the shutdown path and respects the budget.
- [ ] AC#5: a C-blocked worker at shutdown is logged and abandoned at budget expiry; total shutdown completes within `total_shutdown_timeout_seconds`.
- [ ] AC#6: custom `sync_executor_max_workers` and `sync_executor_shutdown_timeout_seconds` change behavior; defaults apply when unset.
