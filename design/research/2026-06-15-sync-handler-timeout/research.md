---
proposal: "Enforce timeouts on sync handlers by interrupting the worker thread (HA's async_raise pattern), so a timeout bounds real execution time instead of only cancelling the await."
date: 2026-06-15
status: Draft
flexibility: Leaning
motivation: "Timeouts on sync handlers are believed to be a no-op: asyncio.timeout cancels the coroutine but the worker thread keeps running and holds a pool slot."
constraints: "Must not corrupt the shared thread pool; must not inject exceptions into the wrong callable; honest about C-level blocking limits."
non-goals: "CPU-bound interruption guarantees; two-tier soft/hard timeouts; retry-on-timeout."
depth: normal
---

# Research Brief: Enforce Timeouts on Sync Handlers via Thread Interruption (#549)

**Initiated by**: "Enforce timeouts on sync handlers via thread interruption — adopt HA's `async_raise(tid, exctype)` pattern so the timeout actually bounds a blocking sync handler's execution, instead of cancelling only the await while the thread runs on."

## Context

### What prompted this

The user believes the execution timeout is currently a **no-op for sync handlers**: `asyncio.timeout()` cancels the awaiting coroutine, but the worker thread running the handler keeps going until the handler returns naturally, occupying a thread-pool slot. The proposal is to adopt Home Assistant's `ctypes.pythonapi.PyThreadState_SetAsyncExc()` pattern to raise an exception into the blocking thread when the timeout fires.

### Verdict on the "no-op" claim

**The user is correct, with one important precision: the timeout is observable but not enforced.** Two distinct things happen when the timeout fires around a sync handler:

1. **What works (observable):** The caller's await unblocks. `asyncio.timeout()` at `command_executor.py:268` raises `TimeoutError`, `track_execution` records `status='timed_out'` (`execution.py:90-91`), a rate-limited WARNING is logged (`command_executor.py:276-278`), and a telemetry record is persisted. So from the *caller's and telemetry's* perspective the timeout fires correctly.

