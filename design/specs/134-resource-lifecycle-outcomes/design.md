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
milestone also deletes it (D17, D18).

Areas and where each new piece lives:

- **Service start handoff** — `Service`'s initialization body and serve wrapper. A service is RUNNING only after `initialize()` (hooks and
  children) has completed.
- **Service supervision** — `ServiceWatcher`; `ServiceEscalationMixin` goes. Nothing restarts services in-process
  (D17): the watcher receives each failure report (D8) and routes it by whether the service is
  required: fatal exit, or dead in place (D2). The restart machinery goes (D8, D17, D18).
- **Fatal escalation** — one fatal-exit function on `Hassette` (D14), called by the watcher and by the
  no-supervisor path for required services (D8). The fatal reason lives in memory on `Hassette`
  (it sets the exit code and the CRITICAL exit line); teardown's existing session finalize writes it to the session
  record best-effort.
- **Required/optional declaration** — a class-level declaration on each `Service`, replacing
  `restart_spec` (D17); `ServiceWatcher` reads it when routing a report.
- **Dead bus** — `BusService` closes the event streams whenever it fails, in its init body or its
  serve (D9). A serve failure then arrives as a D8 report; an init failure is a boot failure (D1). The
  bus is required (D17), so either way the process exits through D14 or failed startup. After bus
  death, no producer blocks (D9).
- **Supervisor hook** — on `Hassette`, registered by `ServiceWatcher` at construction. Lifecycle code
  reports post-handoff serve failures to it (D8).
- **Sync worker evidence** — each resource's `TaskBucket` keeps the sync worker handles it submitted;
  the `TeardownReport` records those still active (D18).
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
  through the client-compat ignore list with changelog and migration notes, because hassette-wire
  and hassette-client are released packages.
- **Scope:** minimal per concern. The deliverable is a milestone of high-level issues, not one build.
- **Rollout:** ship outright. The endpoint contract change and its minimal frontend change land in the
  same release as the app-state changes.
- **Hardening:** project defaults, plus one raised requirement: every new needs-restart or dead-in-place
  state is visible as a status and one ERROR log naming the cause. No silent states.
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

At boot, the first start has no supervising caller (startup waves start children fire-and-forget and
then wait for readiness). A boot-time start failure is therefore fatal whether or not the service is required:
the wave isn't ready, startup fails, and the external supervisor restarts the process. This is a
behavior change. Today a FAILED event from a boot failure in a post-watcher wave reaches
`restart_service()` and gets retried. It is accepted, because a wave that isn't ready is already fatal
today, so a retry only ever helped if it won inside the wave timeout.
**Pick the status quo instead if** a service genuinely needs to look RUNNING while its children
start. None was found.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose RUNNING-after-initialize over serve-time RUNNING, to make a failed attempt fail exactly once at the attempt, accepting a readiness-timing audit of every service. Boot fail-fast chosen at the sketch challenge (Finding 6) over making the first start a supervised attempt, accepting the loss of in-process retry for transient boot failures.

### D2: What happens to a service that fails after startup?

**Deciding factor:** a broken required service is not worth running without, but an optional one is.

**Recommendation:** the outcome follows whether the service is required (D17). A required service's
failure escalates to process exit through D14, and the external supervisor restarts the process. An
optional service ends dead in place: nothing shuts it down or restarts it, so its status stays
FAILED (CRASHED if it raised `FatalError`) until process shutdown begins, and it logs one ERROR naming its
bucket's pending tasks and saying a hassette restart brings it back (Posture: no silent states). No
in-process reconstruction.
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
and reloadable. D12 decides what the flag blocks.
**Pick observed auto-clear instead if** a cancellation-swallowing hook that eventually finishes must
recover without a restart. No peer has found that worth the machinery.
**Reversibility:** easy
**Ratified:** Chose HA's needs-restart flag, set from the existing `TeardownReport`'s pending-work evidence, over a stuck state that clears when abandoned work is observed ending, to match the peer norm and drop quiescence observation, accepting that an app whose hook swallows cancellation needs a hassette restart even if its work would have finished. Re-evaluated at the sketch re-challenge (Finding 2), replacing stuck-until-the-work-ends. At the narrow re-challenge (Finding 1), chose carrying FAILED in the `AppRegistry` failure entry over keeping it on the resource's status through shutdown.

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
| Services affected | Any service whose children or `after_initialize()` need serve already running. Scan: no `Service` overrides `after_initialize()`; the only Services with children are `WebApiService` (`Scheduler`) and `SchedulerService` (`_ScheduledJobQueue`), neither of which waits on the parent's serve | None by timing | None by timing |
| Code | Reorder plus doc update; the docstring's deadlock warning becomes a rule: a Service's children and `after_initialize()` must not wait on the parent's `serve()` or readiness. It goes into the resource-lifecycle rule file, and a Service whose child or `after_initialize()` waits on the parent's serve fails visibly instead of deadlocking | Two transition sites to keep in sync | New cross-task failure handoff |
| Matches prior art | trio/OTP: init completes, then the loop runs | systemd `notify`: running ≠ started | trio's pre-`started()` exception routing |

