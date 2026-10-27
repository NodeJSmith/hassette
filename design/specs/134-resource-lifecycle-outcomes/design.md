# Design: Resource Lifecycle Outcomes

**Date:** 2026-10-18
**Status:** ratified
**Mode:** sketch
**Issues:** #3036, #1716, #1224, #1797, #2780, #1689 (gaps 1 and 2), #1698, #2697

## Summary

Hassette infers lifecycle outcomes instead of recording them. `ServiceWatcher` works out who owns a
service failure from a `_restarting` set, the service's status and step order. App start/stop wrap
the lifecycle coordinator in `anyio.fail_after`, so a timeout abandons the user's hook while the
instance is marked STOPPED/FAILED. Reload creates a replacement without checking the old instance's
teardown. The app action routes read the registry back after the lock is released to guess whether an
action failed. This initiative makes each outcome an explicit, recorded fact. Prior art: the
lifecycle-outcomes prior-art brief of 2026-10-18 in the design research folder (OTP supervisors, systemd, trio, and HA
config entries).

This ledger is milestone-level (Posture: Altitude). It ends in a GitHub milestone plus the issues in
`## Breakdown`, which name components and behavior, never files or line numbers. A re-challenge found
that much of the existing lifecycle machinery restarts or arbitrates what peers simply don't, so the
milestone also deletes it (D17, D18, D19).

Areas and where each new piece lives:

- **Service start handoff** — `Service`'s initialization body and serve wrapper. A service is RUNNING only after `initialize()` (hooks and
  children) has completed.
- **Service supervision** — one report-routing method on `Hassette`, which receives failure reports
  (D8) and routes them (D2, D17). `ServiceWatcher` is deleted: with no restarts, bus listeners or
  readiness tracking left, routing was all it did. `ServiceEscalationMixin` goes (D14) and the restart
  machinery with it (D18).
- **Fatal escalation** — one fatal-exit function on `Hassette`, beside its in-memory fatal-reason
  latch (D14).
- **Required/optional declaration** — a class-level declaration on each `Service`, replacing
  `restart_spec` (D17); `Hassette`'s report routing reads it, and `add_child` rejects a required
  Service whose parent isn't `Hassette`.
- **Dead bus** — `BusService` closes the event streams whenever its drain loop ends, and failed
  startup has it close them unless the loop is running (D9). A serve failure then arrives as a D8
  report; an init failure is a boot failure (D1). The
  bus is required (D17), so either way the process exits through D14 or failed startup. After bus
  death, no producer blocks (D9).
- **Failure report** — `Service`'s serve wrapper reports post-handoff serve failures to `Hassette`'s
  report routing (D8).
- **Shutdown deadlines** (D19) — the stop and foundation stages, and the names of the foundation
  services, on `Hassette`'s root shutdown; the entry deadline on `AppLifecycleService`'s instance
  operations, which on expiry also has the instance's `Bus` and `Scheduler` registrations removed by
  owner; the operation deadline a hook's bound is clamped to, as attempt state on the resource
  coordinator; registry app stop in `AppHandler`'s child stage; the hard exit on the `hassette run`
  path, which reads a force-terminated-work record kept on `Hassette` beside its fatal-reason latch
  (written by the root's stages, by `AppLifecycleService` on entry-deadline expiry and by the
  foundation stage when executor threads survive the join) and `DatabaseService`'s in-flight snapshot;
  `shutdown_timeout_seconds` (per hook) and `total_shutdown_timeout_seconds` (the whole exit) in
  the lifecycle config.
- **App instance state** — the per-instance needs-restart flag
  (home per D11), set by `AppLifecycleService`'s lifecycle mixins (instances, start/stop, changes)
  and held in `AppRegistry`.
- **Action outcomes** — a typed outcome returned by `AppLifecycleService` start/stop/reload methods,
  mapped by the app action routes' `_run_app_action()`. The frontend action buttons and the CLI's
  `app` commands get minimal changes only.
- **Docs and UI** (per the design-completeness rule, shipping with the issue that introduces
  each behavior):
  - the app lifecycle docs explain hook timeouts, the needs-restart flag, reload refusal,
    and "restart hassette to recover";
  - the operating docs explain `shutdown_timeout_seconds` (per hook), `total_shutdown_timeout_seconds`
    (the whole exit) and the supervisor grace period it needs, the hard exit after force-terminated
    work, and the removed settings, which hassette rejects at load;
  - the app lifecycle docs also say shutdown hooks must let cancellation through, clean up promptly
    and never block the event loop, or they can hold shutdown to its stage deadline or past it;
  - the service supervision docs explain required vs optional services, fatal exit, dead-in-place, boot fail-fast, that
    hassette must run under a restart policy (add-on, Docker, systemd), and where that supervisor
    keeps the previous run's fatal reason;
  - the UI shows an instance's needs-restart flag and its reason, as minimal text or
    badge only, since a UI rework is coming; the CLI's app listing shows the same flag and reason.

Out of scope:
- **Closed:** #2481 (load-before-stop), #1767 (in-process service reconstruction), #1390 (process
  restart command).
