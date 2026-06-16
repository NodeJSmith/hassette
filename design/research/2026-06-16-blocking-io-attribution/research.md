---
proposal: "Fix lossy/incorrect app attribution in blocking-IO detection (Tier 1 watchdog and Tier 2 guard) under concurrent load, where a single-slot execution marker mis-attributes 66% of events to NULL or the wrong app."
date: 2026-06-16
status: Draft
flexibility: Exploring
motivation: "Correctness bug — attribution data is 66% unusable (NULL) and sometimes blames innocent apps. The goal is reliable attribution."
constraints: "Accuracy first, watch overhead. bind/unbind is the executor hot path (every execution). Flag per-execution cost but don't rule out on cost alone."
non-goals: "Changing detection itself (detection works); reworking the daemon-thread watchdog mechanism."
depth: deep
---

# Research Brief: Blocking-IO Attribution Under Concurrent Load

**Initiated by**: Issue 1048 — "Blocking-IO detection: lossy/incorrect app attribution under concurrent load." Of 53 detected events, 35 (66%) have `app_key=NULL` and some are misattributed to innocent apps whose execution marker happened to be "current" when the watchdog sampled the frozen loop.

## Context

### What prompted this

The blocking-IO detection feature shipped recently (PR #1040, merged 2026-06-16, issue #162). It has two tiers:

- **Tier 1 (watchdog)** — an off-loop daemon thread (`hassette-loop-watchdog`) that detects loop freezes by polling a heartbeat timestamp, then reads `executor.current_execution` to name the offending app. `src/hassette/core/loop_watchdog.py:235-275`.
- **Tier 2 (guard)** — monkeypatched blocking primitives (`time.sleep`, `socket.send`, `builtins.open`, etc.) that intercept the call *on the loop thread* and read the same `executor.current_execution` marker via `_resolve_owner()`. `src/hassette/core/block_io_guard.py:266-275`, `:315-330`.

Both tiers attribute through the **same single-slot marker**: `CommandExecutor.current_execution`, a plain instance attribute holding one `ExecutionMarker | None`. Detection is solid; the marker is the attribution weak point.

### Current state

**Marker lifecycle** (all on the event-loop thread):

- **Bind** — `bind_execution_context()` (`src/hassette/core/command_executor.py:484-508`) runs at the top of `execute_handler`/`execute_job` *before* `await self._execute(...)`. It atomically assigns `self.current_execution = ExecutionMarker(app_key, instance_name, execution_id, started_at, instance_index)` (`:501`). `ExecutionMarker` is a frozen dataclass (`:52-76`) so a cross-thread reader never sees a half-built object.
- **Read** — Tier 1 daemon reads it from a *separate OS thread* (`loop_watchdog.py:254`); Tier 2 reads it inline on the loop thread (`block_io_guard.py:268`).
- **Unbind** — `unbind_execution_context()` (`:510-521`) clears `self.current_execution = None` *first*, then resets the contextvar, in the `finally` of `execute_handler`/`execute_job` (`:564`, `:601`).

**Why a plain attribute, not a contextvar:** the daemon watchdog runs on a different OS thread and cannot read another thread's `ContextVar`. The design (`design/specs/074-blocking-io-detection/design.md`) explicitly rejected `CURRENT_EXECUTION_ID.get()` for this reason and chose a thread-visible attribute (Candidate B) over an in-loop heartbeat (Candidate A). That decision is correct and is **not** what this brief proposes to revisit.

**The core design assumption** (stated in the `ExecutionMarker` docstring, `command_executor.py:62-72`): *"While the loop thread is frozen by a blocking call no interleaving occurs, so the marker names exactly the execution that froze it."* This holds **only when the blocking call happens in the same synchronous span as its own `bind`** — i.e., the handler binds, then blocks before ever yielding.

### Why attribution actually breaks (Direct + Inferred)

The single-slot marker reflects "the most recent `bind` not yet unbound." Under concurrent load, multiple handler/job coroutines interleave on one event loop (each listener is dispatched as its own task — `bus_service.py:348-351`; no concurrency semaphore). The marker is overwritten or cleared at `await` boundaries. Three concrete failure modes:

1. **Displacement → wrong app (Supported).** Handler A binds (`marker = A`), `await`s, yields. Handler B runs to bind (`marker = B`, overwriting A) and blocks synchronously. The watchdog reads `B` — correct here. But if A resumes after B unbinds and *A* blocks, the marker is `None` or the next bound execution, not A. The marker names "whoever bound most recently," which is not necessarily "whoever is blocking." This is the misattribution-to-innocent-apps symptom.

2. **Framework / gap blocks → NULL (Direct).** Blocking that happens while no execution is bound — framework internals, transport, or in the gap between one execution's `unbind` (marker cleared to `None`) and the next `bind` — reads `marker is None`. The `BlockingEvent.app_key` is nullable precisely to record these (`telemetry_models.py:376`, `source_tier="framework"`). A large share of the 66% NULL is likely *correctly* NULL (framework stalls), but the data can't distinguish "correctly framework" from "lost attribution." (Inferred — needs the query in Open Questions to confirm the split.)

3. **Sync-executor thread-pool blocks → marker reflects the wrong loop-thread execution (Supported).** Sync handler work runs in `SyncExecutorService`'s `InterruptibleThreadPoolExecutor` via `loop.run_in_executor` (`task_bucket.py:230`). While a worker thread blocks, the *loop thread* is free and may be running a different execution whose marker is bound. Tier 1's thread-id gate and Tier 2's thread-id gate (`block_io_guard.py:208`) intentionally **exclude** worker-thread blocks from attribution (that offload is the sanctioned escape hatch — tests `test_tier2_does_not_flag_worker_thread_sleep`). So this is mostly *correctly* not attributed, but it confirms the marker is a loop-thread-global, not an execution-local, value.

The deterministic test `test_marker_read_during_block_names_blocker_not_next_execution` (`tests/unit/core/test_blocking_io_marker_spike.py:56-101`) and the realistic spike (`:113-180`) **only cover mode where the blocking execution is the currently-bound one**. They do not cover displacement (mode 1) or the bound-but-not-blocking case. The green test suite is necessary but not sufficient — it pins the easy case.

### Key constraints

- **Accuracy first.** The point of the feature is reliable attribution.
- **`bind`/`unbind` is the hot path** — runs on every handler and job execution. New per-execution allocations or contention must be justified.
- **The daemon reads from a separate OS thread.** Any attribution state the Tier 1 watchdog consults must be readable cross-thread (rules out a bare contextvar for Tier 1).
- **Sync work crosses a thread-pool boundary.** Contextvars do **not** propagate across `loop.run_in_executor` unless explicitly copied (`copy_context().run`) — confirmed both by the codebase's own `SYNC_WORKER_CELL` workaround comment (`task_bucket.py:17-32`) and by general Python behavior. This constrains any contextvar-based option for the Tier 2 path that needs to survive into a worker thread.
- Python 3.11–3.14 (`pyproject.toml`) — all contextvars / asyncio APIs available.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Marker storage (single-slot → keyed/stack) | `command_executor.py` (`bind`/`unbind`, `ExecutionMarker`) | Med | Med — hot path; cross-thread read semantics |
| Tier 1 reader | `loop_watchdog.py:254` | Low | Low — change what it samples |
| Tier 2 reader | `block_io_guard.py:268` (`_resolve_owner`) | Low | Low |
| Attribution validation (task identity) | `command_executor.py`, `loop_watchdog.py` | Low | Low — add task-id field |
| Telemetry / NULL split | `telemetry_models.py`, query side | Low | Low — diagnostic only |
| Tests | `test_blocking_io_marker_spike.py`, `test_loop_watchdog.py`, integration telemetry tests | Med | Low — must add the displacement case that's currently untested |

### What already supports this

- `ExecutionMarker` is already a frozen, cross-thread-safe immutable snapshot. Adding a field (e.g., the owning `asyncio.Task` id) is cheap and keeps the atomic-rebind property.
- Tier 1 already snapshots the **loop thread's live frame stack** via `sys._current_frames()[loop_thread_id]` (`loop_watchdog.py:277-303`). That stack is the *ground truth* of what is actually executing during the freeze — it is independent of the marker and is exactly how asyncio debug mode and aiomonitor attribute stalls (see Web Research). This is a strong, already-present signal that attribution can lean on.
- The contextvar `CURRENT_EXECUTION_ID` is already per-task-correct (`context.py:17`); the structlog binding already carries `app_key`. The per-task machinery exists; it's just not readable by the daemon.
- `record_blocking_event` already records framework-attributed (NULL) rows distinctly via `source_tier` (`command_executor.py` / `telemetry_models.py:404-408`). The schema can express "framework vs app" — it's the *resolution* that's lossy, not the storage.

### What works against this

- **`bind`/`unbind` is hot.** A naive stack (list push/pop) adds an allocation and two mutations per execution. A dict keyed by task id adds hashing + entry churn. Either is measurable under high listener fan-out.
- **The daemon cannot read contextvars.** This is the hard constraint that killed the "just use contextvars" instinct in the original design. Any Tier 1 fix must keep a thread-visible structure.
- **A stack does not actually fix displacement.** Stacking nested binds helps for *nested* executions on one task, but Hassette executions are not nested — they're *concurrent tasks* interleaved at `await` points. When A yields and B runs, B's bind is not "nested under" A; A's coroutine is suspended. A naive LIFO stack would pop in the wrong order across tasks. (Inferred — this is why option (b) as literally framed is weaker than it looks; see Option B.)

## Options Evaluated

### Option A: Validate attribution by task identity (stamp the marker with the owning task, and prefer the live loop-thread stack)

**How it works**: Two complementary changes, both small and both attacking the root cause directly.

1. **Stamp `ExecutionMarker` with the owning `asyncio.Task` id** (and keep it a single slot). At `bind`, capture `id(asyncio.current_task())` into the marker. When Tier 1 detects a freeze, it reads the marker **and** reads the currently-running task on the loop via `sys._current_frames()` / the loop's running task. If the marker's task id does not match the task actually executing during the freeze, the marker is *stale by displacement* — the watchdog records the event as **framework/unresolved (NULL) rather than guessing**, and tags it so the NULL is honest ("displaced, could not confirm") instead of silently wrong. This converts "confidently wrong" into "honestly unattributed," which is the correctness win the issue asks for.

2. **Promote the loop-thread stack from diagnostic to attribution signal.** The watchdog already captures `sys._current_frames()[loop_thread_id]` (`loop_watchdog.py:277-303`). The frame stack *is* the code actually running during the freeze — the same mechanism asyncio debug mode and aiomonitor use. When the marker is ambiguous, the stack frames (module `__name__`, filename) can map back to the owning app module, giving a second, marker-independent attribution path. At minimum, surfacing the stack on every Tier-1 event (already stored in `source_location`) lets a human or a follow-up resolver recover the true owner.

**Pros**:
- Directly fixes the "blames innocent apps" symptom: a mismatched task id means the watchdog *stops guessing*. No innocent app gets blamed.
- Keeps the single-slot atomic-rebind design — no stack, no dict, no hot-path allocation churn beyond one extra int field on an already-allocated frozen dataclass.
- The task-id capture is one cheap call (`id(asyncio.current_task())`) at bind time, no new contextvar, no thread-boundary problem.
- The loop-stack signal is already captured; this mostly *uses* data already paid for.
- Works identically for Tier 1 and Tier 2 (Tier 2 can also compare `id(asyncio.current_task())` at the call site against the marker's task id — a perfect match means high-confidence attribution).

**Cons**:
- Does not *recover* attribution in the displacement case by itself — it makes the NULL honest rather than turning more NULLs into correct app keys. (Stack-based resolution can recover some, but that's a fuzzier mapping.)
- Stack-to-app mapping is heuristic (module name → app) and won't cover apps whose blocking call sits in a shared library frame.
- Requires adding the currently-missing displacement test to prove the mismatch path.

**Effort estimate**: Small-to-Medium. The task-id stamp + mismatch check is small. The stack-to-app resolver is the optional medium piece — ship the stamp first.

**Dependencies**: None (stdlib `asyncio`, `sys`).

### Option B: Per-task marker registry (dict keyed by task id), daemon reads the loop's running task

**How it works**: Replace the single-slot `current_execution` with a thread-visible `dict[int, ExecutionMarker]` keyed by `id(asyncio.current_task())`. `bind` inserts, `unbind` removes. When the daemon detects a freeze, it determines which task is *currently running on the loop* (the frozen task) and looks up that task's marker in the dict — giving the true blocker even when other suspended tasks have bound markers.

This is the honest version of the proposal's option (b): not a LIFO stack (which is wrong for concurrent non-nested tasks — see "What works against this"), but a **task-keyed registry**, which is what "stack/history of execution contexts" should mean here.

**Pros**:
- Actually *recovers* correct attribution in the displacement case, not just honest NULLs — the daemon can find the blocking task's own marker.
- Still cross-thread readable (a plain dict attribute, read under the GIL) so Tier 1 keeps working.

**Cons**:
- **The hard part is "which task is frozen?"** During a freeze, `asyncio.Task.get_coro()` and the loop's `_current_handle` are not trivially inspectable from another thread without touching asyncio internals. The reliable cross-thread signal is `sys._current_frames()[loop_thread_id]` — but mapping a frame back to its `asyncio.Task` (to then key the dict) is not a public API and is fragile across Python versions (3.11–3.14). (Inferred — this is the load-bearing risk.)
- Hot-path cost: dict insert/delete + hashing on every execution, plus the dict grows with concurrent in-flight executions. Higher overhead than Option A's single int field.
- More moving parts to get right under shutdown/exception (dict leak if `unbind` is skipped — though `finally` covers it).

**Effort estimate**: Medium-to-Large, almost entirely due to the "identify the frozen task cross-thread" problem.

**Dependencies**: None new, but leans on `sys._current_frames` + possibly non-public asyncio internals.

### Option C ("do less"): Stamp the marker with task id, mismatch → NULL. Ship only the honesty half of Option A.

**How it works**: The minimal slice of Option A part 1. Add `task_id: int` to `ExecutionMarker` (one field). At Tier 1 detection and Tier 2 call sites, if the marker's `task_id` does not equal the task actually executing during the freeze, emit the event as framework/unresolved (NULL) and tag it. Skip the stack-to-app resolver entirely.

**Pros**:
- Smallest possible diff that fixes the *worst* symptom (innocent apps blamed). After this, NULL means "framework or unresolvable," never "wrong app."
- Negligible hot-path cost: one extra int captured at bind, one comparison at detection.
- Trivially testable: the displacement test asserts NULL-not-wrong.

**Cons**:
- Doesn't reduce the NULL rate; it makes NULL trustworthy. If most of the 66% are genuinely framework stalls, this is a complete fix; if many are recoverable app blocks, it leaves attribution on the table.
- Still needs the "which task is running during the freeze" determination for the mismatch check — though for Tier 2 this is free (`asyncio.current_task()` at the call site), and for Tier 1 a coarse check (is *any* task running, or is the loop genuinely idle/framework?) may suffice.

**Effort estimate**: Small.

**Dependencies**: None.

## Concerns

### Technical risks

- **"Which task froze the loop?" is the crux for Tier 1.** Tier 2 has it for free (`asyncio.current_task()` at the synchronous call site, same task as the blocker). Tier 1 reads from outside the frozen task and has only `sys._current_frames()[loop_thread_id]` reliably. Whether that frame can be mapped to an `asyncio.Task` cross-thread, across 3.11–3.14, is the single biggest unknown and gates Option B. Prototype this before committing to B.
- **Contextvars do not cross the sync-executor thread boundary** (confirmed: `task_bucket.py:17-32` works around exactly this; general Python `run_in_executor` does not copy context). Any design that tries to read attribution from inside a worker thread via contextvars will read `None`. The current thread-id gates already exclude worker blocks from attribution, so this mostly means: do **not** introduce a contextvar-based attribution path expecting it to survive into the pool.
- **NULL is overloaded today.** "Framework stall," "displaced/lost," and "gap between executions" all collapse to `app_key=NULL`. Until the marker carries a task-id and a reason tag, the 66% cannot be triaged. The first diagnostic step (Open Questions) should split it.

### Complexity risks

- Option B adds a dict and a cross-thread task-identification step — two new failure modes (dict leak, wrong-task lookup) on the hot path and in the daemon. Option A/C add one immutable field and one comparison.
- Any option must add the **currently-missing displacement test**. The existing spike tests only cover the same-span block; shipping a fix without the displacement test leaves the real bug unpinned.

### Maintenance risks

- Leaning on `sys._current_frames()` and (for B) frame→task mapping ties Tier 1 to CPython internals. Frame inspection is already in the code (`_capture_loop_stack`), so Option A's stack use stays within the existing commitment; Option B deepens it.

## Open Questions

- [ ] **Split the 66% NULL.** Run a query against `blocking_events`: of the 35 NULL rows, how many have a `source_location`/stack that maps to an *app module* vs framework/transport? This decides whether the fix should aim for "honest NULL" (Option C) or "recover attribution" (Option B). Without this, we can't size the prize.
- [ ] **Can the frozen task be identified cross-thread on 3.11–3.14?** Prototype: from the daemon, given `sys._current_frames()[loop_thread_id]`, can we reach the owning `asyncio.Task` (and thus its bound marker) without private-API breakage? This gates Option B.
- [ ] **How often is the blocking call in the same span as its bind?** If nearly always (apps that block synchronously inside a handler before any `await`), the single-slot marker is already correct and Option C alone closes the issue. If apps commonly block *after* an `await`, Option B's recovery is worth more.
- [ ] Confirm whether any of the misattributed-to-innocent-app events are Tier 2 (where `asyncio.current_task()` is available at the call site) vs Tier 1 — Tier 2 misattribution is almost free to fix; Tier 1 is the hard one.

## Recommendation

**Ship Option C first (the "do less"), then decide on B with data.** (Confidence: Supported for the diagnosis; Inferred for the exact fix split, pending the NULL-triage query.)

The issue's worst symptom — *blaming innocent apps* — is a correctness bug that Option C fixes cheaply and completely: stamp `ExecutionMarker` with the owning task id, and when the marker's task isn't the one executing during the freeze, record framework/unresolved instead of guessing. This costs one immutable int on the hot path and one comparison at detection, with no contextvar and no thread-boundary hazard. After it lands, `app_key=NULL` means "framework or honestly unknown," never "wrong app." That alone makes the data trustworthy, which is the stated goal.

For Tier 2 specifically, the task-id check is essentially free and high-confidence (`asyncio.current_task()` is available at the synchronous call site, in the same task as the blocker). Fix Tier 2 attribution in the same change — it may account for a meaningful slice of the misattributions at near-zero cost.

Do **not** start with Option B (the per-task registry). It's the only option that *recovers* lost attribution, but its value is unknown until the NULL-triage query runs, and its feasibility hinges on cross-thread frozen-task identification, which is an unproven CPython-internals dependency. Prototype that identification in a branch *before* committing.

Reject any contextvar-based Tier 1 attribution outright: the daemon cannot read contextvars, and contextvars don't survive the sync-executor boundary. The original design was right to use a thread-visible attribute; this brief refines *what that attribute carries*, not the mechanism.

### Suggested next steps

1. Run the NULL-triage query (Open Question 1) to size the recoverable-vs-framework split. This is the single highest-value next action and unblocks the B-vs-C decision.
2. Implement Option C: add `task_id` to `ExecutionMarker`; add the mismatch→NULL check to Tier 1 (`loop_watchdog.py`) and the same-task confirmation to Tier 2 (`block_io_guard.py`). Add a `reason` tag distinguishing "framework" from "displaced/unresolved" in `BlockingEvent`.
3. Add the **displacement regression test** that the current suite lacks: handler A binds, yields, B binds+blocks, assert the watchdog attributes to B (and, in the reverse arrangement, that a displaced A block is NULL-not-wrong).
4. Prototype cross-thread frozen-task identification (Open Question 2) in a throwaway branch. If it works cleanly across 3.11–3.14, schedule Option B as a follow-up to recover the attributable slice; if not, Option A's stack-to-app heuristic becomes the recovery path.
5. Consider running `/mine.challenge` on the chosen design before implementation — the cross-thread task-identity assumption is exactly the kind of load-bearing claim worth adversarial review.

## Sources

- [Developing with asyncio — slow callback detection (Python 3.14 docs)](https://docs.python.org/3/library/asyncio-dev.html)
- [aiomonitor — task monitor runs in a separate thread, works even when the loop is blocked](https://github.com/aio-libs/aiomonitor)
- [aiomonitor-ng — debugging complex asyncio apps](https://blog.lablup.com/en/posts/2022/11/28/aiomonitor-ng/)
- [aiodebug — log long-running blocking calls, attributes the blocking Task](https://superfastpython.com/asyncio-log-long-running-aiodebug/)
- [Propagating context in Python's thread and process executors](https://medium.com/@srimadhu.j/propagating-context-in-pythons-thread-and-process-executors-48db68a06dfa)
- [Troubleshoot thread-local context loss with ThreadPoolExecutor](https://oneuptime.com/blog/post/2026-02-06-troubleshoot-threadpool-context-loss/view)
