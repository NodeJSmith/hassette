# Backend Core Correctness & Coherence Audit — 2026-09-02

**Scope:** Backend core, deep pass — lifecycle/teardown machinery (`resources/`), root coordinator
(`core/core.py`), the readiness lattice (WebsocketService / StateProxy / AppBootstrapCoordinator),
bus stack (`bus/`, `core/bus_service.py`), scheduler stack, app lifecycle
(`app_lifecycle_service.py`, `app_handler.py`, `app_registry.py`), ServiceWatcher, CommandExecutor,
DatabaseService, SessionManager, EventStreamService, SyncExecutor, LoggingService, Api layer, App base.
**Not covered:** web layer, frontend, CLI, docs, deep `triggers.py` pass, sync facades beyond spot checks.

**Lenses:** correctness/races first, design coherence second. Decomposition/file-size debt was
deliberately excluded — the issue backlog already tracks it (#1759, #1576, #1575, #1574, #1721, #1686).

**Method:** direct line-by-line read of ~10k lines of the intricate core (task bucket, resources,
core, websocket, state proxy, bootstrap coordinator, bus, service watcher, app lifecycle, command
executor, database service), plus two full-context delegate passes over the scheduler stack and the
api/support-services slice whose findings were then spot-verified. The headline finding (F1) was
confirmed with a runtime probe, not just reading.

**Overall assessment:** this core is in unusually good shape. The lifecycle coordinator, teardown
report/budget machinery, StateProxy generation fencing + journal replay, bus dispatch/backpressure
bookkeeping, duration-timer state machine, and the telemetry write pipeline all survived detailed
adversarial reading — including deliberate interleaving analysis — with no correctness findings.
The findings below cluster at the *seams between subsystems* (timeout wrappers around coordinator
front doors, retry policies around side-effectful sends, event handlers blind to a dimension of the
events they receive), not inside the machines themselves.

---

## Findings

### F1 — HIGH · App init timeout leaves a ghost initializer running (runtime-confirmed)

`app_lifecycle_service.py:193` wraps `await inst.initialize()` in `anyio.fail_after(startup_timeout)`.
But `initialize()` is the coordinator front door: `coordinate_initialize()`
(`resources/lifecycle.py:658`) runs the real work as `_init_task` and joins it via
`await asyncio.shield(init_task)`. The timeout cancels only the outer await — **the shield keeps the
initializer running**. The timeout branch (`app_lifecycle_service.py:202-212`) then sets
`inst.status = STOPPED`, runs `cleanup_failed_instance()` (listeners/jobs/cache — but never cancels
`_init_task`, never calls `inst.shutdown()` or `cancel(inst)`), and pops the instance from the
registry via `record_failure()`.

**Runtime probe** (real `Resource` through `initialize_instances()`, `on_initialize` sleeping past
the timeout): after the timeout path finished — status STOPPED, failure recorded — `_init_task` was
still pending. When the hung hook completed, the discarded instance registered its listener
*post-cleanup* and transitioned STOPPED→RUNNING (invalid transition, applied with a warning in
non-strict mode; raises inside the orphan task under `strict_lifecycle`).

**Consequences:** a ghost instance with live listeners/jobs, unreachable by stop/reload (registry
already dropped it), emitting RUNNING status events for an instance the dashboard shows as FAILED.
If the user reloads the app meanwhile, ghost and replacement share `instance_name`/owner_id, so a
later teardown rips out both sets of registrations. Trigger condition is mundane: any app
`on_initialize` that outlives `app_startup_timeout_seconds` (default 20s) and later completes —
a slow HTTP call, a stuck device, a long first sync.

**Fix direction:** on timeout, drive the machinery that already exists for exactly this — cancel
and bound-observe the initializer (`_observe_active_initializer` semantics) or run a bounded
`inst.shutdown()` — instead of the ad-hoc cleanup. Cross-references: #1367 covers the *exception*
path of the same seam (hook raises → allocated resources leak); #1689 Gap 2 covers the *shutdown*
twin (`shutdown_instance`'s swallowed `fail_after`), where the background continuation is at least
budget-bounded by design. The init side has no bound and no observer at all.

Probe: `scratchpad/probe_f1_ghost_init.py` (session scratchpad; reproduce with any Resource whose
`on_initialize` sleeps past a shrunk timeout).

### F2 — MED-HIGH · WS retry re-sends non-idempotent commands on response timeout (double execution)

`WebsocketService.send_and_wait` (`websocket_service.py:669-691`) retries on
`FailedMessageError` with `code is None` — which is exactly what a *response timeout* raises
(`:686-689`) after the payload was already **sent successfully**. `Api._call_service` with
`return_response=True` (`api/api.py:601`) and `_fire_event` (`:505`) route through it. When HA is
merely slow (integration reload, recorder purge), a `call_service` response exceeding
`resp_timeout_seconds` re-sends the command under a new msg_id: a toggle flickers, a script/scene/
notify runs twice. The codebase already recognizes this exact hazard for `subscribe_events`
(`:563-605` proactively unsubscribes the abandoned attempt before retrying) — service calls get no
equivalent treatment. **Fix direction:** retry only reads on response timeout; for side-effectful
commands surface a distinct "sent but unconfirmed" error (or make retry opt-in per call).

### F3 — MED · StateProxy read-path retry blocks the event loop with `time.sleep`

`state_proxy.py:36-43`: `_retry_on_not_ready` is a **sync** tenacity retry
(`wait_exponential_jitter(0.01..0.1)`, 5 attempts) decorating sync methods (`get_state`,
`yield_domain_states`) called from async handlers via StateManager. Sync tenacity waits are
`time.sleep()` — on the loop thread. During the UNAVAILABLE window every read can stall the loop up
to ~0.3-0.4s, and since the Tier-2 block-IO guard patches `time.sleep`
(`block_io_guard.py:59`), the framework's own read path would trip its own blocking-IO detector.
**Fix direction:** drop the retry (raise `ResourceNotReadyError` immediately — callers already
handle it) or move retrying to an async read path.

### F4 — MED · ServiceWatcher handlers are role-blind; APP-role service-status events cause noise now, process-kill later

`service_watcher.py` filters `restart_service` and `shutdown_if_crashed` on *status only*. App
resources emit `HASSETTE_EVENT_SERVICE_STATUS` too (Resource-level `handle_failed`/`handle_crash`).
Today: every app init failure fires `restart_service`, which resolves no Service and logs
`"No App found for 'X', skipping restart"` — recurring warning noise. The hazard: `shutdown_if_crashed`
has no role filter, so any future path that drives an APP-role resource through `handle_crash`
(the machinery exists and `bootstrap_apps` already calls it on the lifecycle service itself) takes
down the whole process. Related but distinct from #1666 (filtering app-role events from the *web
UI* WS stream); the watcher-side blindness is unfiled. **Fix:** role-filter the watcher's
subscriptions (`role == SERVICE`) or the predicates.

### F5 — MED · `remove_jobs_by_owner` is an orphaned trap with a Protocol advertising it

`scheduler_service.py:797-803` / `:178-188`: zero production callers, but exported on the service
protocol (`types/types.py:267`) and cited as the mirror pattern by BusService docstrings. Unlike the
unified removal op it skips `_dequeued`, `_jobs_by_id`, and `removed_at`, and scans only the heap —
a future caller gets zombie jobs that survive owner removal and refire forever (a job popped
mid-dispatch is invisible to the heap scan and re-enqueues itself). **Fix:** delete it (and the
protocol entry), or reimplement over `_remove_from_live_state()`.

### F6 — MED · Queued-mode spawn failure at drain time parks a dispatch task forever and leaks a bus semaphore slot

`execution_mode.py:165-171` (`drain_next`): a queued factory whose `run_and_track()` raises is
dropped and the drain continues — but its completion future (bridge in `run_through_guard`) is never
resolved, so the outer dispatch task stays parked on `await done`. For bus listeners that task holds
one `_dispatch_semaphore` slot (`bus_service.py:463-478`), permanently shrinking
`max_concurrent_dispatches` by one per occurrence. The realistic raiser is `TaskBucket.spawn` on a
sealed bucket (teardown-adjacent — same family as F9, and F9 also eats the `release_guard()` call
that would otherwise unwind it). Distinct from the tracked drain/release detach edge (#1099).
**Fix:** resolve the dropped factory's future in `drain_next`'s except branch (wrap factory to
resolve-on-spawn-failure).

### F7 — LOW · Crashed-then-killed sessions are immortal to once-listener cleanup

`session_manager.py:167-187` sets `status='failure'` on crash but leaves `stopped_at` NULL;
orphan-marking (`:143-152`) only matches `status='running'`. A session that recorded a crash and
died before `finalize_session` keeps `stopped_at IS NULL` forever, and the once=True cleanup's
NOT EXISTS join (`:222-227`) treats its executions as belonging to a live session — those rows are
never reaped. **Fix:** orphan-mark on `stopped_at IS NULL` regardless of status, or set
`stopped_at` in the crash UPDATE.

### F8 — LOW · once=True cleanup only reaps listeners that *fired*; comment drift in core.py

`session_manager.py:215-229`: the first EXISTS requires ≥1 execution, so a once listener from a
prior session that never fired is never deleted, contradicting the "prevents unbounded row growth"
docstring. App-owned rows get caught by per-restart reconciliation; framework-owned once listeners
have no such path. Also `core.py:704-706` describes a `session_id = ?` guard that no longer matches
the actual SQL. **Fix:** add a never-fired branch to the cleanup query; refresh the comment.

### F9 — LOW · Sync cancel/removal paths spawn onto possibly-sealed TaskBuckets

`listeners.py:496` (`Listener.cancel()` → spawn `release_guard`) raises `RuntimeError` if the owning
bucket is sealed. Normal teardown ordering avoids it (listener removal happens in `Bus.on_shutdown`,
before that bucket's seal), but force-terminal windows hit it: a force-terminated app's stale
listeners (hooks skipped — documented accepted gap in `_force_terminal`) removed later via
`remove_listeners_by_owner` raise mid-loop, leaving remaining listeners uncancelled and callbacks
unfired (routes are already cleared). Compounds F6. **Fix:** make `spawn`-for-cleanup tolerate
sealed buckets (fall back to inline sync release or drop with debug log).

### F10 — LOW · Resource logger filters accumulate across reload cycles

`resources/base.py:198-212`: `_setup_logger` does `addFilter(_ResourceContextFilter(...))` on a
process-global logger every construction; `_ResourceContextFilter` has no `__eq__`, so stdlib dedupe
never fires. App instances recreated on hot-reload reuse the same logger name → one filter per
reload, unbounded, O(n) filter chain on hot log paths. **Fix:** dedupe by filter type before adding.

### F11 — LOW · Per-wave shutdown floor can structurally overrun the coordinator margin

`Hassette._shutdown_children` gives *every* wave `max(1s floor, body_deadline − now)`
(`children_budget_remaining`), so N hung waves overrun `body_deadline` by up to N×1s while the
coordinator margin is only 10% of total (3s at the 30s default). With 4+ hung waves the "graceful"
path is guaranteed to bust `total_deadline`, making the crude force-terminal backstop the *normal*
outcome exactly in the pathological cases the wave logic was built for. **Fix direction:** budget
per-wave as `remaining/waves_left`, or validate config so `margin ≥ waves × floor`.

### F12 — LOW · Assorted small verified items

- **DB worker cancellation mid-write leaves an in-flight `submit()` future unresolved**
  (`database_service.py:426-450` — `except Exception` doesn't cover `CancelledError`; force-terminal
  path only; add `except CancelledError: future.cancel(); raise`).
- **`Resource.cleanup(timeout=0)` falsy-`or`** (`resources/base.py:656`, same pattern in
  `app/app.py:250`).
- **TaskBucket cross-thread spawn timeout can still create the task later** — caller saw
  `RuntimeError`, work runs anyway (`task_bucket.py:249-261`); tracked-in-bucket so bounded.
- **`submit()` after shutdown reports "called before on_initialize()"** — misleading error text
  (`database_service.py:467-469`).
- **`_serve_wrapper` STOPPING→CRASHED**: a `FatalError` from `serve()` during the shutdown window
  drives an invalid transition (`VALID_TRANSITIONS[STOPPING]` lacks CRASHED) — warning-level noise,
  raises under `strict_lifecycle`.

### F13 — INFO · Coherence notes (no action required, worth knowing)

- **`allow_pre_ready` is a no-op** — `send_json()` (`websocket_service.py:744`) is a pure
  pass-through to `_send_json_when_socket_live()`; both branches of `send_and_await_response` gate
  only on the private `_send_ready_event`. The documented public/private send-capability split
  doesn't exist at the send layer. Mitigated in practice: `Api` checks `is_connected` before
  delegating (`api/api.py:331,337`). Either move the external-readiness gate into `send_json` or
  delete the parameter and the doc claim.
- **StateProxy awaits raw sync tasks** (`await task` in `_request_*_synchronization`) — a
  disconnect-cancel propagates `CancelledError` into the poll job, producing spurious
  `status='cancelled'` execution rows on every mid-poll disconnect. Harmless (next occurrence is
  enqueued before the handler runs). `lifecycle.py` deliberately uses `asyncio.wait()` for exactly
  this decoupling; StateProxy could match.
- **`App.unique_name` `startswith` heuristic** (`app/app.py:171-176`) can collide across classes
  (class `Light` + instance `LightsOut` vs class `LightsOut`) — same owner-registry consequence as
  #1689 Gap 3, distinct mechanism; fold into that issue's scope.
- **Removed-job current-fire semantics**: `Job.remove()` landing after `dispatch_and_log`'s entry
  check doesn't stop the popped fire; the guard has no terminal state. Documented as
  trigger-outcome-independence, not removal-independence — clarify if "remove = no further user
  code" ever becomes the contract.
- **Cron catch-up loop** (`classes.py:102-147`) can do up to 10k synchronous `croniter` steps on
  the loop — bounded, acknowledged, may trip the loop watchdog at pathological settings.
- **`Job.__eq__`/`__lt__` raise for never-scheduled jobs** (`sort_index` unset) — latent trap,
  carefully routed around today.
- **`set_state` double-GET** (`api.py:971-972`) — `entity_exists()` + `get_state_raw()`; one
  404-tolerant GET would do.
- **ServiceWatcher-synthesized restart flow after app FAILED events** produces the F4 warning noise
  today; the same fix covers it.

---

## Clean areas (checked hard, no findings)

- **Lifecycle coordinator** (`coordinate_initialize`/`coordinate_shutdown`/`_run_shutdown_coordinator`):
  admission atomicity, re-entry rejection, pending-start race closure, cancellation-with-evidence
  conversion, budget allocation — all interleavings traced held up.
- **TeardownReport** monotonic-evidence model; **`shutdown_batch`** classification and force-terminal
  propagation.
- **StateProxy synchronization**: baseline/journal/commit protocol under the two-lock discipline
  (never held simultaneously), generation fencing on events, commits, and retries.
- **Bus dispatch**: semaphore/pending bookkeeping including the no-await windows the comments claim;
  DROP_NEWEST accounting; once-guard; debounce/throttle atomicity; duration-timer cycle events and
  active-counter balance across restart/cancel/fire interleavings.
- **Scheduler heap integrity** (off-heap-only mutation invariant, `_dequeued` in-lock re-check,
  KI-006 cleanup), pending EntityTime transitions, restart-mode guard, removal identity checks,
  `_add_job` rollback.
- **CommandExecutor** batch/retry/FK-fallback pipeline, execution-marker publication discipline.
- **DatabaseService** single-writer drain/close ordering (modulo F12 nit); **SessionManager** happy
  paths; **EventStreamService** close/send races all handled at call sites; **SyncExecutor**
  handle/ContextVar discipline; **LoggingService** handler swap; **App/AppSync** surface minimalism
  and teardown overrides.

## Issue tracking

Filed 2026-09-02 during the findings walkthrough:

| Finding | Issue |
|---|---|
| F1 ghost initializer | #1797 (priority:high) |
| F2 WS double-send | #1798 (priority:high) |
| F3 loop-blocking retry | #1803; companion `wait_fresh()` enhancement #1804 |
| F4 role-blind watcher | #1799 |
| F5 `remove_jobs_by_owner` trap | #1800 (Code Quality) |
| F6 dispatch-slot leak | #1805 |
| F7 immortal crashed sessions | #1806 |
| F8 once-cleanup gaps | #1807 |
| F9 sealed-bucket spawns | #1810 |
| F10 logger filter accumulation | #1808 |
| F11 wave floor vs margin | #1809 (priority:low) |
| F12 grouped small edges | #1811 |
| F13 `allow_pre_ready` vestige | #1812 (Architecture) |
| F13 spurious cancelled telemetry | #1813 |
| F13 `unique_name` prefix collision | comment on #1689 |

Report-only (deliberate skips): removed-job current-fire semantics (documented behavior),
cron catch-up stall (bounded + acknowledged), `set_state` double-GET (micro),
cross-thread spawn timeout (accepted-risk, documented inside #1811).

## Suggested sequencing

1. **F1** — file + fix soon; it undermines the teardown-safety story the last three months of work
   built, and the fix is mostly wiring existing machinery into the timeout branch. Coordinate with
   #1367 (exception path) and #1689 (shutdown path) — three seams, one theme: *every* exit from
   `initialize_instances`/`shutdown_instance` should leave the instance either fully alive or fully
   torn down, using the coordinator, not ad-hoc cleanup.
2. **F2** — small, contained, user-visible correctness (double service execution).
3. **F4 + F5** — both are "delete/guard a trap before someone steps on it."
4. **F3, F6-F11** — batch as normal backlog items.
5. F12/F13 — optional hygiene batch or fold into adjacent issues.