**Recommendation:** A, because it removes the mid-attempt window by ordering instead of guarding it,
and the scan found no service that needs serve running before its children. Behavior to pin: a serve
failure never surfaces from the attempt; D1's boot fail-fast covers failures of the body itself. Once
D8's report exists, a serve failure at boot follows D2 like any other: a required service exits
through D14 and an optional one ends dead in place.
**Pick B instead if** the audit finds a service whose child initialization needs its serve loop
draining work. **Pick C instead if** that same need shows up and B's double-path proves unworkable.
**Reversibility:** easy (local to `Service`)
**Ratified:** Chose starting `serve()` last over moving the RUNNING transition or routing early serve failures, to remove the mid-attempt window instead of guarding it, accepting a readiness-timing audit of every service.

### D8: How does `ServiceWatcher` learn that a service failed?

**Deciding factor:** detection outside the supervised channel (OTP links, systemd SIGCHLD/watchdog). A
bus-delivered failure is what makes a dead bus undetectable and what gives one failure two signals.

| | A: Keep bus FAILED events, add a bus-death hook | B: Direct report to the watcher for every service; bus events become telemetry only |
|---|---|---|
| Signals per failure | Two (attempt result and bus event), so failure ownership still has to be inferred | One: a failed attempt raises; a post-handoff serve failure is reported once, directly |
| Dead bus | Needs a special out-of-band hook (done-callback on the bus serve task, registered by `Hassette`) | Reported like any other service failure, then routed fatal by D3 |
| What it deletes | Nothing | The watcher's internal bus listeners, `reconcile_after_bus_recovery()`, `on_bus_service_running()`, the stale-status check, and the `_restarting` set with its step-order guards |
| Coupling | Unchanged | Lifecycle code reports to a supervisor hook on `Hassette` (the watcher registers itself); resources gain one call-out |
| User-visible | Unchanged | `on_hassette_service_failed` etc. keep firing as telemetry; only the watcher stops consuming them |
| #3036 size | Full state machine still needed to arbitrate two channels | Smaller: one channel, and with D17 the watcher only routes a report by whether the service is required |

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

**Report contract.**
- **Report site.** A dedicated report function, called only from `_serve_wrapper()` after the
  handoff. `handle_failed()` and `handle_crash()` stay status and telemetry. Pre-handoff init failures
  and swallowed shutdown-hook failures are never reports.
- **Recipient.** The watcher no longer depends on the bus, so its supervisor hook is registered on
  `Hassette` at construction, before any startup wave runs. A report with no registered supervisor
  logs ERROR and escalates fatal for a required service. The test harness, which has no watcher, opts
  out explicitly.
- **After shutdown starts.** A report arriving after shutdown has been requested, or after a fatal
  reason is already latched, is logged at ERROR and not escalated, so a clean stop still exits 0.
- **Unrequested return.** For a required service, `serve()` returning while shutdown hasn't been
  requested is a failure report, so a silently stopped bus or scheduler can't happen (Posture: no
  silent states).

**Reversibility:** hard (changes how supervision is wired; partial rollback re-introduces the guards)
**Ratified:** Chose direct reporting with bus events as telemetry over keeping bus-delivered FAILED events plus a bus-death hook, to give each failure one signal and make bus death an ordinary report, accepting one supervisor call-out from lifecycle code to `Hassette`. The acting-consumer inventory and report contract (dedicated report site, registration at construction, loud undelivered reports) were added at the sketch challenge (Findings 1, 2, 4, 5, 7, 12). At re-challenge 2 (Finding 10), added that post-shutdown reports are logged, not escalated, replacing the deleted watcher admission check.

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
also releases a sender already blocked on a full channel. `BusService`, which owns the channel, closes
the streams in its own failure paths: before it reports a serve failure (D8), so D14's CRASHED emit is
dropped instead of blocking, and when its init body fails at boot, so failed-startup teardown can't
fill a channel nobody drains. Other fatal exits leave the streams open and keep their shutdown telemetry. A dead bus does not release blocked senders
by itself: `BusService` holds a clone of the receive stream, and `EventStreamService` keeps the
original open. Behavior to pin:
- after bus death, no producer blocks and events are dropped. `Hassette.send_event()` already drops on
  closed streams; `EventStreamService.send_event()` raises on a closed stream rather than blocking, so
  every direct caller handles that error the way `Hassette.send_event()` does;