- **Moved to the log-identity initiative:** #1689 gap 3 (`unique_name` collisions across app keys).
- **Separate initiatives or features:** the lifecycle signal taxonomy (#685, #686), a lifecycle
  controller object (#1237), app-author features (#1830, #67, #608, #1676), #2976, #3029, #2781,
  #2938.

## Posture

- **Failure handling:** loud. A required framework service escalates to process exit; a broken app
  stops only itself; no in-process service restarts (D17).
- **Compatibility:** break freely (pre-V1). Changes to `hassette-wire` enums or published payloads go
  through the compat ignore lists (which one, per the Breakdown's "Applies to all") with changelog and
  migration notes, because hassette-wire
  and hassette-client are released packages.
- **Scope:** minimal per concern. The deliverable is a milestone of high-level issues, not one build.
- **Rollout:** ship outright. The endpoint contract change and its minimal frontend change land in the
  same release as the app-state changes.
- **Hardening:** project defaults, plus one raised requirement: every new needs-restart or dead-in-place
  state is visible as a status and one ERROR log naming the outcome and the cause, on top of whatever
  logged the underlying failure. No silent states.
- **Concurrency:** the existing per-app-key lock is the one serial owner per app instance. No new
  global locks.
- **Altitude:** milestone; the issues are picked up one at a time, after refactors that move the code
  this ledger describes.

## Decisions

### D1: When does a Service count as started?

**Deciding factor:** every peer (OTP `start_link`, systemd `Type=notify`, trio `nursery.start()`)
withholds "started" until initialization returns; the one that doesn't (systemd `Type=simple`) is a
documented trap.

**Recommendation:** RUNNING only after the initialization body completes, including
`after_initialize()` and child initialization (D7 defines the handoff). A failure before that handoff belongs to the caller of the attempt. A failure
after it belongs to the supervisor. D7 decides how that ordering is achieved.

At boot, the first start has no supervising caller, so the startup sequence takes that role: each
wave (and the database service's phase before the waves) joins its children's initialization attempts,
then waits for readiness. Readiness alone doesn't prove the attempt finished, because a service may
mark ready inside `on_initialize()` (`WebApiService` does, before its `Scheduler` child initializes),
so a wave that waited only on readiness could advance while a child initialization later fails in
the background. A boot-time start failure is therefore fatal whether or not the service is required:
the wave's join raises, startup fails at once instead of at the wave timeout, and the external
supervisor restarts the process. The join races `shutdown_event` the way `wait_for_ready()` does,
because initialization is shielded and a shutdown requested mid-wave must not wait for it; and it
records the fatal reason with the failed services' names without logging the exception again, since
the initialization task's observer already logged it at ERROR. No boot-wave initialization body
waits on Home Assistant or on a later wave (the HA connection lives in `WebsocketService.serve()`,
app bootstrap runs after the handoff, in background work today and in `AppHandler.serve()` from issue 4,
and only top-level services declare `depends_on`), so the join
can't stall a wave that readiness would have let through. This is a behavior change. Before this
decision shipped (#3106), a FAILED event from a boot failure in a post-watcher wave reached
`restart_service()` and got retried. It is accepted, because a wave that isn't ready is already fatal
today, so a retry only ever helped if it won inside the wave timeout.
**Pick the status quo instead if** a service genuinely needs to look RUNNING while its children
start. None was found.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose RUNNING-after-initialize over serve-time RUNNING, to make a failed attempt fail exactly once at the attempt, accepting a readiness-timing audit of every service. Boot fail-fast chosen at the sketch challenge (Finding 6) over making the first start a supervised attempt, accepting the loss of in-process retry for transient boot failures. Joining each wave's initialization attempts added at PR review (2026-10-19), because readiness marked inside `on_initialize()` let a wave advance past a child initialization that later failed.

### D2: What happens to a service that fails after startup?

**Deciding factor:** a broken required service is not worth running without, but an optional one is.

**Recommendation:** the outcome follows whether the service is required (D17). A required service's
failure escalates to process exit through D14, and the external supervisor restarts the process. An
optional service ends dead in place: nothing shuts it down or restarts it, so its status stays
FAILED (CRASHED if it raised `FatalError`) until process shutdown begins, and it logs one new ERROR (beyond the serve failure's own logs) naming its
bucket's pending tasks (excluding the reporting serve task itself, which is still running when it
reports) and saying a hassette restart brings it back (Posture: no silent states). No
in-process reconstruction. An app-owned optional Service (D17) is the one exception to that lifetime:
its app's stop or reload shuts it down as a child and a reload recreates it, so its ERROR says
reloading the app brings it back. An optional service whose `serve()` returns without failing
(the web UI watcher with no directories to watch) is not a failure: it is STOPPED, and its own log
is the only signal (D8's unrequested-return rule is for required services only).
**Pick root-exit for everything instead if** an optional service with live leftover work is judged more
dangerous than a process restart.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose type-driven escalation over always-exit, to stop an optional watcher's failure from restarting every app, accepting that an optional service stays dead in place with any leftover work running until a manual restart, announced by one ERROR. Reworded at the re-challenge for D17: there is no restart to refuse, so the outcome applies to any post-startup failure. At the narrow re-challenge (Finding 1), chose not shutting the service down over a shutdown that would need FAILED to survive it, so its status keeps the outcome with no new invariant.

### D3: What happens when the bus dies?

**Deciding factor:** no peer supervises its event channel from inside it.

**Recommendation:** detect bus death without relying on the bus, then start a fatal shutdown. Shutdown
must complete with the bus dead. No in-process bus restart. D8 decides the detection mechanism and D9
decides how sends behave.

"Bus death" is the bus's first post-handoff serve failure. The bus is a required service (D17), so its
failure takes the same report-to-D14 path as any other required service, with no bus-specific case.
That retires today's by-name `BusService` special case (`on_bus_service_running`). A crash loop is
made visible the way peers do it: the exit code and the CRITICAL fatal-error line, kept by the
external supervisor (the add-on log, `docker logs`, the journal). Hassette doesn't read the previous
run's reason back at startup.
**Pick in-process bus restart instead if** process restarts turn out to be frequent in practice. They
aren't today.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose fatal shutdown over in-process bus restart, to match OTP/HA root-failure handling, accepting a full process restart on bus death. The first challenge's declarative first-failure-fatal spec, and the re-challenge's `budget_intensity=0` constant for it (Finding 9), became unnecessary under D17: every required service is fatal on first failure. The boot-time log of the previous fatal reason, accepted at re-challenge 1 (Finding 10), was dropped at re-challenge 2 (Finding 1): it read a DB-backed record blind to DB-caused loops, and no peer reads the reason back at startup; the supervisor's retained log covers every case.

### D4: What is the blast radius of a broken app?

**Deciding factor:** HA config entries: one broken entry is stuck in place with a `require_restart`
signal, and the rest keeps running.

**Recommendation:** a broken app instance affects only itself, never the process or its siblings.
An instance flagged needs-restart (D5) is recovered by restarting hassette manually.
**Pick process exit instead if** never. Apps are user code and must not restart the framework.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose app-scoped failure over process exit, to keep unrelated automations running, accepting that an instance stuck on never-ending work needs a manual hassette restart (no restart command; #1390 closed).

### D5: What happens when an app hook outlives its timeout?

**Deciding factor:** Python can't kill a coroutine. Python peers stop waiting and log (HA setup,
AppDaemon, pyscript); HA config entries add one flag, `FAILED_UNLOAD`, and refuse reload until a
restart. No peer watches abandoned work to clear a state automatically.

**Recommendation:** a timed-out hook is cancelled (D10), and the instance's `TeardownReport` decides
what follows. If work may still be running (the predicate defined in D18), the instance is
flagged **needs restart**. The instance is reported `FAILED`, for a timed-out init or stop alike,
since the operation didn't finish: `AppRegistry` records a failure entry, as it already does for a
failed init, while the resource object itself ends STOPPED (its status only says orchestration
finished). One ERROR names the pending tasks and says to restart
hassette, and the flag stays until the process restarts. Otherwise the instance is ordinary failed
and reloadable. The `TeardownReport` records a timed-out hook as its own cause, distinct from a
raised one, so the outcome can say "timed out" (D15); like other hook causes it is diagnostic only
for D18's predicate. D12 decides what the flag blocks.
**Pick observed auto-clear instead if** a cancellation-swallowing hook that eventually finishes must
recover without a restart. No peer has found that worth the machinery.
**Reversibility:** easy
**Ratified:** Chose HA's needs-restart flag, set from the existing `TeardownReport`'s pending-work evidence, over a stuck state that clears when abandoned work is observed ending, to match the peer norm and drop quiescence observation, accepting that an app whose hook swallows cancellation needs a hassette restart even if its work would have finished. Re-evaluated at the sketch re-challenge (Finding 2), replacing stuck-until-the-work-ends. At the narrow re-challenge (Finding 1), chose carrying FAILED in the `AppRegistry` failure entry over keeping it on the resource's status through shutdown. At the D19 re-challenge (Finding 14), chose FAILED for any timed-out stop, with a timed-out cause distinct from a raised hook, over FAILED only with pending work.

### D6: Which lock guards app reload decisions?

**Deciding factor:** HA's per-entry `setup_lock` covers the whole unload-then-setup sequence, and
`start_instance()` already re-reads state under the lock.

**Recommendation:** the per-app-key lock covers the whole operation: the decision (dormant check,
changed indices, valid indices), the stop, the replacement gate (D12), and the create. Every reload and
config-change path re-reads its inputs under the lock. Contention keeps today's split: an HTTP action
that finds the app key busy is refused with 409 (the existing in-progress check), and an internal
reload or config change waits for the lock. Setup runs under the same lock, so no reload can
interleave with a setup in flight. The replacement gate itself, and how a refusal is reported, are
D12's.
**Pick finer-grained locks instead if** whole-app-key serialization measurably delays unrelated
instances. Nothing suggests it does.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose one per-app-key lock across decide+stop+create over the current unlocked decision (or finer-grained locks), to close #1689 gaps 1 and 2, accepting serialized per-instance reloads within one app key. At the re-challenge 2 comb, the in-flight refusal was folded into the existing busy (409) / wait split, and the gate's paths moved to D12.

### D7: How does `Service._initialize_body()` achieve "RUNNING after initialize"?

**Deciding factor:** fewest moving parts that make every failure belong to exactly one side of the
handoff. The handoff is the initialization body completing.

| | A: Start `serve()` last | B: Keep spawn order, move the RUNNING transition | C: Keep spawn order, route early serve failures to the attempt |
|---|---|---|---|
| Change | Spawn the serve task after `after_initialize()` and child init; `_serve_wrapper()` still sets RUNNING when serve starts | Spawn serve where it is; `_initialize_body()` sets RUNNING after children; `_serve_wrapper()` no longer does | Spawn serve where it is; a serve failure before init returns is handed to the init attempt to raise, not to `handle_failed()` |
| Can serve fail mid-attempt? | No. Spawning the serve task is the body's last step, with no await after it, so serve's first step runs after the body has completed: every serve failure is post-handoff and reported (D8), and every body failure is the attempt's | Yes: serve runs, but status stays STARTING. Its failure still goes through `handle_failed()` unless also rerouted | Yes, but it is owned by the attempt |
| Services affected | Any service whose children or `after_initialize()` need serve already running. None, per Assumed: no Service's `after_initialize()` or children wait on its serve | None by timing | None by timing |
| Code | Reorder plus doc update; the docstring's deadlock warning becomes a rule: a Service's children and `after_initialize()` must not wait on the parent's `serve()` or readiness. It goes into the resource-lifecycle rule file, and a Service whose child or `after_initialize()` waits on the parent's serve fails visibly instead of deadlocking | Two transition sites to keep in sync | New cross-task failure handoff |
| Matches prior art | trio/OTP: init completes, then the loop runs | systemd `notify`: running ≠ started | trio's pre-`started()` exception routing |

**Recommendation:** A, because it removes the mid-attempt window by ordering instead of guarding it,
and the scan found no service that needs serve running before its children. Behavior to pin: a serve
failure never surfaces from the attempt; D1's boot fail-fast covers failures of the body itself. Once
D8's report exists, a serve failure at boot follows D2 like any other: a required service exits
through D14 and an optional one ends dead in place. For that to hold, a startup wave treats an
optional member whose initialization attempt succeeded and whose serve task has since ended (FAILED,
CRASHED, or STOPPED by an early return) as settled, instead of waiting on its readiness until the wave
timeout fails startup: an optional watcher marks ready inside `serve()`, so one whose `serve()` ends
first never becomes ready. The wave watches each Service member's serve task as a wake source beside
readiness and the attempts, so it settles at once rather than at the timeout. The rule lives in
`wait_for_wave`, so both the startup waves and `start_children_and_wait` (the harness's path) get it,
and it reads the serve task and the declaration through an internal hook rather than the private
serve-task attribute. The hook, like `add_child`'s required-parent check, is defined on `Resource` and
overridden by `Service`, the shape of the existing `_force_terminal` hook: the wave helpers and `Resource`
sit below `Service` in the import graph, so neither can name it. A failed attempt stays
fatal for every member (D1), and a required member's serve failure is D14's. The wave's "a member that
loses readiness mid-wave has to regain it" rule no longer applies to a settled optional member.
Behavior to pin: an optional watcher whose `serve()` raises before marking ready leaves boot
completing promptly, with the watcher FAILED and its one ERROR.
**Pick B instead if** the audit finds a service whose child initialization needs its serve loop
draining work. **Pick C instead if** that same need shows up and B's double-path proves unworkable.
**Reversibility:** easy (local to `Service` and its two `Resource` hooks)
**Ratified:** Chose starting `serve()` last over moving the RUNNING transition or routing early serve failures, to remove the mid-attempt window instead of guarding it, accepting a readiness-timing audit of every service. At the pre-build comb for issue 4 (2026-10-26), chose letting a wave settle on a failed optional member over keeping the wave strict, so "optional" holds at boot too. At the ship-time challenge for issue 4 (2026-10-26), chose underscore-prefixed hooks on `Resource` that `Service` overrides over public hooks or moving both checks off `Resource`, to keep the base-class contract visibly framework-internal without duck typing around the import cycle, accepting two service-only hooks on the base class.

### D8: How does the supervisor learn that a service failed?

**Deciding factor:** detection outside the supervised channel (OTP links, systemd SIGCHLD/watchdog). A
bus-delivered failure is what makes a dead bus undetectable and what gives one failure two signals.

| | A: Keep bus FAILED events, add a bus-death hook | B: Direct report to the supervisor for every service; bus events become telemetry only |
|---|---|---|
| Signals per failure | Two (attempt result and bus event), so failure ownership still has to be inferred | One: a failed attempt raises; a post-handoff serve failure is reported once, directly |
| Dead bus | Needs a special out-of-band hook (done-callback on the bus serve task, registered by `Hassette`) | Reported like any other service failure, then routed fatal by D3 |
| What it deletes | Nothing | The watcher's internal bus listeners, `reconcile_after_bus_recovery()`, `on_bus_service_running()`, the stale-status check, and the `_restarting` set with its step-order guards |
| Coupling | Unchanged | Lifecycle code reports to a routing method on `Hassette`; resources gain one call-out |
| User-visible | Unchanged | `on_hassette_service_failed` etc. keep firing as telemetry; only the watcher stops consuming them |
| #3036 size | Full state machine still needed to arbitrate two channels | Smaller: one channel, and with D17 the supervisor only routes a report by whether the service is required, so the watcher goes |

**Recommendation:** B, because it removes the cause of the double handling instead of arbitrating it,
and it solves dead-bus detection with no special case.
**Pick A instead if** something outside the watcher depends on the watcher acting on bus events.
Nothing found.

**Acting consumers of service-status events, and where each goes.** These are the only framework
subscribers that act on `HASSETTE_EVENT_SERVICE_STATUS`; `RuntimeQueryService` only observes, for WS
and telemetry:
- the watcher's `restart_service` → the direct report;
- the watcher's `shutdown_if_crashed` → crashes reach D14 through the direct report;
- the watcher's `on_service_running` / `await_service_readiness` (budget reset and the
  readiness-timeout warning) → deleted: nothing restarts (D17), and boot readiness stays with the
  startup waves;
- the watcher's `on_bus_service_running` / `reconcile_after_bus_recovery` → deleted (D3: no
  in-process bus recovery);
- `SessionManager`'s CRASHED listener → deleted; teardown's session finalize records the outcome (D14).
  What only it used goes with it: `SessionManager`'s `Bus` child, its stored session error and the
  finalize branch that writes it, leaving finalize's fatal-reason branch.
- `AppLifecycleService`'s own `handle_crash` on a failed bootstrap → deleted: bootstrap moves into
  `AppHandler.serve()` (D17), so its failure is an ordinary report against `AppHandler`.

With all of these gone, `ServiceWatcher` has nothing left but routing, so it is deleted and the routing
lives on `Hassette` (Recipient below). Its `logging.service_watcher` config key goes with it, with a
changelog migration note (a config that still sets it stops at load, per Assumed).

**Report contract.**
- **Report site.** A dedicated, synchronous report function, called only from `_serve_wrapper()`
  after the handoff, at every failure exit: a raised exception, a `FatalError`, a `ClosedResourceError`
  outside shutdown, and a required service's unrequested return or cancellation (reported, and passed
  to `handle_failed()`, as a new framework exception carrying a reason
  saying `serve()` ended without shutdown). It is the first thing the wrapper does on that exit, before
  `handle_failed()` or `handle_crash()`: those await `send_event()` on a bounded channel with no
  timeout, so reporting after them would let a stalled bus delay the very failure meant to be detected
  without it (D3). It never awaits, so nothing can move the service to STOPPED before `handle_failed()`
  writes FAILED (whose terminal guard would otherwise swallow it).
  `handle_failed()` and `handle_crash()` stay status and telemetry. Pre-handoff init failures and
  swallowed shutdown-hook failures are never reports. Behavior to pin: a non-bus required service
  failing while the event channel is full and undrained still requests shutdown.
- **Recipient.** A report-routing method on `Hassette`, in place from construction, so no startup wave
  can run before it. It routes by the service's declaration (D17): required → D14's escalation
  function, optional → the one ERROR of D2. The test harness's `Hassette` overrides it to a no-op, so a
  required-service failure under a shared harness never latches a fatal reason or requests shutdown;
  harness reset clears nothing extra. The test suite's mock `Hassette` (a sealed `AsyncMock`) gets a
  synchronous no-op for it too, set in `make_mock_hassette` whether or not the mock is sealed (sealed,
  the call raises on an unconfigured attribute; unsealed, it returns an unawaited coroutine), and the
  same for the separate web-test `Hassette` stub.
  The harness docstrings that count its overrides or cite watcher restart tests are updated.
- **After shutdown starts.** "Shutdown requested" means the process-level `Hassette.shutdown_event`,
  not the reporting resource's own. A report arriving after it is set, or after a fatal reason is
  already latched, is logged at ERROR and not escalated, so a clean stop still exits 0.
- **Unrequested return.** For a required service, `serve()` returning, or its serve task being
  cancelled, while `Hassette.shutdown_event` isn't set is a failure report, so a silently stopped bus
  or scheduler can't happen (Posture: no silent states). The service's status becomes FAILED, not the
  STOPPED the wrapper writes for a requested return.

**Reversibility:** hard (changes how supervision is wired; partial rollback re-introduces the guards)
**Ratified:** Chose direct reporting with bus events as telemetry over keeping bus-delivered FAILED events plus a bus-death hook, to give each failure one signal and make bus death an ordinary report, accepting one supervisor call-out from lifecycle code to `Hassette`. The acting-consumer inventory and report contract (dedicated report site, registration at construction, loud undelivered reports) were added at the sketch challenge (Findings 1, 2, 4, 5, 7, 12); registration and undelivered reports were later superseded by the pre-build comb's routing on `Hassette`. At re-challenge 2 (Finding 10), added that post-shutdown reports are logged, not escalated, replacing the deleted watcher admission check. At the pre-build comb for issue 4 (2026-10-26): chose deleting `ServiceWatcher` and routing on `Hassette` over keeping a slim watcher, so the required/optional routing exists once; fixed the report to run before the awaited telemetry sends; pinned the process-level shutdown event and the harness override.

### D9: How do event sends behave once the bus is dead?

**Deciding factor:** shutdown itself emits lifecycle events through `Hassette.send_event()`, whose
underlying channel send has no timeout. A dead consumer plus a full channel would hang shutdown.

| | A: Bus death closes the event streams | B: Timeout on every send | C: Drop sends while a "bus dead" flag is set |
|---|---|---|---|
| Mechanism | On bus death, close the streams; the existing closed-stream drop in `Hassette.send_event()` applies, and blocked senders are released with a broken-stream error that `send_event()` handles | Bounded wait on each send, then drop and warn | Check a flag before sending |
| Already-blocked senders | Released | Released after the timeout | Still blocked (flag checked before the wait) |
| Healthy-path cost | None | A timer per send on the hottest path | One branch |
| Code | Reuses `close_streams()` and the closed check | New timeout config or constant | New flag plus the same blocked-sender gap |

**Recommendation:** A, because it reuses the existing closed-stream path and is the only option that
also releases a sender already blocked on a full channel. `BusService`, which owns the channel and is
the only component that knows whether it is draining, closes the streams whenever its drain loop ends:
before it reports a serve failure (D8), so D14's CRASHED emit is dropped instead of blocking, and on a
requested stop too, since nothing can deliver an event after the loop ends. At boot, failed startup asks
the bus to close the streams unless its drain loop is running, so failed-startup teardown can't fill a
channel nobody drains. A bus init failure's own FAILED send is awaited before any bus code sees the
error, which is why this close is driven from failed startup, not from the bus's init path. Other fatal
exits keep their shutdown telemetry for as long as the bus drains. A dead bus does not release blocked senders
by itself: `BusService` holds a clone of the receive stream, and `EventStreamService` keeps the
original open. Behavior to pin:
- after bus death, no producer blocks and events are dropped. `Hassette.send_event()` already drops on
  closed streams; `EventStreamService.send_event()` raises on a closed stream rather than blocking, so
  every direct caller handles that error the way `Hassette.send_event()` does;
- status transitions still happen. `Resource._shutdown_body()` no longer skips `handle_stop()` when
  the streams are closed, so every resource still reaches STOPPED during the fatal teardown, and only
  the event send is dropped.
**Pick B instead if** a wedged-but-alive bus (not dead, just not draining) also needs to be survivable.
**Pick C instead if** never: it leaves already-blocked senders blocked, which A and B both release.
That is out of scope under the posture.
**Reversibility:** easy
**Ratified:** Chose closing the event streams on bus death over per-send timeouts or a bus-dead flag, to release every blocked producer through the existing closed-stream drop, accepting that a wedged-but-alive bus stays out of scope. At the sketch challenge (Finding 10), chose letting `handle_stop()` run with closed streams over accepting skipped STOPPED transitions. At the re-challenge comb, chose `BusService` closing its own streams before reporting over D14 closing them for every fatal exit, keeping shutdown telemetry for other fatal exits at the cost of one bus-owned cleanup step. At the ship-time challenge for issue 5 (2026-10-27): chose a bus-owned trigger (close whenever the drain loop ends; failed startup closes unless the loop is running) over keying the close on the bus's status or on whether a stop was requested, since both guessed at the bus's state, accepting that a bus init failure with a full channel exits only after the startup timeout, and that a peer failing in the tick before a starting bus enters its loop closes that bus's streams and logs a misleading serve failure.

### D10: Is a timed-out app initializer cancelled?

**Deciding factor:** a timed-out init is being discarded, so its work has no future. Today the
coordinator shields init, so the outer timeout abandons it while it keeps running. Shutdown is
already bounded and cancelled by the coordinator, with the evidence recorded in the `TeardownReport`;
where its timeouts sit is D19's.

| | A: Cancel init on timeout; shutdown unchanged | B: Leave init shielded (today) |
|---|---|---|
| Init timeout | Cancel the init attempt by shutting the instance down (D18): framework teardown removes its listeners and jobs and returns the `TeardownReport`; user shutdown hooks are skipped; D5 applies to whatever is still pending | Init keeps running after the instance is marked failed; late registrations (#1797) happen |
| Shutdown timeout | Each shutdown hook is cancelled at its own deadline, clamped to its operation's deadline (D19) | Same |
| Late registrations (#1797) | Usually prevented: cancellation lands at the next await | Happen |
| Matches | `anyio`: cancel, then bound and observe; #1797's fix direction | — |

**Recommendation:** A, because it shortens a discarded init. Shutdown hooks keep being cancelled at
their deadlines; D19 decides where those deadlines sit.
**Pick B instead if** apps commonly do work in `on_initialize` that must not be interrupted mid-way
(for example, creating HA helpers).
**Reversibility:** easy
**Ratified:** Chose cancelling a timed-out init over leaving it shielded, to cut short discarded work, accepting that a cancellation-ignoring init still ends flagged needs-restart (D5). At the sketch re-challenge (Finding 6), "never cancel shutdown" was corrected: shutdown hooks are cancelled at their deadlines and stay cancelled. Re-ratified with D19, which moves those deadlines to the hooks alone, clamped to the operation's deadline; the shutdown body has no deadline of its own beyond its stage or entry deadline. At D19's second re-challenge (Finding 12), hooks stay inline with cancel-and-wait, so a hook that ignores cancellation is bounded by the stage or entry deadline above it, not abandoned on its own.

### D11: Where does an app instance's needs-restart flag live?

**Deciding factor:** it must survive the instance being unregistered (a stop unregisters it), must be
read by the reload gate (D12), the routes and the UI, must not stretch a type that services also use,
and must not make every registry reader exclude it.

| | A: New `ResourceStatus` value (wire) | B: Keyed record in `AppRegistry`, outside the instance map | C: Tombstone entry in the instance map |
|---|---|---|---|
| Shape | e.g. a new `NEEDS_RESTART` value | `(app_key, index) → reason and pending task names`, beside the live instances | `InstanceEntry` gains a phase |
| Survives stop/unregister | Only if the registry keeps the entry anyway | Yes | Yes |
| Live registry readers | Every `ResourceStatus` consumer handles an app-only value | Untouched | Each one must exclude tombstones |
| Wire change | `ResourceStatus` enum plus compat entries (Breakdown, "Applies to all") | `AppInstanceInfo` gains a needs-restart flag and reason; the snapshot includes flagged unregistered instances | Same as B |
| Matches HA | — | Per-entry state with `require_restart` | — |

**Recommendation:** B, because it holds app-only state where the gate and the UI can read it without
changing what "registered" means. `ResourceStatus` stays unchanged and honest. For `AppStatus`, a
flagged instance counts as not running, the same way FAILED does (`DEGRADED` beside running siblings,
`FAILED` if none run). Nothing clears the record except a process restart. A config change doesn't prune it either, because the
abandoned work is still running: the record keeps counting toward `AppStatus`, and the snapshot
renders a flagged row whose app or index has left config, using the instance name stored in the
record.

The flag is exposed in the API, CLI and UI only, not in the liveness payload, matching HA's
`require_restart`. **Pick a liveness-payload count instead if** an unattended install must be alerted
externally.

The flag is deliberately separate from service statuses. Services and apps live on
separate UI surfaces (diagnostics vs the apps page), and each is mapped once, in its own place.

The registry record is the instance's persistent state for later readers. D15's outcome is what one
request did. Both are set in the same step under the app-key lock.

**Reversibility:** hard (wire shape the UI and client consume)
**Ratified:** Chose a keyed needs-restart record in `AppRegistry`, outside the instance map, over a new `ResourceStatus` value or a tombstone entry, to keep app-only state off the type services share without making registry readers exclude it, accepting an `AppInstanceInfo` wire change. Separate service/app vocabularies were chosen at the first sketch challenge (Finding 20); the tombstone model chosen there was replaced at the re-challenge (Findings 2, 7), and concurrent app shutdown (first-challenge Finding 16) moved to D18. At re-challenge 2 (Finding 9), chose keeping the record counting until restart, with the snapshot rendering orphaned rows, over pruning it with config, accepting a DEGRADED app after a config edit until hassette restarts. At D19's second re-challenge (Finding 18), accepted that a needs-restart record outlives the config that produced it, so its row stays orphaned until restart. At the final challenge (Finding 8), chose keeping the flag in the API, CLI and UI only over adding a count to the liveness payload, matching HA's config-entry `require_restart`, accepting that an unattended install gets no external alert for a needs-restart instance.

### D12: What old-instance evidence allows a replacement?

**Deciding factor:** the danger is two live incarnations (k8s's at-most-one identity), not an exception
in user code. HA refuses reload after any failed unload, but hassette reloads on every file save, so a
buggy `on_shutdown` that merely raises would force a restart on every edit.

Evidence is the instance's `TeardownReport`, which the coordinator already produces, read through
D18's "work may still be running" predicate. That predicate separates causes that only record
something raised or timed out and has since ended from evidence that work may still be alive.
Threads, subprocesses and external side effects the user starts outside hassette's context are
invisible under every option, and so is the work D18's predicate lists as not covered (sync worker
threads, parallel-mode handlers and scheduler jobs).

| | H: Refuse while flagged needs-restart (pending work only) | A′: Refuse until abandoned work is observed ending | B: Refuse after any failed teardown (HA's rule) | P: Never refuse (Python norm) |
|---|---|---|---|---|
| `on_shutdown` raised, nothing pending | Reloadable, with an ERROR | Reloadable | Needs restart | Reloadable |
| Work still pending after cancellation | Needs restart | Stuck; clears when the work ends | Needs restart | Reloadable; two incarnations can overlap |
| New machinery | One keyed flag (D11) | A quiescence primitive, plus callbacks or derived re-checks | One keyed flag | None |
| Dev reload loop | Only cancellation-swallowing code forces a restart | Same, until the work ends | Any cleanup bug forces a restart per edit | Never blocked |
| Matches | HA `FAILED_UNLOAD`, narrowed to live work | Erlang `soft_purge` (a VM feature) | HA `FAILED_UNLOAD` | AppDaemon, pyscript |

**Recommendation:** H, because it refuses the overlap the gate exists to prevent, within the coverage
D18 states, with evidence that already exists, and leaves raised-but-finished teardowns reloadable.
The gate runs under the app-key lock (D6) on every path that creates an instance (app start, instance
start, restart or reload, config-change reconcile, autostart), refusing a flagged `(app_key, index)`
with D15's "refused (needs restart)" outcome. A refused path with no response channel (a file-watcher
reload, reconcile, autostart) logs one ERROR naming the instance and saying to restart hassette; it is
not replayed.
**Pick B instead if** a raised `on_shutdown` should also force a restart, as in HA, accepting a
restart per edit while developing a buggy hook. **Pick P instead if** overlapping incarnations from cancellation-swallowing code are acceptable in
exchange for no new state. **Pick A′ instead if** such instances must recover without a restart.
**Reversibility:** easy
**Ratified:** Chose refusing replacement only while an instance is flagged needs-restart (work still pending after cancellation) over observed auto-clear, HA's any-failed-teardown rule, or never refusing, to prevent overlapping incarnations with existing evidence and keep hot reload usable, accepting a manual hassette restart for the rare cancellation-swallowing app. Re-evaluated at the sketch re-challenge (Finding 2), replacing no-terminal-state and dropping the quiescence primitive from PR #1782's branch. At re-challenge 2, the gate was widened from reload to every instance-creating path (Finding 8), and its evidence gained active sync workers with stated coverage (Finding 7). At D19's second re-challenge (Finding 9), per-bucket sync-worker tracking was dropped: sync workers join the uncovered list, and only executor threads surviving the exit join count (D19's hard exit).

### D13: Where does per-service supervision state live?

**Deciding factor:** each owner holds its own state. `EXHAUSTED_COOLING` and `EXHAUSTED_DEAD` are
supervision outcomes that the watcher writes onto the service through `set_service_status()`, so
today a resource's status mixes its own lifecycle with its supervisor's decisions.

| | N: No supervision state; `EXHAUSTED_*` leave `ResourceStatus` | R: Per-key record (episode task + COOLING/DEAD marker) |
|---|---|---|
| Needed under D17 | Yes: nothing restarts, so there are no episodes, budgets or cooldowns to track | Only with in-process restarts |
| What FAILED means | Final: nothing retries it, for every service (D2 gives its lifetime) | "Failed, maybe retrying"; the marker says which |
| Wire and UI | Two values leave `ResourceStatus` (hassette-wire); `retry_at` leaves all three service payloads (the internal `ServiceStatusPayload`, the WS `ServiceStatusData` and the HTTP `ServiceInfo`); the frontend drops their mapping (diagnostics service row, sidebar groups, status utils, and the hand-written WS types) | Same removal, plus a dead flag and reason |
| Terminal guard | `handle_failed()`'s terminal guard stays; a shutdown still ends STOPPED, which means only that orchestration finished, and outcomes live in the `TeardownReport`, the `AppRegistry` failure entry (D5) or the un-shut-down service's own status (D2); `_force_terminal()` loses its terminal-status preservation (D18) | The guard and `_force_terminal()` consult the DEAD marker |

**Recommendation:** N, because D17 removes everything a supervision record would track.
`ResourceStatus` keeps only lifecycle values (NOT_STARTED, STARTING, RUNNING, STOPPING, STOPPED,
FAILED, CRASHED).
**Pick R instead if** D17 is reversed.
**Reversibility:** hard (wire enum)
**Ratified:** Chose no supervision state, removing `EXHAUSTED_*` and `retry_at`, over a per-key supervision record, because D17 leaves nothing to supervise, accepting a wire change and a frontend status-mapping removal. Replaced at the re-challenge: first the five-state machine became a per-key record (Findings 1, 3, 4), then D17 removed the need for one. A "FAILED survives shutdown" rule added by the comb was dropped at the narrow re-challenge (Finding 1): five sites write the end-of-shutdown status, and no consumer needs it once D2 skips the shutdown and D5 uses the registry.

### D14: Do the service fatal paths share one exit route?

**Deciding factor:** every fatal exit takes one route, starts shutdown immediately, and depends on
neither the event bus nor the database. Peers (systemd, Docker, Kubernetes, HA core) record a fatal
reason in the exit status and the log, never with blocking I/O before shutdown. Today PERMANENT
exhaustion calls `hassette.shutdown()` inline and restart refusal calls `request_shutdown()`.

**Recommendation:** one escalation function on `Hassette`, beside its existing fatal-reason latch and
called by its report routing (D8); `ServiceEscalationMixin` goes:
1. record the fatal reason in memory (first reason wins); it sets the exit code and the CRITICAL
   fatal-error line. The reason keeps today's shape, naming the service and the exception type
   (or, for an unrequested return, that `serve()` ended without shutdown), now built here instead
   of in the watcher's CRASHED listener;
2. call `request_shutdown()`;
3. emit CRASHED as telemetry without awaiting it, so a full or dead channel never delays shutdown.
   The emit runs as a best-effort task in `Hassette`'s own bucket that logs a failed send at DEBUG;
   one cancelled or dropped by teardown is expected and not reported as leftover work.

Behavior to pin: shutdown is requested even when the event channel is full and undrained.

Nothing on this path awaits the database. Teardown's existing session finalize writes the fatal reason
to the session record, best-effort. `SessionManager`'s CRASHED listener is deleted, since finalize
already records the outcome.

Failure reports from required services (D2, D3) and `FatalError`s raised by required services (a
serve failure carrying one arrives through the D8 report; one from an init body at boot is D1's) use
it. A failed app bootstrap reaches it the same way: bootstrap runs in `AppHandler.serve()` and
`AppHandler` is required (D17), so the failure is an ordinary report rather than a second caller of
this function. Today bootstrap runs as detached background work whose crash exits the process only
through the watcher's CRASHED listener, which D8 deletes. It is a framework failure, not an app
failure, so D4 doesn't apply.

Two side effects are accepted. A required service that fails (FAILED) still gets a CRASHED telemetry
event from step 3 while the process exits, so the event and the status briefly disagree. And deleting
`SessionManager`'s CRASHED listener removes the only writer of the session row's `error_type` and
`error_traceback`; finalize writes the fatal reason as `error_message` only, and the traceback stays
in the log the external supervisor retains. A `FatalError` from an optional service
ends it dead in place like any other failure (D2). With no restarts, `fatal_error_names` has nothing to route around and
goes (D18).
**Pick keep-both instead if** an inline shutdown is needed somewhere for ordering. None found.
**Reversibility:** easy
**Ratified:** Chose one escalation function on `Hassette` that records the fatal reason in memory, calls `request_shutdown()` immediately and emits CRASHED without awaiting it over keeping inline `shutdown()` or writing the session record before shutdown, to let `run_forever()` own every fatal exit with no bus or database dependency, accepting that the session record gets the reason only if teardown's finalize reaches the database, the deletion of `SessionManager`'s CRASHED listener, and a duplicate CRASHED event when a required service's `FatalError` already emitted one (narrow re-challenge, Finding 4), and that a fatal report landing just after the last startup wave is ready can be preceded by the "Hassette is running" log line, with the exit code and reason still correct (Finding 7). Reframed at re-challenge 1 after D17; the direct session write was dropped at re-challenge 2 (Findings 1, 3) to match peers. At the pre-build comb for issue 4 (2026-10-26), chose keeping a failed app bootstrap fatal over making it app-scoped, since it is a framework failure, and then routing it through the ordinary report by making `AppHandler` a required Service over a direct call into this function, so the harness override and the post-shutdown guard apply without a second guarded entry point.

### D15: What do app lifecycle actions return, and how do the routes map it?

**Deciding factor:** report the operation's own result. Reading the registry after the lock is released
is racy, and a stop never shows a failure because stop unregisters regardless. HA's reload endpoint is
synchronous, refuses with a 4xx and returns `require_restart`.

| | A: Typed outcome returned from `AppLifecycleService` | B: Keep registry read-back, change status codes |
|---|---|---|
| Source of truth | The operation's own per-instance results (succeeded / failed / refused / needs restart), with reason | `get_failed_instance_infos()` after the lock is released |
| Concurrent-request misattribution | Gone | Remains (documented accepted risk today) |
| Stop failures | Visible | Invisible |
| HTTP mapping | Worst outcome wins: any failed or newly flagged instance gives 500, otherwise any refused (needs restart, app key busy) gives 409, otherwise 200. The body always lists every instance's outcome and names each instance that needs a hassette restart. A stop whose hook timed out is failed with the reason "timed out", whether or not work is still pending; pending work additionally flags it needs-restart (D5) | 200 instead of 202; refusal codes added |
| Frontend | Minimal: accept 200, show the refusal or failure message and restart-required text | Same |
| Error bodies | A 409 or 500 from an app action is a `ProblemDetail` (RFC 9457) carrying an optional `outcomes` extension member with the per-instance list; the needs-restart refusal gets its own `ProblemCode` | Unchanged |
| Wire | `ActionResponse` keeps `app_key`, `action` and `instance_index` and gains the outcomes alongside; `ProblemDetail` gains `outcomes`; OpenAPI and types regenerated, compat entries (Breakdown, "Applies to all") | Same |

**Recommendation:** A, because it fixes misattribution and invisible stop failures at the source, and
it is the outcome contract the needs-restart flag needs anyway.
**Pick B instead if** the outcome type would need to thread through more layers than the lifecycle
mixins already return values from.
**Reversibility:** hard (published API contract)
**Ratified:** Chose a typed per-instance outcome returned by `AppLifecycleService` over registry read-back with new status codes, to report each request's own result including stop failures, accepting an `ActionResponse` wire reshape and a minimal frontend update. At the re-challenge comb, chose worst-outcome-wins status codes over always returning 200 with the outcomes in the body, so a failure never hides behind a 200, accepting that a partly successful bulk request returns an error code. At the D19 re-challenge (Finding 14), chose reporting any timed-out stop as failed with a distinct "timed out" reason over failing it only when work is still pending, matching systemd's `Result=timeout` and D5, accepting a 500 for a hook that ended promptly once cancelled. At D19's second re-challenge (Finding 13), chose carrying the outcomes on error responses as an optional `outcomes` extension member of `ProblemDetail`, with a named needs-restart `ProblemCode` and `ActionResponse` keeping its identifying fields, over a separate error envelope, so 409/500 bodies stay RFC 9457 problem details.

### D16: Which nearby issues ride along?

**Deciding factor:** include an item only if the Done-when fails without it, or if it is cheaper
inside this work than after it.

| Item | Recommendation | Why |
|---|---|---|
| #1222 concurrent init/shutdown interleaving | Close as obsolete | The early return it cites is gone; the single-attempt coordinator covers all three gaps (resource-lifecycle rule file, "One attempt per resource") |
| #2697 remove `strict_lifecycle` | In, by deletion (D18) | D7 and D13 change status transitions, which should be tested on the behavior production runs; cheap pre-V1 |
| #1715 handler cancels itself via its own resource's shutdown | Out | Real but independent of outcome recording; keep in `epic:correctness` |
| #1721 remaining function splits | Out, and trim the issue | `restart_service()`/`execute_restart()` are deleted by D17; the coordinator and `_shutdown_body()` splits are code quality |

**Recommendation:** take the table as written.
**Pick differently if** you want the milestone to carry the correctness bug #1715 too.
**Reversibility:** easy
**Ratified:** Chose closing #1222, taking #2697 in by deletion (D18), and leaving #1715 and the trimmed #1721 out over also carrying #1715, to keep the milestone to what its Done-when needs, accepting that the self-cancel bug waits in the correctness bucket.

### D17: Does hassette restart services in-process at all?

**Deciding factor:** whether a mid-run crash of a required service is common enough to justify a
supervisor inside the process, when every other fatal path (D1 boot failure, D3 bus death) already
relies on an external one. The routine failure, losing Home Assistant, never reaches the supervisor:
`WebsocketService` reconnects in place and its `serve()` doesn't exit on HA-side failures. Any other
failure of a required service, whatever its cause, is rare enough that a process restart is an
acceptable price. That includes `DatabaseService` raising on persistent heartbeat failure, an
environmental fault (a full disk, a locked file) that exits the process and fails the next boot the
same way until it is fixed, which the required-DB direction (#2695) already accepts.

| | X: No in-process restart | K: Keep watcher restarts |
|---|---|---|
| Required service crashes mid-run | D14 fatal exit; the external supervisor restarts the process | Backoff, budget and cooldown, then exit when exhausted |
| Optional service crashes | Dead in place with one ERROR (D2) | Restarted per its spec |
| Machinery | Removes `RestartBudget`, backoff, cooldown, same-object service restart, and the watcher (D8) | Keeps all of it |
| `RestartSpec` / `RestartType` | Replaced by one required/optional declaration per service | Unchanged |
| Cost of a transient crash | Every app re-initializes with the process | Only that service restarts |
| Bare `hassette run` without a restart policy | The process stays down after a crash; the docs require a restart policy, as D1 and D3 already assume | Survives in-process |
| Matches | HA core under the Supervisor; systemd/k8s process supervision | OTP, which has a VM to make it cheap |

Classification: required are `BusService`, `SchedulerService`, `SyncExecutorService`,
`WebsocketService`, `DatabaseService`, `CommandExecutor`, `WebApiService` and `AppHandler`.
`AppHandler` becomes a `Service` whose `serve()` runs app bootstrap and then waits for shutdown
(`after_initialize()` keeps marking it ready, so the boot wave doesn't wait on Home Assistant); a
failed bootstrap leaves hassette with no apps, so it is fatal (D14). `WebApiService` is
required because it is the control plane: the CLI and the UI talk to it, and it serves the liveness
probe (`/api/health/live`), so a live process with a dead API would leave automations running with no
way to observe or control them. Optional are the two file watchers (`FileWatcherService`,
`WebUiWatcherService`); losing one only disables hot reload. A `Service` subclass that doesn't declare
required or optional fails at class definition, replacing today's missing-`restart_spec` warning
(Posture: loud failure).

The declaration is one boolean `ClassVar` on `Service` named `required` (public API: the migration
note, the docs and user Services use it), enforced in `__init_subclass__` by today's
`restart_spec` rule: classes with abstract methods are skipped, and a concrete class must declare it
in its own body, so a subclass of a concrete service redeclares it. `Service` itself defaults it to
`True`, so an abstract-skipped intermediate that is instantiated anyway (`FinalMeta` doesn't enforce
abc) routes as required, the loud side, instead of failing the routing read. Plain `Resource`s are
untouched.
"Required" means "its failure ends the process", which only a framework service owned by `Hassette` may
claim: `add_child` raises when a required Service's parent isn't `Hassette`. That is a guard on
`add_child` only; a Service constructed directly (as unit-test fixtures do) bypasses it.

`AppHandler` as a Service: `serve()` calls `AppHandler.bootstrap_apps()`, which stays the one
bootstrap entry point (it keeps `has_bootstrapped()` in step, and harness reset calls it directly),
then parks on `AppHandler`'s own shutdown event; `_bootstrap_task` goes. Marking ready in
`after_initialize()` rather than in `serve()` is a deliberate deviation from the resource-lifecycle
rule file's readiness rule (bootstrap waits on Home Assistant, which no boot wave may), recorded in
that file's deviations list and the mark-ready timing test's categories. A failed bootstrap now clears
`AppHandler`'s readiness through `handle_failed()`; in production the report's shutdown ends the wave
first, while under the harness's no-op routing a bootstrap failure during harness start surfaces as
that start timing out. `bootstrap_apps()` keeps its own exception log and re-raise; only its
`handle_crash` call goes. hassette doesn't
document user-defined Services as a feature, but `RestartSpec`, `restart_spec` and the restart docs
were public, so the change ships with a changelog migration note saying what replaced them and that an
app-owned Service must declare itself optional.

The same-object re-initialization guard (`RestartRefusedError` raised by the coordinator after an
unsafe teardown) stays as an invariant of "one attempt per resource", though nothing triggers it in
normal operation.

**Recommendation:** X, because the routine failure is already handled in place, every other fatal path
already exits, and it removes the largest mechanism this milestone would otherwise build.
**Pick K instead if** a required service turns out to crash transiently in practice often enough that
restarting every app is disruptive, or users commonly run without a restart policy.
**Reversibility:** hard (restart machinery could return behind D8's report, but D13's wire removal
would need reversing)
**Ratified:** Chose no in-process service restart, with `WebApiService` required as the control plane, over keeping watcher restarts, to delete the restart machinery and give every service failure one outcome, accepting that a transient crash of any required service restarts every app, that a persistent environmental database fault crash-loops until fixed (as the required-DB direction, #2695, already implies), that hassette must run under a restart policy, and that on the HA add-on, where Watchdog is opt-in, Supervisor stops restarting after 10 attempts in 30 minutes, leaving automations stopped under a persistent fault until the user starts the add-on (re-challenge 2, Finding 13). Added at the sketch re-challenge from an inventory of built lifecycle machinery. At the pre-build comb for issue 4 (2026-10-26), chose rejecting a required app-owned Service at `add_child` over silently treating it as optional, to make the change loud for anyone running their own Services; and added `AppHandler` to the required set as a Service whose `serve()` runs app bootstrap, since bootstrap was already serve-shaped work and this lets its failure take the ordinary report path.

### D18: What already-built lifecycle machinery does the milestone remove?

**Deciding factor:** remove what the milestone touches anyway, or what makes its decisions false or
harder to state, while the project is young. Being already built is not a reason to keep something.
Source: an inventory of the lifecycle, teardown, supervision and app-lifecycle code against the
prior-art brief's peers.

**In the milestone:**

| Remove | Why | Replaced by |
|---|---|---|
| The app layer's own stop timeout, `cleanup_failed_instance()` and its cleanup-timeout setting | When the app timeout fires before the coordinator's, no `TeardownReport` exists for D5 to read; the hand-rolled cleanup never seals the bucket or shuts down children | The app init deadline stays the one bound on an app's init; on expiry, or on any failed init, the instance is shut down (D10), which cancels the init, skips user shutdown hooks, and returns the `TeardownReport` D5 reads. App and resource shutdown timeouts become one setting |
| `strict_lifecycle`, the `ResourceStatus` transition table, setter validation and its error type, and the setting's other readers (issue 2) | Production only warns, and the table has caused failures (#1071) | Nothing; #2697 is done by deletion |
| Restart machinery: `RestartBudget`, `RestartSpec` and `RestartType` as a whole (D17), same-object service `restart()` and the generic restart front door in the resource operations module, the watcher's admission checks, `fatal_error_names`, `log_service_event`, and `ServiceWatcher` itself (its `Bus` child, bus dependency and `logging.service_watcher` key with it) | D17 | One required/optional declaration per service, routed by `Hassette` (D8) |
| `_force_terminal()`'s terminal-status preservation | Exists only for `EXHAUSTED_*` (D13) | — |
| Restart safety meaning "any recorded cause" | A raised or timed-out hook, body or cleanup was cancelled and has ended | One predicate, "work may still be running", read by D5, D12 and the coordinator's re-init guard (kept as a cheap invariant, D17). It is true when the report's `pending_tasks` is non-empty, when it records `INITIALIZATION_TASK_PENDING` (which carries no task name), when the evidence is incomplete (`FORCED_TERMINAL`, `COORDINATOR_FAILED`), or when a child's report satisfies the same predicate. Coverage: the instance's own tasks and its children's (including its `Bus`, so non-parallel handlers). Not covered: sync worker threads (an `AppSync` hook or sync handler on a `SyncExecutorService` thread keeps running after its awaiting coroutine is cancelled, and the executor keeps no per-resource owner for it), and parallel-mode handlers and scheduler jobs, which run in `BusService`'s and `SchedulerService`'s buckets; which resource owns a handler's task is #1715's question, left out by D16. At process exit, executor threads that survive the foundation stage's join trigger D19's hard exit instead. Every other cause is diagnostic only: raised or timed-out hooks, bodies and cleanups, and `SERVE_TASK_PENDING`/`TASKS_PENDING`, whose task names are already in `pending_tasks` |
| The shutdown budget allocation (shared hooks pool, margins, floors, per-wave division) | No peer splits shutdown time this way; it has caused #1809 and #2248; it shortchanges `on_shutdown` against the documented timeout (Assumed) | Operation-owned deadlines (D19) |

**Separate issues, outside the milestone:** the `_pending_start_task` machinery and cross-thread
`start()`/`cancel()` redispatch; the remaining duplicate guards (`cleanup()` re-waiting init, unused
`initializing`/`task` properties); `TaskBucket` subclassing `Resource`.

Process shutdown is to stop app instances concurrently, as D19 places it, not within a share of the
app handler's hook time, so an app whose hooks run to their timeout costs no other app its `on_shutdown` (chosen at the first sketch challenge, Finding 16). Behavior to pin: no app's
shutdown hooks are cut short by other apps' hooks at process exit. An inferred bug, that later apps are cut off at process exit
because they shut down sequentially inside `AppHandler`'s own shutdown-hook pool (computed the same way as the per-app pool in Assumed), is reproduced first; the
test that reproduces it pins the fix.

**Reversibility:** easy (deletions; the shutdown-budget change touches shutdown timing everywhere but restores nothing callers rely on)
**Ratified:** Chose removing the six items above in the milestone, including the shutdown budget, and filing three smaller cleanups separately, over keeping built machinery or deferring the budget, to leave the milestone's decisions true and the lifecycle code smaller, accepting a medium-risk shutdown-timing change and that a failed init skips the app's `on_shutdown` (HA's rule). Added at the sketch re-challenge from the machinery inventory. Re-ratified with D19, which replaces the budget with operation-owned deadlines and moves removal of the app layer's stop timeout into issue 1. Per-bucket sync-worker tracking, added at the narrow re-challenge (Finding 5), was dropped at D19's second re-challenge (Finding 9): the predicate no longer covers sync workers, and executor threads surviving the exit join trigger D19's hard exit instead.

### D19: Where do shutdown timeouts sit?

**Deciding factor:** today an app's `on_shutdown` at process exit sits inside eight nested bounds:
its hook timeout, the app coordinator's outer wait, the app layer's stop timeout, `AppHandler`'s own
shutdown-hook bound, `AppHandler`'s coordinator outer wait, the root wave's batch timeout, the root
body's deadline and the root coordinator's outer wait. Nested bounds on the same work only agree if
they are divided downward (the shutdown budget, which gives hooks 2.5s; Assumed) or summed upward,
and either drifts as the tree changes. The interior bounds exist because the hook runner bounds a hook
with a cancel-and-wait timeout, which cannot stop waiting on a hook that swallows cancellation, so
every level above adds a bound that can walk away. The peers put the deadline on whoever started the
operation or on the stage, and let inner bounds only shorten it: trio/anyio pass one deadline down
that nested scopes can only tighten; HA core gives each shutdown stage (stop, final write, close) its
own timeout and none per integration; systemd bounds each unit with `TimeoutStopSec`; OTP recommends
`infinity` as a supervisor child's shutdown time and bounds only workers.

| | O: Operation-owned deadlines, hooks clamped to them | L: Leaves only, one root ceiling | B: Stage timeouts plus an outer bound per resource | N: Leaves only, not abandonable |
|---|---|---|---|---|
| Who owns a deadline | The operation's entry point. Process exit has a stop stage (everything but the foundation services) and then a foundation stage with a fixed budget that runs even when the stop stage timed out; `total_shutdown_timeout_seconds` bounds the whole exit, so the stop stage gets the total minus the foundation budget. A runtime instance stop, reload or init-timeout teardown has one entry deadline of the stop stage's length. The deadline is attempt state on the resource coordinator, set by the operation's owner when it starts; a caller that joins an attempt already running can only tighten it | The root alone, at process exit | Every resource coordinator, `AppHandler`'s hook and the app layer, plus the root | The root alone |
| Leaves | Each user hook, the serve-task wait and the initializer observation (D10) run inline as today, under a cancel-and-wait bound of `min(shutdown_timeout_seconds, what is left of the operation)`; the task-cancel stage gets `task_cancellation_timeout_seconds` and `cleanup()` its fixed 0.5s cap, each under the same rule. The foundation stage's framework steps are not user hooks and are not bounded by the hook timeout: the session finalize is a database write bounded by SQLite's 5s busy timeout, the database drain has a fixed 5s cap, and the sync executor's join-or-interrupt a fixed 10s (HA's constant), so the foundation budget is their sum, 20s. The shutdown snapshot keeps its existing rule: it is not bounded, runs to completion in its own thread even if its stage ends, and only the supervisor's kill cuts it short | Each hook gets the hook timeout | As L, plus each outer bound | As L |
| Interior nodes (coordinators, dependency-ordered shutdown waves, child batches, `AppHandler`) | Wait without a bound of their own and pass the deadline down: a child batch passes it to each child, and `AppHandler` passes it explicitly to the app instances it stops, which have no parent. Only the deadline owners walk away: the root, for each exit stage, and `AppLifecycleService`, for a runtime instance operation's entry deadline. Orchestration is never a hook: `AppHandler` stops registry apps concurrently in its child stage, not in `on_shutdown`, so every hook is a leaf | Wait without a bound, but `AppHandler`'s app stop runs inside its bounded `on_shutdown`, so an app whose hooks sum past one hook timeout is cut off | Bounded | As L |
| Cancellation-swallowing hook | Cancelled at its bound; it holds its resource's shutdown until the stage or entry deadline walks away and force-terminates the resource. Shutdown hooks must let cancellation through, and the docs say so | Abandoned, with no owner afterwards | The resource's outer bound force-terminates it | Holds the stage until its deadline; later stages never run |
| Foundation work when a hook hangs at exit (session finalize with D14's fatal reason, database drain, snapshot) | Always attempted in the foundation stage, the snapshot last | Lost when the ceiling force-terminates the foundation services | Depends on the sums | Lost |
| Runtime stop or reload hang | Bounded by the entry deadline; expiry force-terminates the instance, fails it as timed out and flags it needs-restart | Unbounded as drafted, but the entry deadline is independent of the exit stages and could be added to L | Bounded by the app layer's timeout | Unbounded |
| Values that must agree | One single-field floor: `total_shutdown_timeout_seconds` exceeds the fixed foundation budget. No cross-field check: a hook longer than what is left of its stage gets what is left, and the stage-expiry ERROR names it; the docs say so. The supervisor's grace period must cover `total_shutdown_timeout_seconds` plus an allowance for the snapshot | Unstated | Every outer bound must exceed its stages and children | As L |
| Matches | HA core stages, trio/anyio scopes, systemd, OTP | — | — | AppDaemon, HA config-entry unload (both documented as hanging) |

Under O:

- **Deadline carrier.** The operation's deadline lives on the resource coordinator's attempt state
  beside its init and shutdown tasks. The operation's owner sets it when the operation starts: the
  root shutdown for each stage, `AppLifecycleService` for an entry deadline. A caller that joins an
  attempt already in flight can only tighten it (`min`), never extend it. At process exit, app
  instances stop through the same instance-stop path as runtime stops, so their deadline is the entry
  deadline's length or what is left of the stop stage, whichever ends first.
- **Hooks stay inline.** A hook runs in its coordinator's task, as today, bounded by cancel-and-wait.
  There are no per-hook tasks, no post-cancel grace and no owner set for abandoned hooks. A hook that
  swallows cancellation holds its resource's shutdown until the stage or entry deadline above it
  walks away. This is a documented limitation: shutdown hooks must re-raise `CancelledError` and clean
  up promptly once cancelled; otherwise they can stall shutdown to the stop stage's deadline, and at
  runtime they leave the instance needs-restart. A hook that blocks the event loop (a synchronous
  network call, `time.sleep`) is out of scope: no deadline and no hard exit can run while the loop is
  blocked, so the supervisor's kill at its grace period is the backstop, and the docs say shutdown
  hooks must not block the loop. Peers accept the same: AppDaemon's terminate, HA's
  unload and trio's `Cancelled` all rely on the hook letting cancellation through.
- **Stop stage.** At its deadline the stage stops waiting, without cancelling the work and waiting
  for the cancellation to land, and the coordinator's separate outer wait goes. On expiry, every stop-stage
  resource that has not finished is force-terminated, registry apps included, and one ERROR names
  each of them with the stage it was in (CRITICAL stays reserved for D14's fatal reason; a stop-stage
  expiry sets no exit code). The foundation stage then runs.
- **Foundation stage.** `Hassette`'s root shutdown names its foundation services:
  `DatabaseService`, `SyncExecutorService` and `SessionManager`, whose finalize carries D14's fatal
  reason. It stops every other child in the stop stage first. Within the stage, the session finalize
  writes, then the database drains and closes, then the executor joins, in that order, so the budget is their sum. The shutdown snapshot runs last, after the join and outside the budget (it opens its own
  connection to the database file, so the closed service connections don't affect it), so a slow copy never holds up the budgeted steps or reads as a failed stage, and a copy the supervisor kills costs only itself. If the foundation budget runs out, an
  ERROR says which of the drain, the session finalize and the executor join did not finish.
- **Entry deadline.** It lives in `AppLifecycleService`'s instance operations, which every path
  calls (app actions, file-watcher and config reconcile, autostart), and bounds the stop and teardown
  legs: its clock starts when that leg begins (after the app-key lock is held, and after a timed-out
  init, not counting the init), and a reload's create leg stays under the app init deadline (D18). On
  expiry it walks away from the coordinator's join and force-terminates the instance, which also
  removes the instance's bus listeners and scheduler jobs by owner (a registry operation that runs no
  user hook; force-termination otherwise skips the `Bus` and `Scheduler` teardown that removes them,
  and at runtime nothing else would), so it is FAILED
  with a "timed out" reason (the typed outcome carrying the reason is D15's) and flagged
  needs-restart, since force-termination leaves the evidence incomplete (`FORCED_TERMINAL`, D18's
  predicate), with one ERROR naming the pending tasks it knows of, or, when force-termination left no
  task names, the force-terminated resources and that the evidence is incomplete; the needs-restart
  record carries the same. Until issue 6 adds the flag, expiry is
  FAILED plus the ERROR only.
- **Apps.** `AppHandler`'s child stage stops registry apps concurrently through the same
  instance-stop path runtime stops use, so their lifecycle events and log binding stay, and merges
  their `TeardownReport`s into its own. Its force-terminal reaches registry apps too. App stop is not
  in `AppHandler.on_shutdown`.
- **Process exit.** On the `hassette run` path only, when a stage or entry deadline force-terminated
  something during the process's life, or when executor threads survived the foundation stage's join,
  hassette waits for an in-flight shutdown snapshot to finish, logs one ERROR naming what was left,
  flushes logs and hard-exits, after D14's CRITICAL fatal line, with the exit code `hassette run`
  already maps, so the event loop's cancel-and-await and the interpreter's thread join cannot hold the
  process until the supervisor kills it. An exit whose only problem is abandoned work exits 0, by
  decision. Embedded and test-harness loops never hard-exit.
- **Settings.** `shutdown_timeout_seconds` bounds each hook; it replaces the app and resource
  shutdown timeouts (D18's merge) and keeps the old app timeout's default. `total_shutdown_timeout_seconds` keeps its name and now bounds the
  whole exit, both stages; its default rises from 30s to 45s, leaving a 25s stop stage. Today's 30s covers the whole exit,
  including an executor join of up to 10s (the removed setting's default), so the stop work's share
  grows from about 20s to 25s; a longer total would only lengthen the wait before a hung process
  gives up.
  `task_cancellation_timeout_seconds` stays, `TaskBucket`-wide. `sync_executor_shutdown_timeout_seconds`
  and its validator go: the executor join is a fixed constant inside the foundation budget, as in HA.
  The fixed values in the table above are decided here and live as code constants; the docs point to
  them. The supervisor grace period follows the total plus a 15s snapshot allowance: the Docker
  compose `stop_grace_period` rises from 45s to 60s, along with the Docker integration test's stop-grace constant and the operating and
  add-on docs' sentences tying shutdown to the total. The add-on's own stop timeout is a follow-up in
  the add-on repository.
- **Removed keys.** Four settings go across the milestone: `app_shutdown_timeout_seconds`,
  `resource_shutdown_timeout_seconds` and `sync_executor_shutdown_timeout_seconds` here, and
  `failed_instance_cleanup_timeout_seconds` in issue 6 (D18). A config that still sets one is rejected
  at load as a config error (Assumed), so hassette does not start until the config is edited; each
  changelog migration note leads with that.

**Recommendation:** O, because it puts each deadline where a peer would, keeps an app's hooks out of
any other node's bound, always attempts the snapshot, bounds runtime stops, and replaces a tree of
nested sums with one deadline per operation, a fixed foundation budget and one single-field floor.
**Pick L (with the entry deadline added) instead if** losing the session finalize, the database drain
and the snapshot on an exit where a hook hung is acceptable, and two exit stages aren't worth
carrying.
**Pick N instead if** force-terminating at a stage deadline is judged worse than an exit that waits
until the supervisor kills it.
**Pick B instead if** each resource genuinely needs its own shutdown bound independent of its
caller's; none was found, and B's nested sums are what caused #1809 and #2248.
**Reversibility:** easy (the stage split, entry deadline and deadline carrier are local)
**Ratified:** Chose operation-owned deadlines (a stop stage and a foundation stage at process exit, an entry deadline for runtime instance operations), with each hook's bound clamped to them, over one root ceiling (L), per-resource outer bounds (B) or unabandonable leaves (N), to put each deadline on its stage or caller as HA core and trio do and keep the snapshot and runtime stops bounded, accepting two exit stages and a hard exit when work was force-terminated. At the comb after the second re-challenge, kept the Settings bullet's total and grace over raising both by 5s once the foundation budget was found to include the session finalize, accepting a shorter stop stage. Revised at the re-challenge after building #3104 began (Findings 1 and 2, converging Findings 3-9 and 12), replacing leaves-only-under-one-ceiling. At the second re-challenge, chose a per-hook `shutdown_timeout_seconds` with `total_shutdown_timeout_seconds` bounding the whole exit and no cross-field check (Finding 2), the deadline as coordinator attempt state that joiners only tighten (Finding 3), an enforced entry deadline that walks away and force-terminates (Finding 4), registry app stop in `AppHandler`'s child stage with merged reports (Finding 8), named foundation services (Finding 11), a hard exit triggered by force-termination or surviving executor threads, with an exit whose only problem is abandoned work mapped to 0 (Finding 10), and removed keys rejected at load (Finding 14), and dropped O's earlier per-hook tasks with a post-cancel grace (Finding 12), accepting that a hook that swallows cancellation holds shutdown to its stage or entry deadline and leaves its instance needs-restart, that a reload during exit can create an instance whose `on_shutdown` never runs (Finding 16), and that slow app hooks can use up the stop stage so bus and scheduler teardown get force-terminated (Finding 17). At the final challenge, kept D19 whole over splitting the entry deadline from the exit topology or pairing L's single ceiling with the entry deadline, because the foundation stage protects the session finalize carrying D14's fatal reason and the database drain, not only the optional snapshot (Finding 2); and chose removing a force-terminated instance's listeners and jobs by owner at entry-deadline expiry over leaving them live until restart (Finding 4), accepting that a hook blocking the event loop defeats every deadline and the hard exit, leaving the supervisor's kill as the backstop (Finding 3). Chose running the snapshot last, after the executor join, over counting it against the foundation budget, so a slow disk can't fail the stage (Finding 5). Accepted that after a stop that runs its full total on slow storage, the supervisor can kill the snapshot mid-copy, leaving the previous snapshot in place and logging nothing (Finding 6). Accepted that after a runtime entry-deadline expiry, the process's next shutdown hard-exits even if the force-terminated work has since finished, and its stdout-only ERROR may name finished work (Finding 7).

## Assumed

- The only `after_initialize()` overrides are on `StateManager`, `AppHandler` and `App`. Until issue 4
  none of them is a Service; issue 4 makes `AppHandler` one (D17), and its override then only marks it
  ready, waiting on nothing. Evidence: a search for `after_initialize` definitions in the `hassette`
  package; `AppHandler.after_initialize()`.
- The only `Service` subclasses with children are `WebApiService` (`Scheduler`) and `SchedulerService`
  (`Bus`, `_ScheduledJobQueue`), joined in issue 4 by `AppHandler` (`Bus`, `AppLifecycleService`, whose
  initializer only marks it ready). `RuntimeQueryService` owns a `Bus` but is a plain `Resource`;
  `SessionManager` and `ServiceWatcher` do too until issue 4 removes both buses (D8). Evidence: their
  `add_child` calls and base classes.
- With defaults, the shutdown budget gives an app's three shutdown hooks a shared 2.5s, while the
  operating docs say `app_shutdown_timeout_seconds` (10s) caps a single app's `on_shutdown`. Evidence:
  `compute_shutdown_budget` evaluated with the default settings; the operating docs page's shutdown
  timeout section.
- Today's shutdown nests the bounds D19's deciding factor lists around an app's `on_shutdown`, the hook
  runner bounds a hook with a cancel-and-wait timeout that cannot walk away from a hook that swallows
  cancellation, today's foundation wave is the database service and the sync executor, the database drain
  has a fixed cap, the shutdown snapshot is deliberately unbounded, and the executor's join-or-interrupt
  is a port of HA's. Evidence:
  the shutdown coordinator, the hook runner, `AppHandler`'s and the app layer's stop paths, the root
  shutdown body and waves, the database write queue's drain, and the interruptible executor module.
- Unknown config keys raise a `ConfigError` at load, so a config that still sets a removed setting
  stops hassette from starting (`hassette run` exits 78) rather than being silently ignored.
  Evidence: the config package's unknown-key check.
- hassette runs under an external process supervisor that restarts it after a fatal exit: the HA
  add-on with Watchdog enabled (limits in D17), a Docker restart policy, or a systemd unit. D1, D3 and D17 depend on it. Evidence:
  the add-on's health check; the Docker getting-started compose snippet's restart policy.
- Only top-level services (children of `Hassette`) declare `depends_on`, no boot-wave initialization
  body waits on Home Assistant, and no child of a Service in the inventory above waits on its parent's
  serve (each child's initializer only marks ready or wires itself). D1's
  wave join and D7's ordering depend on it. Evidence: the `depends_on` declarations across the core
  package; the HA connection living in `WebsocketService.serve()`; the `Scheduler`,
  `_ScheduledJobQueue` and `AppLifecycleService` initializers.
- Every required service's `serve()` returns only after shutdown is requested: most loop until their
  own shutdown event is set (a disabled web API included), `WebsocketService` exits only by raising,
  and `BusService` also ends when its event stream closes, which happens only at shutdown or in D9's
  bus-death close. So D8's "unrequested return is a failure" rule fires on no normal path. Evidence:
  the `serve()` loops of the required services (D17).
- Readiness stays separate from status. Services that mark ready in `on_initialize()` (`WebApiService`,
  `WebsocketService`, disabled watchers) keep doing so. D1 changes when RUNNING is set, not those
  rules. Evidence: the resource-lifecycle rule file's readiness section; `WebApiService`'s and
  `WebsocketService`'s `on_initialize()` ready marks.
- The lifecycle coordinator owns exactly one init and one shutdown attempt per resource, holds the
  init, shutdown and shutdown-body tasks, and produces the `TeardownReport`. Evidence: the
  coordinator's initialize and shutdown functions; rule file section "One attempt per resource".
- The coordinator already cancels shutdown hooks and the shutdown body at their deadlines, and records
  what is still pending in the `TeardownReport`. Init is shielded today, so the app layer's timeout
  abandons it. Evidence: the coordinator's shutdown wait and hook runner; rule file section "Teardown
  reports".
- An unsafe `TeardownReport` already blocks re-initializing the same object (`RestartRefusedError`).
  Apps avoid it because reload builds a new object. Evidence: rule file section "Teardown reports".
- `WebsocketService` reconnects to Home Assistant in place; its `serve()` does not exit on HA-side
  failures, so losing HA never reaches the supervisor. Evidence: `WebsocketService.serve()` docstring.
- The CLI and the web UI reach a running instance only through `WebApiService`, which also serves the
  liveness probe the add-on's health check calls. Evidence: the CLI client; the add-on Dockerfile.
- `SyncExecutor` tracks only a global outstanding-submission count (for saturation warnings) and a
  per-submission `SyncWorkerHandle` with no owner, so no resource can tell whether its own sync
  workers are still running. Evidence: `SyncExecutor.submit()` and `TaskBucket.run_in_thread()`.
- `Hassette.send_event()` already drops events when the streams are closed. Evidence:
  `Hassette.send_event()` and `event_streams_closed`.
- `ResourceStatus` and `AppStatus` are published in `hassette-wire`. `ServiceStatusPayload` is internal
  to hassette's events. Evidence: `hassette_wire.enums`.
- `_run_app_action()` already maps bootstrap-not-released, blocked and in-progress to 409, and recorded
  failures to 500. Only the success shape (202 `accepted`) and the read-back source change. Evidence:
  the app action routes.

## Breakdown

**Done when:**
- a service failure after startup has exactly one outcome: a required service exits the process with a
  nonzero exit code and a CRITICAL line naming the reason, an optional one is FAILED (CRASHED for `FatalError`) with one dead-in-place ERROR; nothing restarts a service
  in-process, and `ResourceStatus` has no `EXHAUSTED_*` values;
- a failure report arriving after shutdown was requested doesn't escalate, so a clean stop exits 0, and
  a required service whose `serve()` returns unrequested counts as failed;
- a service is RUNNING only after its initialization completes, and a boot-time start failure fails
  startup;
- bus death, at boot or later, shuts the process down without hanging, and every resource still
  reaches STOPPED;
- a timed-out app hook never leaves an app's reported state STOPPED while its work runs: it is FAILED, and
  flagged needs-restart in the API, CLI and UI when D18's predicate holds, until hassette restarts;
- no path creates an instance over a needs-restart instance, and every reload decides, stops and
  creates under the app-key lock;
- app action endpoints return each request's own per-instance outcome;
- each app's shutdown hooks are bounded by the hook timeout and never cut short by other apps' hooks,
  and the database shutdown snapshot is always attempted at process exit;
- a runtime stop or reload that hangs ends within its deadline as a failed, timed-out outcome;
- a process that force-terminated work at any point in its life, or whose shutdown left executor
  threads running, exits (unless a hook blocks the event loop, D19) with its
  decided exit code instead of waiting for the supervisor to kill it;
- `strict_lifecycle` and the status transition table no longer exist;
- a config that sets a removed shutdown or cleanup setting stops hassette at load with a config error;
- the docs describe all of the above; each issue ships its own docs (Summary, "Docs and UI").

Applies to all: D4 (an app failure never takes down the process or its siblings), the Posture's
"no silent states" rule, and its compatibility rule: an issue that changes a `hassette-wire` enum or a
published payload (4, 6, 8) adds the compat ignore entries its checks actually fail on, plus changelog
and migration notes. A removed response enum value or property fails the OpenAPI diff
(`tools/wire_compat_ignore.txt`); `client_compat` (`tools/client_compat_ignore.txt`) fails only when a
released client can't parse the new responses, and a stale entry there fails the check, so don't add
one pre-emptively.

1. **Put shutdown deadlines on operations and stages**: replace the shutdown budget allocation with
   D19's operation-owned deadlines: the two exit stages, the enforced entry deadline on runtime
   instance stop and reload (whose expiry also removes the instance's listeners and jobs by owner),
   hooks kept inline and clamped to them, registry app stop in
   `AppHandler`'s child stage, and the hard exit. Remove every interior bound D19 lists. Make D19's
   setting changes, carried through the dev and prod configs, the generated config schema and the
   frontend's config fixture. Report any timed-out stop as FAILED with an `AppRegistry` failure entry
   (D5), and record a timed-out hook as its own teardown cause. Docs: the operating docs (per-hook and
   total settings, the grace period, the hard exit), the app lifecycle docs' rule that shutdown hooks
   let cancellation through and never block the loop, and the add-on docs' grace sentence; raise the Docker compose
   `stop_grace_period` and the Docker stop-grace test to match; a changelog migration note for each
   removed setting, leading with "hassette won't start until you remove it". Reproduce the suspected
   cut-off of later apps first. Implements: D5 (timed-out stop outcome and cause), D10 (shutdown row),
   D18 (shutdown budget, timeout merge, app-layer stop timeout, concurrent app shutdown), D19.
   After: none. Issue: #3104
2. **Remove `strict_lifecycle` and the status transition table**: delete transition validation, and
   decide the setting's other readers: `WebsocketService`'s connection-state check, strict registry
   validation (enabled only by this setting today, and forced on by the test harness), and the
   transition error's place in the WS reconnect's propagated exceptions. Implements:
   D16 (#2697), D18. After: none. Issue: #3105
3. **Mark a service RUNNING only after initialization completes**: start `serve()` last, add the
   no-waiting-on-parent-serve rule, make boot start failures fatal by joining each startup wave's
   initialization attempts (and the database service's phase before them) before its readiness wait. Implements: D1, D7. After: none.
   Issue: #3106
4. **Report service failures directly and stop restarting services in-process**: the direct report and
   its contract (reported before the telemetry sends, routed by `Hassette`, overridden by the harness),
   required/optional classification replacing restart specs (an undeclared Service fails at class
   definition; a required Service under a non-`Hassette` parent is rejected at `add_child`), dead-in-place
   optional services, startup waves that settle on an optional member whose serve ended, by failing
   or returning early (D7), report-routing no-ops on the harness and the test mocks (D8), one fatal
   escalation path,
   `AppHandler` as a required Service running app bootstrap in `serve()`, removal of restart budgets,
   backoff, cooldown, the generic restart front door,
   `fatal_error_names`, `EXHAUSTED_*` and `retry_at` (wire and frontend mapping), `ServiceWatcher` and
   its `logging.service_watcher` key (committed config schema and frontend framework-keys included),
   `ServiceEscalationMixin`, and `SessionManager`'s CRASHED listener with its `Bus` and stored session
   error; OpenAPI, WS schema and frontend types regenerated; a failed optional service is left
   un-shut-down. Changelog migration notes for `RestartSpec` / `restart_spec` replaced by `required`
   (an app-owned Service must declare itself optional) and the removed logging key; changelog entries
   for the behavior changes: any non-app CRASHED no longer exits by itself (a `FatalError` from an
   optional service ends it dead in place), and session rows no longer get
   `error_type`/`error_traceback`. Stale references to the deleted classes go too: the docs
   reference-page generator and xref-coverage checker, `core/REVIEW.md`'s watcher questions, the
   database telemetry page's example app key, the status-predicates module, `Hassette`'s watcher slot,
   the known-flakes list, the client-compat live-state fixture's `_retry_at` seeding, the adversarial
   seed scenario's watcher rows, `resources/REVIEW.md`'s `EXHAUSTED_*` questions, the `FatalError` and
   `RestartRefusedError` docstrings, harness and fixture comments citing watcher behavior,
   `SessionManager`'s session lock (which only coordinated with the deleted listener), and the
   `Service` docstring (whose step order also predates D7). Docs: the Lifecycle & Supervision page
   (`internals/lifecycle.md`: its restart-spec, watcher and `EXHAUSTED_*` material, replaced by
   required vs optional, fatal exit, dead-in-place, that hassette must run under a restart policy, and
   where that supervisor keeps the previous run's fatal reason), plus the
   fatal-exit sentences on the health endpoints and database telemetry pages, the internals overview
   (its `ServiceWatcher` API cross-reference, which breaks the docs build once the class is gone, and its
   startup diagrams), the service details page's restart-spec and `EXHAUSTED_*` material and
   restart-spec snippet, the web UI diagnostics page's cooldown text and the log-levels
   page's watcher key, replaced by the required/optional declaration a custom `Service` author must
   make; the resource-lifecycle, core-startup and unit-test rule files and the config log-level
   convention design note. Implements: D2, D8, D13, D14, D17, D18
   (restart machinery, terminal-status preservation), and D7's boot outcome for serve failures.
   After: 2, 3. Issue: #3107
5. **Shut down cleanly when the bus dies**: route bus death through issue 4's fatal path, have the bus
   close the event streams whenever its drain loop ends, and at failed startup unless it is draining
   (D9's amendment), so no producer blocks, have direct
   `EventStreamService.send_event()` callers handle the closed-stream error, and let status transitions
   run with closed streams.
   Implements: D3, D9. After: 4. Issue: #3108
6. **Flag app instances that need a restart after a hook timeout**: route failed and timed-out init
   through instance shutdown (user hooks skipped), remove the hand-rolled cleanup and its timeout
   setting, with a changelog migration note (the init deadline stays and triggers instance shutdown; issue 1 removes the app-layer stop
   timeout), put init-timeout teardown under D19's entry deadline, adopt the "work may still be
   running" safety predicate in the coordinator's re-init guard, add the needs-restart record (counted
   toward `AppStatus` and rendered as an orphaned row after a config edit, D11), flag it
   when the predicate holds and on every entry-deadline expiry, `AppInstanceInfo` fields, the minimal
   UI badge, the flag and reason in the CLI's app listing, and the app lifecycle docs on hook timeouts,
   the needs-restart flag and "restart hassette to recover".
   Implements: D5, D10, D11, D12 (flag), D18 (`cleanup_failed_instance()` and its setting, restart safety), D19 (init-timeout entry deadline, needs-restart on expiry). After: 1. Issue: #3109
7. **Decide reloads under the app-key lock and refuse unsafe replacements**: decide, stop, gate and
   create under one lock; refuse every instance-creating path over a
   needs-restart instance; log refusals that have no response channel; document reload refusal in the
   app lifecycle docs. Implements: D6, D12 (gate). After: 6. Issue: #3110
8. **Return typed outcomes from app actions**: per-instance outcomes from `AppLifecycleService`, the
   worst-outcome-wins 200/409/500 mapping, `ActionResponse` reshape, the `outcomes` extension member on
   `ProblemDetail` and the needs-restart `ProblemCode`, the minimal frontend change, and
   the CLI's app action output reporting refusals and failures instead of success. Implements: D15.
   After: 6, 7. Issue: #3111

Housekeeping outside the issues (D16, D18), done: #1222 closed as obsolete; #1721 trimmed to the
coordinator and shutdown-body splits; separate issues outside the milestone: #3112 (`_pending_start_task`
machinery), #3113 (remaining duplicate guards), #3114 (`TaskBucket` subclassing `Resource`). Milestone:
*Resource Lifecycle*; the overlapping originals closed as superseded. Follow-up filed into the milestone so it isn't lost (removable later): #3395, replacing `TeardownReport`'s evidence tree with a small outcome (result, what is still running, reason).

## Addendum

**2026-10-27 — implementation decisions for item 6 (#3109).** The issue was combed against the code before building. These were decided with the user and are backed by `design/research/2026-10-27-needs-restart-flag/prior-art.md`:

- **D18: the skip of shutdown hooks after a failed init stays apps-only, as a per-attempt flag.** `AppLifecycleService` sets the flag on the failed-init shutdown attempt. It is not propagated to children, so the never-initialized `Bus`/`Scheduler` still run `on_shutdown` and remove the app's listeners and jobs. A general Resource rule ("hooks only after init completed", HA/OTP's shape) was rejected for two reasons. Children initialize after the user hooks, so the rule would need a careful definition to keep their cleanup. It would also skip framework services' `on_shutdown` after a partial init, which HA only gets away with by having integrations register `async_on_unload` callbacks. HA's rule covers integrations, which are user code, and `App` is the equivalent boundary here.
- **D5/D11: status is sticky FAILED.** A flagged instance reports FAILED until restart, including after a stop that discards its failure entry. The record stores the instance and class name, so orphaned rows render (HA `FAILED_UNLOAD`, systemd `failed`).
- **D18: `is_restart_safe` is redefined in place as "work may still be running".** There is no second predicate. `CHILD_SHUTDOWN_FAILED` and `CHILD_SHUTDOWN_TIMED_OUT` count as incomplete evidence. `CHILD_RESTART_UNSAFE` means a child's report satisfies the predicate.
- **D11: the wire field is `needs_restart: NeedsRestart | None` (`reason`, `pending_tasks`, `flagged_at`).** It is on `AppInstance` and carried on `app_status_changed` (HA sends the full entry on each event).
- **D11: CLI.** `hassette app` gets a needs-restart count column. `hassette status` gets a section listing flagged instances.
- **D18: walk-away cleanup bound.** Removing `failed_instance_cleanup_timeout_seconds` leaves `walk_away_from_instance`'s listener and job cleanup bounded by a fixed module constant instead.