2. **What is a no-op (the real execution time is not bounded):** The worker thread is never stopped. The chain is:

   - `make_async_adapter` sends sync handlers through `run_in_thread` (`task_bucket.py:205`).
   - `run_in_thread` returns `asyncio.to_thread(_call)` (`task_bucket.py:176`).
   - `asyncio.to_thread` internally calls `loop.run_in_executor(None, ...)`, which returns a future backed by the **default `ThreadPoolExecutor`**.
   - When `asyncio.timeout` cancels the await, it cancels that future. But **`concurrent.futures` cannot cancel a thread once the work has started running** — `Future.cancel()` only succeeds on not-yet-started work. The worker thread runs the sync handler to natural completion.

   The slot stays occupied for the full real duration of the blocking call, regardless of the timeout. (Confidence: **Direct** — code + documented Python semantics. The project's own design doc states it explicitly: "the asyncio wrapper is cancelled but the underlying thread continues running until the blocking operation completes ... the thread may occupy a thread pool slot beyond the timeout" — `design/specs/036-execution-timeouts/design.md:184`.)

**Precise framing for the design doc:** the timeout is a correct *signal* (caller, logs, telemetry all see it) but does not *bound execution* or *reclaim the slot* for sync handlers. For async handlers the cancellation is real — `CancelledError` propagates at the next yield point and stops the coroutine. The gap is sync-only.

A secondary detail worth noting: `make_async_adapter` deliberately re-raises `TimeoutError` ahead of its broad `except Exception` (`task_bucket.py:206-207`), with a comment "no task to cancel anymore" (`:209`). The author already understood the thread cannot be cancelled — the current code is the documented, intentional behavior, not a bug.

### Current state (relevant architecture)

- **Sync detection** happens at registration via `is_async_callable` (`utils/func_utils.py:9-46`); sync handlers are silently wrapped by `make_async_handler` → `make_async_adapter` (`bus/listeners.py:699-712`). No warning is issued for blocking sync handlers at the API boundary.
- **Thread pool:** There is **no Hassette-owned executor.** Sync handlers run on asyncio's *default* `ThreadPoolExecutor` via `asyncio.to_thread` (`task_bucket.py:176`), shared loop-wide, `max_workers = min(32, os.cpu_count() + 4)`, unconfigurable. (Contrast HA, which installs its own custom executor as the loop default.)
- **Timeout config:** `event_handler_timeout_seconds` default `600.0`, `job_timeout_seconds` default `600.0`, `error_handler_timeout_seconds` default `5.0` (`config/models.py:218-259`, `:395-397`). Per-listener/job override via `timeout=` / `timeout_disabled=`. Resolved to `effective_timeout` at fire time (`bus/invocation.py:55-63`, `core/scheduler_service.py:325-332`).
- **Enforcement point:** single site — `async with asyncio.timeout(cmd.effective_timeout): await fn()` (`command_executor.py:268-269`).
- **Telemetry:** `status` enum includes `'timed_out'` (`migrations_sql/001.sql:92`); records carry `duration_ms`, `status`, error fields (`core/execution_record.py:12-105`). The "thread still running after timeout" condition is **not** currently surfaced anywhere.

### Key constraints

- Must not corrupt the shared default thread pool or inject an exception into the wrong callable (the exact race the original design rejected the feature over).
- Honest about the C-level blocking limit: `PyThreadState_SetAsyncExc` only delivers at the next Python bytecode boundary.
- This is a `Leaning` proposal, not `Decided` — dealbreakers and safer variants must be surfaced.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Dedicated interruptible executor (own pool, not the loop default) | new module under `task_bucket/` or `core/`; wiring in `core/core.py` | Med | Med — ownership, lifecycle, shutdown |
| Route sync handlers through the new executor | `task_bucket.py:153-176`, `:202-213` | Med | Med — must track the tid per call |
| Fire `async_raise` on timeout | `command_executor.py:265-274` (timeout/except path) | Med | **High** — race window between timeout and raise |
| Choose/define interrupt exception type | new exception in `hassette.exceptions` | Low | Low |
| Opt-in flag + config | `config/models.py`, listener/job options | Low | Low |
| Telemetry: record "interrupted" vs "timed_out but thread leaked" | `execution_record.py`, migration | Low–Med | Low |
| Tests: race, startup timing, C-block, interrupt success | new test files | Med | Med |
| Docs: update Non-Goals, document guarantees + limits | `design/specs/036.../design.md`, docs site | Low | Low |

### What already supports this

- **Single enforcement point.** All timeout logic funnels through `command_executor.py:268`. Interruption hooks into one place.
- **Sync/async split is already explicit.** `make_async_adapter` already branches; the interruption logic only touches the sync branch.
- **`TimeoutError` already escapes cleanly** from the sync adapter (`task_bucket.py:206-207`), so a raised interrupt exception can ride the same path.
- **Telemetry already models `timed_out`** — adding an "interrupted" distinction is incremental.
- **HA's reference implementation exists locally and is small** (`~/source/core/homeassistant/util/thread.py`, `:38-55`) — directly portable.

### What works against this

- **Hassette uses the *shared default* executor, not a private one.** HA installs its **own** executor as the loop default and only interrupts it at **shutdown** (see below). Raising into the shared default pool risks hitting threads running unrelated asyncio internals. A private pool is effectively mandatory — adding architecture HA has but Hassette lacks.
- **HA does not use `async_raise` for per-call timeouts at all** — only for shutdown. There is **no upstream precedent** for the exact thing #549 proposes. That is the single most important finding for the design phase (detail below).
- **The original design already rejected this** for thread-ID races (`design/specs/036-execution-timeouts/design.md:182-188`). Reversing requires solving those races, not hand-waving them.
- **No tid is currently captured.** `asyncio.to_thread` hides the worker thread; getting the tid for a specific call requires a custom executor or a custom thread wrapper.

## How Home Assistant Actually Does It (critical context)

HA's machinery lives in two files. Quoted verbatim from local source.

**`~/source/core/homeassistant/util/thread.py:38-55`:**
```python
def async_raise(tid: int, exctype: Any) -> None:
    """Raise an exception in the threads with id tid."""
    if not inspect.isclass(exctype):
        raise TypeError("Only types can be raised (not instances)")
    c_tid = ctypes.c_ulong(tid)  # changed in python 3.7+
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(c_tid, ctypes.py_object(exctype))
    if res == 1:
        return
    if res == 0:
        raise ValueError("Thread not found")
    # "if it returns a number greater than one, you're in trouble,
    # and you should call it again with exc=NULL to revert the effect"
    ctypes.pythonapi.PyThreadState_SetAsyncExc(c_tid, None)
    raise SystemError("PyThreadState_SetAsyncExc failed")
```

**The call site — `~/source/core/homeassistant/util/executor.py:35-58`:**
```python
def join_or_interrupt_threads(threads, timeout, log) -> set[Thread]:
    """Attempt to join or interrupt a set of threads."""
    joined = set()
    timeout_per_thread = timeout / len(threads)
    for thread in threads:
        thread.join(timeout=timeout_per_thread)
        if not thread.is_alive() or thread.ident is None:
            joined.add(thread)
            continue
        if log:
            _log_thread_running_at_shutdown(thread.name, thread.ident)
        with contextlib.suppress(SystemError, ValueError):
            # SystemError or ValueError at this stage is usually a benign
            # race condition where the thread dies right before we force
            # it to raise the exception.
            async_raise(thread.ident, SystemExit)
    return joined
```

**What HA uses this for — and what it does NOT:**

- HA installs `InterruptibleThreadPoolExecutor` (a `ThreadPoolExecutor` subclass) as the loop's default executor (`runner.py`), `max_workers = MAX_EXECUTOR_WORKERS` (64), thread prefix `SyncWorker`.
- `async_raise` is called **only from `shutdown()`** (`executor.py:61-101`), inside a 10s budget, after `super().shutdown(wait=False, cancel_futures=True)`. It is a **best-effort deadlock-avoidance measure at process shutdown**, not a per-handler timeout.
- The exception raised is **`SystemExit`** — chosen because it tears the thread down rather than being caught by handler `except Exception` blocks.
- HA never interrupts a worker mid-runtime for exceeding a timeout. It accepts that a slow integration occupies a slot until shutdown.

**This is the headline for the design phase:** #549 wants to use `async_raise` for a purpose HA deliberately does not — per-call, mid-runtime interruption. Hassette would be going *beyond* the reference, into the exact territory (mid-runtime, on a live pool, against a specific tid that may be reused) where the races bite hardest. HA sidesteps those races precisely by only doing this at shutdown, when no new work is being scheduled.

### Race conditions (and how HA mitigates — or avoids)

| Race | HA's mitigation | Applicability to per-call timeout |
|------|-----------------|-----------------------------------|
| tid not found / thread already died | checks `is_alive()`; suppresses `SystemError`/`ValueError`; checks `res` value | Partial — still a window between check and raise |
| `res > 1` (multiple states) | reverts with `SetAsyncExc(tid, None)`, raises `SystemError` | Portable directly |
| Thread hasn't started yet | not a concern at shutdown (threads are mid-work) | **Unsolved for per-call** — timeout could fire before the worker dequeues the job; tid may be unset |
| **tid reuse** — finished worker's tid reassigned to an unrelated job before the raise lands | **avoided by construction** — at shutdown the pool is draining, no new work is scheduled | **The core unsolved risk for per-call.** On a live reused pool, raising into a recycled tid injects the exception into the wrong handler. This is exactly what the original design rejected (`design.md:186`). |

The original design's rejection holds: on a *standard reused* `ThreadPoolExecutor`, per-call `async_raise` is unsafe. The only way to make it defensible is a **dedicated, single-use thread per interruptible call** (thread created, runs one callable, discarded — never returned to a pool, so its tid is never reused while a stale raise is in flight). That converts the reuse race into thread-churn cost.

### C-level blocking limitation (honest statement)

`PyThreadState_SetAsyncExc` sets a pending exception that the interpreter delivers **only at the next bytecode boundary in that thread**. A thread blocked inside a C call — `time.sleep()`, `socket.recv()` without a timeout, a blocking C extension, `requests` mid-syscall, a native DB driver — will **not** be interrupted until it returns to Python. So the feature can interrupt a Python `while True:` loop or a chain of Python calls, but **cannot** bound the most common real-world offender: a sync handler blocked in a C-level network/IO call. This must be stated plainly in the guarantees: "interrupts Python-level execution at the next bytecode boundary; does not interrupt threads blocked in C calls." That caveat materially shrinks the feature's value, since blocking IO is the usual reason a sync handler runs long.

## Options Evaluated

### Option A: Thread interruption via a dedicated single-use executor (the proposal, made safe)

**How it works**: Introduce a Hassette-owned executor for interruptible sync handlers where **each interruptible call runs on its own thread that is discarded after the call** (no tid reuse). Capture the worker tid when the call starts. On timeout at `command_executor.py:268`, call `async_raise(tid, HassetteInterrupt)` where `HassetteInterrupt` is a `BaseException` subclass (so handler `except Exception` blocks don't swallow it). Port HA's `res`-value handling and `SystemError`/`ValueError` suppression verbatim. Gate behind an opt-in flag (`interruptible=True` per listener/job, default off). Record a distinct telemetry status (`interrupted` vs `timed_out`).

**Pros**:
- Actually bounds execution time and reclaims the slot — for Python-level work.
- Single-use threads eliminate the tid-reuse race that the original design rejected.
- Builds on HA's battle-tested `async_raise` core (portable, ~18 lines).
- Hooks into the one existing enforcement point.

**Cons**:
- **Does not solve the common case** — C-blocked IO is uninterruptible (see limitation above). The feature's headline benefit doesn't apply to the workloads that most need it.
- Thread churn: one OS thread per interruptible call, created and torn down. Real cost under high-frequency handlers.
- Adds an executor Hassette doesn't currently own, plus lifecycle/shutdown wiring.
- Startup-timing race still exists (timeout before the worker starts running the callable) — needs a "tid not yet captured → cannot interrupt, fall back to current no-op behavior" path.
- Goes beyond HA's own usage; no upstream precedent for per-call interruption to lean on.

**Effort estimate**: **Medium–Large** — new executor + tid capture + race handling + opt-in plumbing + telemetry + a real test matrix (interrupt success, C-block non-interrupt, startup race, reuse safety).

**Dependencies**: None new (`ctypes` is stdlib). New internal exception type.

### Option B: Document-and-monitor only — make the no-op observable, don't kill threads

**How it works**: Keep the current behavior (timeout cancels the await, thread runs on). Add observability: a telemetry/log signal when a sync handler's thread is still alive past its timeout, and surface thread-pool saturation (active vs `max_workers`). Optionally add a registration-time DEBUG/INFO note when a sync handler is registered with a finite timeout, clarifying that the timeout signals but does not bound it.

**Pros**:
- Smallest diff; zero new failure modes; no ctypes, no churn, no races.
- Directly addresses the real user pain (the no-op was *invisible*) by making it *visible*.
- Honest: doesn't promise a guarantee the C-block limit can't deliver.
- Reversible and a strict prerequisite for any later forcible option (you need the metric to know if interruption helps).

**Cons**:
- Does not reclaim slots; a runaway sync handler still saturates the pool.
- Users wanting a hard bound must restructure to async handlers.

**Effort estimate**: **Small** — telemetry field + a saturation gauge + doc updates.

**Dependencies**: None.

### Other variants (lightweight, for completeness)

- **(c) Bounded/dedicated pool that caps concurrency and accepts leaked slots.** Give sync handlers their own fixed pool so a storm of slow handlers can't starve framework internals on the shared default executor. Combine well with B. Doesn't bound any single call, but contains blast radius. **Small–Medium.** Worth folding into the recommendation regardless of A/B, because today sync handlers and asyncio internals share one pool.
- **(d) Process-pool / subprocess isolation.** Truly killable (SIGKILL), interrupts C-blocked work too. But handlers must be picklable, lose shared `self`/state, and pay IPC cost — incompatible with the `App` instance-method handler model. **Large, poor fit. Not recommended.**
- **(e) Refuse/discourage blocking sync handlers at the API boundary.** A registration-time warning when a sync handler is registered (`make_async_handler`, `listeners.py:699`). Cheap nudge toward async. Pairs with B. Pure prevention, no enforcement. **Small.**

## Concerns

### Technical risks
- **tid reuse on a reused pool** corrupts an unrelated handler — the original rejection reason (`design.md:186`). Only a single-use-thread design avoids it.
- **Startup-timing race**: timeout fires before the worker dequeues the callable; tid unset or pointing at idle pool state. Needs an explicit "cannot interrupt yet" fallback.
- **`BaseException` choice**: if the interrupt exception subclasses `Exception`, handler `try/except Exception` swallows it and the interrupt is lost. Must be `BaseException` (HA uses `SystemExit`). But `BaseException` leaking through user code can bypass their cleanup — `finally` blocks still run, but `except Exception` recovery won't.
- **C-block limit** means the feature silently fails to interrupt the most common slow path (blocking IO). Users may assume a guarantee they don't have.

### Complexity risks
- New executor with its own lifecycle, shutdown, and saturation accounting where today there is none.
- A new opt-in concept (`interruptible`) and a new telemetry status to teach and maintain.
- Thread churn under high-frequency handlers — a new performance characteristic to reason about.

### Maintenance risks
- ctypes interpreter-internal call (`PyThreadState_SetAsyncExc`) is CPython-specific and could shift across versions; it obligates ongoing version testing (3.11–3.14).
- Going beyond HA's usage means no upstream to track for fixes — Hassette owns the race-safety proof entirely.

## Open Questions

- [ ] What fraction of real slow sync handlers are C-blocked (IO) vs Python-bound? If mostly IO, Option A delivers little and B is the honest answer. (Unknown — needs the Option B telemetry to measure. Searched the design doc and tests; no usage data exists.)
- [ ] Should interruption be opt-in per handler or a global mode? Opt-in is safer (default off) and matches the "leaning, not decided" posture.
- [ ] Does any current consumer rely on a timed-out sync handler *completing* its side effects (since the thread runs on today)? Interruption changes that contract. (Unknown — Hassette is a framework; real consumers are user apps not in this repo.)
- [ ] Acceptable thread-churn ceiling — do we cap concurrent interruptible calls to bound OS-thread creation?
- [ ] Should Hassette stop using the shared default executor for sync handlers regardless of #549 (Option c), to isolate handler blast radius from asyncio internals?

## Recommendation

**Ship Option B first, with Option (c) folded in, and treat Option A as opt-in and conditional on what B's metrics reveal.**

The user's diagnosis is right — but the precise problem is that the no-op was *invisible*, not that threads weren't being killed. The highest-value, lowest-risk move is to make it visible: record when a timed-out sync handler's thread is still alive, and surface thread-pool saturation. That directly resolves the surprise, costs little, and is a hard prerequisite for evaluating whether forcible interruption is even worth it.

Option A (thread interruption) is **defensible only as a dedicated single-use-thread design, opt-in, default off** — and even then it carries a load-bearing caveat: it cannot interrupt C-blocked IO, which is the most common reason a sync handler runs long. The original design rejected this for tid-reuse races; those races are real and only the single-use-thread variant avoids them. Critically, **HA itself does not use `async_raise` for per-call timeouts** — only for shutdown — so #549 would be charting territory upstream deliberately avoids. That is not a hard blocker, but it shifts the full race-safety burden onto Hassette.

Confidence: the no-op verdict and HA's shutdown-only usage are **Direct** (code-cited). The tid-reuse and C-block risks are **Direct** (semantics + HA comments). The claim that "most slow handlers are C-blocked" is **Speculative** until B's telemetry exists — which is itself the strongest argument for sequencing B first.

### Suggested next steps
1. Implement Option B + (c): a dedicated sync-handler pool with a saturation gauge and a telemetry signal for "thread alive past timeout." Measure for a release cycle.
2. Run `/mine.challenge` on this brief before committing to a direction — the HA-doesn't-do-this finding and the C-block limit deserve adversarial pressure.
3. If B's data shows meaningful Python-bound (non-C-blocked) runaway handlers, write a design doc (`/mine.define`) for Option A as an opt-in single-use-thread interrupt, porting HA's `async_raise` core verbatim with a `BaseException` interrupt type, an explicit startup-race fallback, and a documented C-block caveat.
4. Update `design/specs/036-execution-timeouts/design.md` Non-Goals to reflect the refined verdict (timeout is observable but unenforced for sync) regardless of which option ships.

## Sources

All findings are from local source; no web research was performed.
- Hassette: `src/hassette/core/command_executor.py:222-326`, `src/hassette/task_bucket/task_bucket.py:153-213`, `src/hassette/bus/listeners.py:699-712`, `src/hassette/utils/func_utils.py:9-46`, `src/hassette/config/models.py:218-259,395-397`, `src/hassette/core/execution_record.py:12-105`, `src/hassette/migrations_sql/001.sql:92`, `design/specs/036-execution-timeouts/design.md:21-27,141-188`, and tests `tests/unit/test_make_async_adapter_timeout.py`, `tests/unit/scheduler/test_scheduler_timeout_threading.py`, `tests/unit/bus/test_bus_timeout_threading.py`.
- Home Assistant core (`~/source/core`): `homeassistant/util/thread.py:14-69`, `homeassistant/util/executor.py:23-101`, `homeassistant/runner.py`.