- status transitions still happen. `Resource._shutdown_body()` no longer skips `handle_stop()` when
  the streams are closed, so every resource still reaches STOPPED during the fatal teardown, and only
  the event send is dropped.
**Pick B instead if** a wedged-but-alive bus (not dead, just not draining) also needs to be survivable.
That is out of scope under the posture.
**Reversibility:** easy
**Ratified:** Chose closing the event streams on bus death over per-send timeouts or a bus-dead flag, to release every blocked producer through the existing closed-stream drop, accepting that a wedged-but-alive bus stays out of scope. At the sketch challenge (Finding 10), chose letting `handle_stop()` run with closed streams over accepting skipped STOPPED transitions. At the re-challenge comb, chose `BusService` closing its own streams before reporting over D14 closing them for every fatal exit, keeping shutdown telemetry for other fatal exits at the cost of one bus-owned cleanup step.

### D10: Is a timed-out app initializer cancelled?

**Deciding factor:** a timed-out init is being discarded, so its work has no future. Today the
coordinator shields init, so the outer timeout abandons it while it keeps running. Shutdown is
already bounded and cancelled by the coordinator, with the evidence recorded in the `TeardownReport`;
how its timeouts are divided is D18's.

| | A: Cancel init on timeout; shutdown unchanged | B: Leave init shielded (today) |
|---|---|---|
| Init timeout | Cancel the init attempt by shutting the instance down (D18): framework teardown removes its listeners and jobs and returns the `TeardownReport`; user shutdown hooks are skipped; D5 applies to whatever is still pending | Init keeps running after the instance is marked failed; late registrations (#1797) happen |
| Shutdown timeout | Hooks and body are cancelled at their deadlines, as today; the timeouts themselves follow D18 | Same |
| Late registrations (#1797) | Usually prevented: cancellation lands at the next await | Happen |
| Matches | `anyio`: cancel, then bound and observe; #1797's fix direction | — |

**Recommendation:** A, because it shortens a discarded init. Shutdown keeps being cancelled at its
deadlines; D18 simplifies how those deadlines are set.
**Pick B instead if** apps commonly do work in `on_initialize` that must not be interrupted mid-way
(for example, creating HA helpers).
**Reversibility:** easy
**Ratified:** Chose cancelling a timed-out init over leaving it shielded, to cut short discarded work, accepting that a cancellation-ignoring init still ends flagged needs-restart (D5). At the sketch re-challenge (Finding 6), "never cancel shutdown" was corrected: shutdown hooks and body are already cancelled at their deadlines, and they stay cancelled; D18 changes only how the deadlines are set.

### D11: Where does an app instance's needs-restart flag live?

**Deciding factor:** it must survive the instance being unregistered (a stop unregisters it), must be
read by the reload gate (D12), the routes and the UI, must not stretch a type that services also use,
and must not make every registry reader exclude it.

| | A: New `ResourceStatus` value (wire) | B: Keyed record in `AppRegistry`, outside the instance map | C: Tombstone entry in the instance map |
|---|---|---|---|
| Shape | e.g. a new `NEEDS_RESTART` value | `(app_key, index) → reason and pending task names`, beside the live instances | `InstanceEntry` gains a phase |
| Survives stop/unregister | Only if the registry keeps the entry anyway | Yes | Yes |
| Live registry readers | Every `ResourceStatus` consumer handles an app-only value | Untouched | Each one must exclude tombstones |
| Wire change | `ResourceStatus` enum plus a `client_compat` entry | `AppInstanceInfo` gains a needs-restart flag and reason; the snapshot includes flagged unregistered instances | Same as B |
| Matches HA | — | Per-entry state with `require_restart` | — |

**Recommendation:** B, because it holds app-only state where the gate and the UI can read it without
changing what "registered" means. `ResourceStatus` stays unchanged and honest. For `AppStatus`, a
flagged instance counts as not running, the same way FAILED does (`DEGRADED` beside running siblings,
`FAILED` if none run). Nothing clears the record except a process restart. A config change doesn't prune it either, because the
abandoned work is still running: the record keeps counting toward `AppStatus`, and the snapshot
renders a flagged row whose app or index has left config, using the instance name stored in the
record.

The flag is deliberately separate from service statuses. Services and apps live on
separate UI surfaces (diagnostics vs the apps page), and each is mapped once, in its own place.

The registry record is the instance's persistent state for later readers. D15's outcome is what one
request did. Both are set in the same step under the app-key lock.

**Reversibility:** hard (wire shape the UI and client consume)
**Ratified:** Chose a keyed needs-restart record in `AppRegistry`, outside the instance map, over a new `ResourceStatus` value or a tombstone entry, to keep app-only state off the type services share without making registry readers exclude it, accepting an `AppInstanceInfo` wire change. Separate service/app vocabularies were chosen at the first sketch challenge (Finding 20); the tombstone model chosen there was replaced at the re-challenge (Findings 2, 7), and concurrent app shutdown (first-challenge Finding 16) moved to D18. At re-challenge 2 (Finding 9), chose keeping the record counting until restart, with the snapshot rendering orphaned rows, over pruning it with config, accepting a DEGRADED app after a config edit until hassette restarts.

### D12: What old-instance evidence allows a replacement?

**Deciding factor:** the danger is two live incarnations (k8s's at-most-one identity), not an exception
in user code. HA refuses reload after any failed unload, but hassette reloads on every file save, so a
buggy `on_shutdown` that merely raises would force a restart on every edit.

Evidence is the instance's `TeardownReport`, which the coordinator already produces, read through
D18's "work may still be running" predicate. That predicate separates causes that only record
something raised or timed out and has since ended from evidence that work may still be alive.
Threads, subprocesses and external side effects the user starts outside hassette's context are
invisible under every option. Framework-started sync worker threads are covered (D18); parallel-mode
handlers and scheduler jobs are not (#1715).

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
**Pick P instead if** overlapping incarnations from cancellation-swallowing code are acceptable in
exchange for no new state. **Pick A′ instead if** such instances must recover without a restart.
**Reversibility:** easy
**Ratified:** Chose refusing replacement only while an instance is flagged needs-restart (work still pending after cancellation) over observed auto-clear, HA's any-failed-teardown rule, or never refusing, to prevent overlapping incarnations with existing evidence and keep hot reload usable, accepting a manual hassette restart for the rare cancellation-swallowing app. Re-evaluated at the sketch re-challenge (Finding 2), replacing no-terminal-state and dropping the quiescence primitive from PR #1782's branch. At re-challenge 2, the gate was widened from reload to every instance-creating path (Finding 8), and its evidence gained active sync workers with stated coverage (Finding 7).

### D13: Where does per-service supervision state live?

**Deciding factor:** each owner holds its own state. `EXHAUSTED_COOLING` and `EXHAUSTED_DEAD` are
supervision outcomes that the watcher writes onto the service through `set_service_status()`, so
today a resource's status mixes its own lifecycle with its supervisor's decisions.

| | N: No supervision state; `EXHAUSTED_*` leave `ResourceStatus` | R: Per-key record (episode task + COOLING/DEAD marker) |
|---|---|---|
| Needed under D17 | Yes: nothing restarts, so there are no episodes, budgets or cooldowns to track | Only with in-process restarts |
| What FAILED means | Final until a process restart, for every service | "Failed, maybe retrying"; the marker says which |
| Wire and UI | Two values leave `ResourceStatus` (hassette-wire); `retry_at` leaves the service payload; the frontend drops their mapping (diagnostics service row, sidebar groups, status utils) | Same removal, plus a dead flag and reason |
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

**Recommendation:** one escalation function on `Hassette`, beside its existing fatal-reason latch, so
the watcher and the no-supervisor path (D8) both reach it; `ServiceEscalationMixin` goes:
1. record the fatal reason in memory (first reason wins); it sets the exit code and the CRITICAL
   fatal-error line;
2. call `request_shutdown()`;
3. emit CRASHED as telemetry without awaiting it, so a full or dead channel never delays shutdown.
   The emit runs as a best-effort task in `Hassette`'s own bucket that logs a failed send at DEBUG;
   one cancelled or dropped by teardown is expected and not reported as leftover work.

Behavior to pin: shutdown is requested even when the event channel is full and undrained.

Nothing on this path awaits the database. Teardown's existing session finalize writes the fatal reason
to the session record, best-effort. `SessionManager`'s CRASHED listener is deleted, since finalize
already records the outcome.

Failure reports from required services (D2, D3), `FatalError`s raised by required services (a serve
failure carrying one arrives through the D8 report; one from an init body at boot is D1's), and
undelivered reports from required services (D8) all use it. A `FatalError` from an optional service
ends it dead in place like any other failure (D2). With no restarts, `fatal_error_names` has nothing to route around and
goes (D18).
**Pick keep-both instead if** an inline shutdown is needed somewhere for ordering. None found.
**Reversibility:** easy
**Ratified:** Chose one escalation function on `Hassette` that records the fatal reason in memory, calls `request_shutdown()` immediately and emits CRASHED without awaiting it over keeping inline `shutdown()` or writing the session record before shutdown, to let `run_forever()` own every fatal exit with no bus or database dependency, accepting that the session record gets the reason only if teardown's finalize reaches the database, the deletion of `SessionManager`'s CRASHED listener, and a duplicate CRASHED event when a required service's `FatalError` already emitted one (narrow re-challenge, Finding 4), and that a fatal report landing just after the last startup wave is ready can be preceded by the "Hassette is running" log line, with the exit code and reason still correct (Finding 7). Reframed at re-challenge 1 after D17; the direct session write was dropped at re-challenge 2 (Findings 1, 3) to match peers.

### D15: What do app lifecycle actions return, and how do the routes map it?

**Deciding factor:** report the operation's own result. Reading the registry after the lock is released
is racy, and a stop never shows a failure because stop unregisters regardless. HA's reload endpoint is
synchronous, refuses with a 4xx and returns `require_restart`.

| | A: Typed outcome returned from `AppLifecycleService` | B: Keep registry read-back, change status codes |
|---|---|---|
| Source of truth | The operation's own per-instance results (succeeded / failed / refused / needs restart), with reason | `get_failed_instance_infos()` after the lock is released |
| Concurrent-request misattribution | Gone | Remains (documented accepted risk today) |
| Stop failures | Visible | Invisible |
| HTTP mapping | Worst outcome wins: any failed or newly flagged instance gives 500, otherwise any refused (needs restart, app key busy) gives 409, otherwise 200. The body always lists every instance's outcome and names each instance that needs a hassette restart. A stop whose hook times out with work still pending is failed | 200 instead of 202; refusal codes added |
| Frontend | Minimal: accept 200, show the refusal or failure message and restart-required text | Same |
| Wire | `ActionResponse` reshaped, OpenAPI and types regenerated, `client_compat` entry | Same |

**Recommendation:** A, because it fixes misattribution and invisible stop failures at the source, and
it is the outcome contract the needs-restart flag needs anyway.
**Pick B instead if** the outcome type would need to thread through more layers than the lifecycle
mixins already return values from.
**Reversibility:** hard (published API contract)
**Ratified:** Chose a typed per-instance outcome returned by `AppLifecycleService` over registry read-back with new status codes, to report each request's own result including stop failures, accepting an `ActionResponse` wire reshape and a minimal frontend update. At the re-challenge comb, chose worst-outcome-wins status codes over always returning 200 with the outcomes in the body, so a failure never hides behind a 200, accepting that a partly successful bulk request returns an error code.

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
relies on an external one. The routine failure, losing Home Assistant, never reaches the watcher:
`WebsocketService` reconnects in place and its `serve()` doesn't exit on HA-side failures. Any other
failure of a required service, whatever its cause, is rare enough that a process restart is an
acceptable price. That includes `DatabaseService` raising on persistent heartbeat failure, an
environmental fault (a full disk, a locked file) that exits the process and fails the next boot the
same way until it is fixed, which the required-DB direction (#2695) already accepts.

| | X: No in-process restart | K: Keep watcher restarts |
|---|---|---|
| Required service crashes mid-run | D14 fatal exit; the external supervisor restarts the process | Backoff, budget and cooldown, then exit when exhausted |
| Optional service crashes | Dead in place with one ERROR (D2) | Restarted per its spec |
| Machinery | Removes `RestartBudget`, backoff, cooldown, same-object service restart, and most of the watcher | Keeps all of it |
| `RestartSpec` / `RestartType` | Replaced by one required/optional declaration per service | Unchanged |
| Cost of a transient crash | Every app re-initializes with the process | Only that service restarts |
| Bare `hassette run` without a restart policy | The process stays down after a crash; the docs require a restart policy, as D1 and D3 already assume | Survives in-process |
| Matches | HA core under the Supervisor; systemd/k8s process supervision | OTP, which has a VM to make it cheap |

Classification: required are `BusService`, `SchedulerService`, `SyncExecutorService`,
`WebsocketService`, `DatabaseService`, `CommandExecutor` and `WebApiService`. `WebApiService` is
required because it is the control plane: the CLI and the UI talk to it, and it serves the liveness
probe (`/api/health/live`), so a live process with a dead API would leave automations running with no
way to observe or control them. Optional are the two file watchers (`FileWatcherService`,
`WebUiWatcherService`); losing one only disables hot reload. A `Service` subclass that doesn't declare
required or optional fails at class definition, replacing today's missing-`restart_spec` warning
(Posture: loud failure).

The same-object re-initialization guard (`RestartRefusedError` raised by the coordinator after an
unsafe teardown) stays as an invariant of "one attempt per resource", though nothing triggers it in
normal operation.

**Recommendation:** X, because the routine failure is already handled in place, every other fatal path
already exits, and it removes the largest mechanism this milestone would otherwise build.
**Pick K instead if** a required service turns out to crash transiently in practice often enough that
restarting every app is disruptive, or users commonly run without a restart policy.
**Reversibility:** hard (restart machinery could return behind D8's report, but D13's wire removal
would need reversing)
**Ratified:** Chose no in-process service restart, with `WebApiService` required as the control plane, over keeping watcher restarts, to delete the restart machinery and give every service failure one outcome, accepting that a transient crash of any required service restarts every app, that a persistent environmental database fault crash-loops until fixed (as the required-DB direction, #2695, already implies), that hassette must run under a restart policy, and that on the HA add-on, where Watchdog is opt-in, Supervisor stops restarting after 10 attempts in 30 minutes, leaving automations stopped under a persistent fault until the user starts the add-on (re-challenge 2, Finding 13). Added at the sketch re-challenge from an inventory of built lifecycle machinery.

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
| Restart machinery: `RestartBudget`, `RestartSpec` and `RestartType` as a whole (D17), same-object service `restart()`, the watcher's admission checks, `log_service_event`, and the watcher's `Bus` child and bus dependency | D17 | One required/optional declaration per service |
| `_force_terminal()`'s terminal-status preservation | Exists only for `EXHAUSTED_*` (D13) | — |
| Restart safety meaning "any recorded cause" | A raised or timed-out hook, body or cleanup was cancelled and has ended | One predicate, "work may still be running", read by D5, D12 and the coordinator's re-init guard (kept as a cheap invariant, D17). It is true when the report's `pending_tasks` is non-empty, when it records `INITIALIZATION_TASK_PENDING` (which carries no task name), when the evidence is incomplete (`FORCED_TERMINAL`, `COORDINATOR_FAILED`), when a child's report satisfies the same predicate, or when the instance still has an active sync worker (an `AppSync` hook or sync handler running on a `SyncExecutorService` thread; cancelling its awaiting coroutine doesn't stop the thread). Tracking this is new: today the executor keeps only a global submission count and a per-submission handle with no owner. Each resource's `TaskBucket`, through which every per-resource thread submission already passes, keeps the handles it submitted until each worker thread finishes, not until its future completes (a cancelled future leaves the thread running), so the set stays bounded by running threads and a cancelled-but-running worker stays visible; the `TeardownReport` records the ones still active beside `pending_tasks`. Coverage: the instance's own tasks, its children's (including its `Bus`, so non-parallel handlers), and its sync workers. Parallel-mode handlers and scheduler jobs run in `BusService`'s and `SchedulerService`'s buckets and are not covered; which resource owns a handler's task is #1715's question, left out by D16. Every other cause is diagnostic only: raised or timed-out hooks, bodies and cleanups, and `SERVE_TASK_PENDING`/`TASKS_PENDING`, whose task names are already in `pending_tasks` |
| The shutdown budget allocation (shared hooks pool, margins, floors, per-wave division) | No peer splits shutdown time this way; it has caused #1809 and #2248; it shortchanges `on_shutdown` against the documented timeout (Assumed) | Plain per-stage timeouts (each hook gets the configured timeout, task cancel and cleanup have fixed caps, children are bounded by their own coordinators) plus one outer bound per resource, the only thing that can stop waiting on a cancellation-swallowing body; the coordinator's wait on an active initializer is capped by the per-stage shutdown timeout. The root's outer bound stays the whole-process ceiling, set by the total shutdown timeout: every per-resource bound and the concurrent app-shutdown deadline run inside it, it stays below the grace period the Docker and add-on docs give, and the root's separate fallback deadline folds into it |

**Separate issues, outside the milestone:** the `_pending_start_task` machinery and cross-thread
`start()`/`cancel()` redispatch; the remaining duplicate guards (`cleanup()` re-waiting init, unused
`initializing`/`task` properties); `TaskBucket` subclassing `Resource`.

Process shutdown stops app instances concurrently under one shared deadline of its own, not a share of
the app handler's hook time, so an app whose hooks run to their timeout costs no other app its
`on_shutdown` (chosen at the first sketch challenge, Finding 16). Behavior to pin: every app gets its
full shutdown timeout at process exit. An inferred bug, that later apps are cut off at process exit
because they shut down sequentially inside `AppHandler`'s own shutdown-hook pool (computed the same way as the per-app pool in Assumed), is reproduced first; the
test that reproduces it pins the fix.

**Reversibility:** easy (deletions; the shutdown-budget change touches shutdown timing everywhere but restores nothing callers rely on)
**Ratified:** Chose removing the six items above in the milestone, including the shutdown budget, and filing three smaller cleanups separately, over keeping built machinery or deferring the budget, to leave the milestone's decisions true and the lifecycle code smaller, with sync-worker handles held until their thread finishes (narrow re-challenge, Finding 5), accepting a medium-risk shutdown-timing change and that a failed init skips the app's `on_shutdown` (HA's rule). Added at the sketch re-challenge from the machinery inventory.

## Assumed

- No `Service` subclass overrides `after_initialize()`. The only overrides are on `StateManager`,
  `AppHandler` and `App`, none of them Services. Evidence: a search for `after_initialize`
  definitions in the `hassette` package.
- The only `Service` subclasses with children are `WebApiService` (`Scheduler`) and `SchedulerService`
  (`_ScheduledJobQueue`). `RuntimeQueryService` and `ServiceWatcher` own a `Bus` but are plain
  `Resource`s. Evidence: their `add_child` calls and base classes.
- With defaults, the shutdown budget gives an app's three shutdown hooks a shared 2.5s, while the
  operating docs say `app_shutdown_timeout_seconds` (10s) caps a single app's `on_shutdown`. Evidence:
  `compute_shutdown_budget` evaluated with the default settings; the operating docs page's shutdown
  timeout section.
- hassette runs under an external process supervisor that restarts it after a fatal exit: the HA
  add-on with Watchdog enabled (limits in D17), a Docker restart policy, or a systemd unit. D1, D3 and D17 depend on it. Evidence:
  the add-on's health check; the Docker getting-started compose snippet's restart policy.
- Readiness stays separate from status. Services that mark ready in `on_initialize()` (`WebApiService`,
  `WebsocketService`, disabled watchers) keep doing so, as listed in the resource-lifecycle rule file.
  D1 changes when RUNNING is set, not those rules.
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
  failures, so losing HA never reaches the watcher. Evidence: `WebsocketService.serve()` docstring.
- The CLI and the web UI reach a running instance only through `WebApiService`, which also serves the
  liveness probe the add-on's health check calls. Evidence: the CLI client; the add-on Dockerfile.
- `SyncExecutor` tracks only a global outstanding-submission count (for saturation warnings) and a
  per-submission `SyncWorkerHandle` with no owner; per-resource submissions all go through
  `TaskBucket.run_in_thread()`. Evidence: `SyncExecutor.submit()` and `TaskBucket.run_in_thread()`.
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
  nonzero exit code and a CRITICAL line naming the reason, an optional one is FAILED (CRASHED for `FatalError`) with one ERROR; nothing restarts a service
  in-process, and `ResourceStatus` has no `EXHAUSTED_*` values;
- a failure report arriving after shutdown was requested doesn't escalate, so a clean stop exits 0, and
  a required service whose `serve()` returns unrequested counts as failed;
- a service is RUNNING only after its initialization completes, and a boot-time start failure fails
  startup;
- bus death, at boot or later, shuts the process down without hanging, and every resource still
  reaches STOPPED;
- a timed-out app hook never leaves an instance marked STOPPED while its work runs: it is FAILED, and
  flagged needs-restart in the API, CLI and UI when work D18's predicate covers was still running after
  cancellation, until hassette restarts;
- no path creates an instance over a needs-restart instance, and every reload decides, stops and
  creates under the app-key lock;
- app action endpoints return each request's own per-instance outcome;
- every app gets its documented shutdown timeout at process exit;
- the docs describe all of the above; each issue ships its own docs (Summary, "Docs and UI").

Applies to all: D4 (an app failure never takes down the process or its siblings) and the Posture's
"no silent states" rule.

1. **Simplify shutdown timing to per-stage timeouts**: replace the shutdown budget allocation with
   per-stage timeouts plus one outer bound per resource (keeping the root's process-wide ceiling and
   folding the root's fallback deadline into it), merge the app and resource shutdown timeouts into one
   setting, and stop app instances concurrently under one
   deadline at process exit. Reproduce the suspected cut-off of later apps first. Implements: D18
   (shutdown budget, concurrent app shutdown). After: none. Issue: #3104
2. **Remove `strict_lifecycle` and the status transition table**: delete transition validation, and
   decide the setting's other readers: `WebsocketService`'s connection-state check, strict registry
   validation (enabled only by this setting today, and forced on by the test harness), and the
   transition error's place in the WS reconnect's propagated exceptions. Implements:
   D16 (#2697), D18. After: none. Issue: #3105
3. **Mark a service RUNNING only after initialization completes**: start `serve()` last, add the
   no-waiting-on-parent-serve rule, make boot start failures fatal. Implements: D1, D7. After: none.
   Issue: #3106
4. **Report service failures directly and stop restarting services in-process**: the direct report and
   its contract, required/optional classification replacing restart specs (an undeclared Service fails at class definition), dead-in-place optional
   services, one fatal escalation path, removal of restart budgets, backoff, cooldown, `EXHAUSTED_*`
   (wire and frontend mapping), the watcher's bus dependency, `ServiceEscalationMixin` and `SessionManager`'s
   CRASHED listener; a failed optional service is left un-shut-down. Implements: D2, D8, D13, D14, D17, D18
   (restart machinery, terminal-status preservation), and D7's boot outcome for serve failures.
   After: 2, 3. Issue: #3107
5. **Shut down cleanly when the bus dies**: route bus death through issue 4's fatal path, have the bus
   close the event streams on any failure (init or serve) so no producer blocks, have direct
   `EventStreamService.send_event()` callers handle the closed-stream error, and let status transitions
   run with closed streams.
   Implements: D3, D9. After: 4. Issue: #3108
6. **Flag app instances that need a restart after a hook timeout**: route failed and timed-out init
   through instance shutdown (user hooks skipped), remove the app-layer stop timeout (the init deadline stays and triggers instance shutdown) and hand-rolled
   cleanup, adopt the "work may still be running" safety predicate, including per-bucket tracking of active sync workers as evidence
   and in the coordinator's re-init guard, add the needs-restart record,
   `AppInstanceInfo` fields, the minimal UI badge, and the flag and reason in the CLI's app listing.
   Implements: D5, D10, D11, D12 (flag), D18 (app timeouts, restart safety). After: 1. Issue: #3109
7. **Decide reloads under the app-key lock and refuse unsafe replacements**: decide, stop, gate and
   create under one lock; refuse every instance-creating path over a
   needs-restart instance; log refusals that have no response channel. Implements: D6, D12 (gate). After: 6. Issue: #3110
8. **Return typed outcomes from app actions**: per-instance outcomes from `AppLifecycleService`, the
   worst-outcome-wins 200/409/500 mapping, `ActionResponse` reshape, the minimal frontend change, and
   the CLI's app action output reporting refusals and failures instead of success. Implements: D15.
   After: 6, 7. Issue: #3111

Housekeeping outside the issues (D16, D18), done: #1222 closed as obsolete; #1721 trimmed to the
coordinator and shutdown-body splits; separate issues outside the milestone: #3112 (`_pending_start_task`
machinery), #3113 (remaining duplicate guards), #3114 (`TaskBucket` subclassing `Resource`). Milestone:
*Resource Lifecycle*; the overlapping originals closed as superseded.
