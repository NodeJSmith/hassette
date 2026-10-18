# Design: Resource Lifecycle Outcomes

**Date:** 2026-10-18
**Status:** draft
**Mode:** sketch
**Issues:** #3036, #1716, #1224, #1797, #2780, #1689 (gaps 1 and 2), #1698

## Summary

Hassette infers lifecycle outcomes instead of recording them. `ServiceWatcher` works out who owns a
service failure from a `_restarting` set, the service's status and step order. App start/stop wrap
the lifecycle coordinator in `anyio.fail_after`, so a timeout abandons the user's hook while the
instance is marked STOPPED/FAILED. Reload creates a replacement without checking the old instance's
teardown. The app action routes read the registry back after the lock is released to guess whether an
action failed. This initiative makes each outcome an explicit, recorded fact. Prior art:
`design/research/2026-10-18-lifecycle-outcomes/prior-art.md` (OTP supervisors, systemd, trio, and HA
config entries).

This ledger is initiative-level. It is not built in one session. It ends in a GitHub milestone plus
high-level issues that name components and behavior, never line numbers. The milestone's Done-when
comes from D-decisions below.

Areas and where each new piece lives:

- **Service start handoff** — `Service._initialize_body()` / `Service._serve_wrapper()` in
  `src/hassette/resources/service.py`. A service is RUNNING only after `initialize()` (hooks and
  children) has completed.
- **Service supervision** — `ServiceWatcher` (`src/hassette/core/service_watcher.py`) and
  `ServiceEscalationMixin` (`service_watcher_escalation.py`). A watcher-owned supervision state machine per
  service key (D13) replaces `_restarting`, the stale-status check and the step-order guards, and
  takes over the `EXHAUSTED_*` outcomes from `ResourceStatus`. How failures reach the
  watcher is D8.
- **Fatal escalation** — one fatal-exit path on the escalation mixin, used by PERMANENT exhaustion,
  restart refusal of a required service, and fatal errors.
- **Dead bus** — the bus's first serve failure arrives as a D8 report. `BusService` opts into the
  `RestartSpec` fatal-on-first-failure option (D3), which escalates through D14. After bus death, no
  producer blocks (D9): `Hassette.send_event()` and `EventStreamService.send_event()`.
- **Supervisor hook** — on `Hassette`, registered by `ServiceWatcher` at construction. Lifecycle code
  reports post-handoff serve failures to it with a per-resource run generation (D8).
- **App instance state** — the per-instance stuck condition
  (home per D11), set by the app lifecycle mixins (`app_lifecycle_instances.py`,
  `app_lifecycle_start_stop.py`, `app_lifecycle_changes.py`) and held in `AppRegistry`
  (`app_registry.py`).
- **Action outcomes** — a typed outcome returned by `AppLifecycleService` start/stop/reload methods,
  mapped by `_run_app_action()` in `src/hassette/web/routes/apps.py`. The frontend action buttons get
  minimal changes only.
- **Docs and UI** (per `.claude/rules/design-completeness.md`, shipping with the issue that introduces
  each behavior):
  - the app lifecycle docs explain hook timeouts, the stuck states, reload refusal,
    and "restart hassette to recover";
  - the service supervision docs explain type-driven refusal, fatal exit, and boot fail-fast;
  - the UI shows an instance's stuck condition and its reason, as minimal text or
    badge only, since a UI rework is coming.

Out of scope:
- **Closed:** #2481 (load-before-stop), #1767 (in-process service reconstruction), #1390 (process
  restart command).
- **Moved to the log-identity initiative:** #1689 gap 3 (`unique_name` collisions across app keys).
- **Separate initiatives or features:** the lifecycle signal taxonomy (#685, #686), a lifecycle
  controller object (#1237), app-author features (#1830, #67, #608, #1676), #2976, #3029, #2781,
  #2938.

## Posture

- **Failure handling:** loud. A required framework service escalates to process exit; a broken app
  stops only itself; no new retry machinery beyond the existing `RestartSpec`.
- **Compatibility:** break freely (pre-V1). Changes to `hassette-wire` enums or published payloads go
  through `tools/client_compat_ignore.txt` with changelog and migration notes, because hassette-wire
  and hassette-client are released packages.
- **Scope:** minimal per concern. The deliverable is a milestone of high-level issues, not one build.
- **Rollout:** ship outright. The endpoint contract change and its minimal frontend change land in the
  same release as the app-state changes.
- **Hardening:** project defaults, plus one raised requirement: every new stuck or dead-in-place
  state is visible as a status and one ERROR log naming the cause. No silent states.
- **Concurrency:** one serial owner per supervised thing: one supervision record per service key in
  the watcher, and the existing per-app-key lock for apps. No new global locks.

## Decisions

### D1: When does a Service count as started?

**Deciding factor:** every peer (OTP `start_link`, systemd `Type=notify`, trio `nursery.start()`)
withholds "started" until initialization returns; the one that doesn't (systemd `Type=simple`) is a
documented trap.

**Recommendation:** RUNNING only after `initialize()` completes, including `after_initialize()` and
child initialization. A failure before that handoff belongs to the caller of the attempt. A failure
after it belongs to the supervisor. D7 decides how that ordering is achieved.

At boot, the first start has no supervising caller (startup waves start children fire-and-forget and
then wait for readiness). A boot-time start failure is therefore fatal regardless of `RestartType`:
the wave isn't ready, startup fails, and the external supervisor restarts the process. This is a
behavior change. Today a FAILED event from a boot failure in a post-watcher wave reaches
`restart_service()` and gets retried. It is accepted, because a wave that isn't ready is already fatal
today, so a retry only ever helped if it won inside the wave timeout.
**Pick the status quo instead if** a service genuinely needs to look RUNNING while its children
start. None was found.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose RUNNING-after-initialize over serve-time RUNNING, to make a failed attempt fail exactly once at the attempt, accepting a readiness-timing audit of every service. Boot fail-fast chosen at the sketch challenge (Finding 6) over making the first start a supervised attempt, accepting the loss of in-process retry for transient boot failures.

### D2: Where does a refused service restart escalate?

**Deciding factor:** a broken required service is not worth running without, but an optional one is.

**Recommendation:** refusal follows `RestartType`. A TEMPORARY service whose restart is refused ends DEAD in
place: the service is FAILED and its watcher supervision state is DEAD (D13). A PERMANENT or TRANSIENT service escalates to process exit, and the external
supervisor restarts the process. No in-process reconstruction.
**Pick root-exit for everything instead if** an optional service with live leftover work is judged more
dangerous than one more restart.
**Reversibility:** easy
A TEMPORARY service that ends DEAD in place logs one ERROR naming the pending tasks from its
`TeardownReport` and saying a hassette restart clears it (Posture: no silent states).
**Ratified:** Ratified in conversation (2026-10-18): chose type-driven refusal over always-exit, to stop an optional watcher's slow teardown from restarting every app, accepting that a TEMPORARY service with unconfirmed teardown stays dead in place with its leftover work running until a manual restart, announced by one ERROR.

### D3: What happens when the bus dies?

**Deciding factor:** no peer supervises its event channel from inside it.

**Recommendation:** detect bus death without relying on the bus, then start a fatal shutdown. Shutdown
must complete with the bus dead. No in-process bus restart. D8 decides the detection mechanism and D9
decides how sends behave.

"Bus death" is the bus's first post-handoff serve failure. It is expressed declaratively: `RestartSpec`
gains a "fatal on first failure" option, `BusService` opts in in place of `CORE_PERMANENT_RESTART`,
and the watcher routes it through D14 without knowing which service it is. That also retires today's
by-name `BusService` special case (`on_bus_service_running`). To make a deterministic crash loop
visible, startup logs the previous session's fatal reason when the last session ended in a fatal exit.
**Pick in-process bus restart instead if** process restarts turn out to be frequent in practice. They
aren't today.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose fatal shutdown over in-process bus restart, to match OTP/HA root-failure handling, accepting a full process restart on bus death. At the sketch challenge (Findings 9, 21), chose a declarative fatal-on-first-failure `RestartSpec` option over routing through the bus budget or a by-name watcher case, accepting that a transient bus failure costs a process restart; a boot-time log of the previous fatal reason makes a crash loop visible.

### D4: What is the blast radius of a broken app?

**Deciding factor:** HA config entries: one broken entry is stuck in place with a `require_restart`
signal, and the rest keeps running.

**Recommendation:** a broken app instance affects only itself, never the process or its siblings.
An instance stuck on work that never ends is recovered by restarting hassette manually (D12).
**Pick process exit instead if** never. Apps are user code and must not restart the framework.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose app-scoped failure over process exit, to keep unrelated automations running, accepting that an instance stuck on never-ending work needs a manual hassette restart (no restart command; #1390 closed).

### D5: What happens when an app hook outlives its timeout?

**Deciding factor:** Python can't kill a coroutine, but the coordinator already owns the task and can
observe when it ends.

**Recommendation:** a timed-out `on_initialize`/`on_shutdown` leaves the instance in a named stuck
state for as long as the abandoned work is still running. When that work actually ends (observed, not
assumed), the instance becomes ordinary failed and reloadable (D12: there is no terminal state). D10
decides whether the init attempt is also cancelled.
**Pick terminal-until-restart instead if** observing the abandoned task is unreliable. It isn't: the
coordinator holds `_init_task` / `_shutdown_task` / `_shutdown_body_task`.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose stuck-until-the-work-ends over terminal-until-restart, to recover automatically from a merely slow hook, accepting one extra transition per instance.

### D6: Which lock guards app reload decisions?

**Deciding factor:** HA's per-entry `setup_lock` covers the whole unload-then-setup sequence, and
`start_instance()` already re-reads state under the lock.

**Recommendation:** the per-app-key lock covers the whole operation: the decision (dormant check,
changed indices, valid indices), the stop, the replacement gate (D12), and the create. Every reload and
config-change path re-reads its inputs under the lock. A reload is refused while a setup for that
instance is in flight, and while the old instance is stuck (D12).
**Pick finer-grained locks instead if** whole-app-key serialization measurably delays unrelated
instances. Nothing suggests it does.
**Reversibility:** easy
**Ratified:** Ratified in conversation (2026-10-18): chose one per-app-key lock across decide+stop+create over the current unlocked decision, to close #1689 gaps 1 and 2, accepting serialized per-instance reloads within one app key.

### D7: How does `Service._initialize_body()` achieve "RUNNING after initialize"?

**Deciding factor:** fewest moving parts that make a pre-handoff failure impossible to report twice.

| | A: Start `serve()` last | B: Keep spawn order, move the RUNNING transition | C: Keep spawn order, route early serve failures to the attempt |
|---|---|---|---|
| Change | Spawn the serve task after `after_initialize()` and child init; `_serve_wrapper()` still sets RUNNING when serve starts | Spawn serve where it is; `_initialize_body()` sets RUNNING after children; `_serve_wrapper()` no longer does | Spawn serve where it is; a serve failure before init returns is handed to the init attempt to raise, not to `handle_failed()` |
| Can serve fail mid-attempt? | Only in the few loop turns between serve starting and `restart()` returning to the watcher; the run generation (D8) attributes such a failure to the attempt | Yes: serve runs, but status stays STARTING. Its failure still goes through `handle_failed()` unless also rerouted | Yes, but it is owned by the attempt |
| Services affected | Any service whose children or `after_initialize()` need serve already running. Scan: no `Service` overrides `after_initialize()`; service children are `Scheduler`, `Bus`, `_ScheduledJobQueue`, none of which wait on the parent's serve | None by timing | None by timing |
| Code | Reorder plus doc update; the docstring's deadlock warning becomes a rule: a Service's children and `after_initialize()` must not wait on the parent's `serve()` or readiness. It goes into `.claude/rules/resource-lifecycle.md`, with a test | Two transition sites to keep in sync | New cross-task failure handoff |
| Matches prior art | trio/OTP: init completes, then the loop runs | systemd `notify`: running ≠ started | trio's pre-`started()` exception routing |

**Recommendation:** A, because it narrows the mid-attempt window to a few loop turns (closed by the
run generation in D8) instead of guarding it, and the scan found no service that needs serve running
before its children.
**Pick B instead if** the audit finds a service whose child initialization needs its serve loop
draining work. **Pick C instead if** that same need shows up and B's double-path proves unworkable.
**Reversibility:** easy (local to `service.py`)
**Ratified:** Chose starting `serve()` last over moving the RUNNING transition or routing early serve failures, to remove the mid-attempt window instead of guarding it, accepting a readiness-timing audit of every service.

### D8: How does `ServiceWatcher` learn that a service failed?

**Deciding factor:** detection outside the supervised channel (OTP links, systemd SIGCHLD/watchdog). A
bus-delivered failure is what makes a dead bus undetectable and what gives one failure two signals.

| | A: Keep bus FAILED events, add a bus-death hook | B: Direct report to the watcher for every service; bus events become telemetry only |
|---|---|---|
| Signals per failure | Two (attempt result and bus event), so failure ownership still has to be inferred | One: a failed attempt raises; a post-handoff serve failure is reported once, directly |
| Dead bus | Needs a special out-of-band hook (done-callback on the bus serve task, registered by `Hassette`) | Reported like any other service failure, then routed fatal by D3 |
| What it deletes | Nothing | The watcher's internal bus listeners, `reconcile_after_bus_recovery()`, `on_bus_service_running()`, the stale-status check, and the in-restart guard's reason to exist |
| Coupling | Unchanged | Lifecycle code reports to a supervisor hook on `Hassette` (the watcher registers itself); resources gain one call-out |
| User-visible | Unchanged | `on_hassette_service_failed` etc. keep firing as telemetry; only the watcher stops consuming them |
| #3036 size | Full state machine still needed to arbitrate two channels | Smaller: one channel, so a serial owner per key is enough (D13) |

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
  readiness-timeout warning) → after a successful attempt, the watcher awaits the service's readiness
  directly, bounded by `startup_timeout_seconds`, resets the budget on readiness, and warns on
  timeout;
- the watcher's `on_bus_service_running` / `reconcile_after_bus_recovery` → deleted (D3: no
  in-process bus recovery);
- `SessionManager`'s CRASHED listener → D14 marks the session failed directly.

**Report contract.**
- **Report site.** A dedicated report function, called only from `_serve_wrapper()` after the
  handoff. `handle_failed()` and `handle_crash()` stay status and telemetry. Pre-handoff init failures
  and swallowed shutdown-hook failures are never reports.
- **Run identity.** Each serve run gets a per-resource run generation, stamped when the run starts.
  Every report carries it, and the watcher decides ownership from the report alone (D13). Precedent:
  `WebsocketService`'s connection generation.
- **Recipient.** The watcher no longer depends on the bus, so its supervisor hook is registered on
  `Hassette` at construction, before any startup wave runs. A report with no registered supervisor
  logs ERROR and escalates fatal for a required service. The test harness, which has no watcher, opts
  out explicitly.

**Reversibility:** hard (changes how supervision is wired; partial rollback re-introduces the guards)
**Ratified:** Chose direct reporting with bus events as telemetry over keeping bus-delivered FAILED events plus a bus-death hook, to give each failure one signal and make bus death an ordinary report, accepting one supervisor call-out from lifecycle code to `Hassette`. The acting-consumer inventory and report contract (dedicated report site, run generation, registration at construction, loud undelivered reports) were added at the sketch challenge (Findings 1, 2, 4, 5, 7, 12).

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
also releases a sender already blocked on a full channel. A dead bus does not release blocked senders
by itself: `BusService` holds a clone of the receive stream, and `EventStreamService` keeps the
original open. Behavior to pin:
- after bus death, no producer blocks, and events are dropped with a debug log;
- status transitions still happen. `Resource._shutdown_body()` no longer skips `handle_stop()` when
  the streams are closed, so every resource still reaches STOPPED during the fatal teardown, and only
  the event send is dropped.
**Pick B instead if** a wedged-but-alive bus (not dead, just not draining) also needs to be survivable.
That is out of scope under the posture.
**Reversibility:** easy
**Ratified:** Chose closing the event streams on bus death over per-send timeouts or a bus-dead flag, to release every blocked producer through the existing closed-stream drop, accepting that a wedged-but-alive bus stays out of scope. At the sketch challenge (Finding 10), chose letting `handle_stop()` run with closed streams over accepting skipped STOPPED transitions.

### D10: Is a timed-out app initializer cancelled?

**Deciding factor:** a timed-out init is being discarded, so its work has no future; interrupting
cleanup, however, can leave resources half-released (#2780).

| | A: Cancel init on timeout, never cancel shutdown | B: Cancel neither | C: Cancel both |
|---|---|---|---|
| Init timeout | Cancel the init attempt and detach its listeners and jobs at once (today's `cleanup_failed_instance()`); stay stuck until the init work actually ends | Stuck until init finishes by itself, possibly forever; then tear down what it registered | Same as A |
| Shutdown timeout | Stuck until `on_shutdown` ends by itself | Same | Cancelled; cleanup may be left half-done |
| Late registrations (#1797) | Usually prevented: cancellation lands at the next await | Happen, then get torn down | Prevented |
| Matches | `anyio`: cancel, then bound and observe; #1797's fix direction | pyscript / HA: just wait | Erlang `brutal_kill`, which Python can't do |

**Recommendation:** A, because it shortens a discarded init without risking a half-done cleanup.
**Pick B instead if** apps commonly do work in `on_initialize` that must not be interrupted mid-way
(for example, creating HA helpers).
**Reversibility:** easy
**Ratified:** Chose cancelling a timed-out init but never a timed-out shutdown over cancelling neither or both, to cut short discarded work without half-finishing cleanup, accepting that a cancellation-ignoring init still stays stuck until it ends.

### D11: Where does an app instance's stuck state live?

**Deciding factor:** it must survive the instance being unregistered (a stuck stop must still be
visible and block replacement), must be read by the replacement gate, the routes and the UI, and must
not stretch a type that services also use.

| | A: New `ResourceStatus` values (wire) | B: An instance condition held by `AppRegistry` | C: Derived on demand from the coordinator |
|---|---|---|---|
| Vocabulary | e.g. a new `STUCK` value (hook still running) | `InstanceEntry` gains a condition (`stuck_initializing`, `stuck_stopping`) plus a reason; `AppStatus` is derived from it as today | Read `_init_task` / `_shutdown_body_task` / `teardown_report` each time |
| Survives stop/unregister | Only if the registry keeps the entry anyway | Yes: the registry keeps the entry until the condition clears | No: needs the entry kept anyway |
| Shared with services | Yes: every `ResourceStatus` consumer (watcher, telemetry, web) must handle values only apps reach | No | No |
| Wire change | `ResourceStatus` enum, plus a `client_compat` ignore entry | `AppInstanceInfo` gains fields and `AppStatus` may gain a value; it is already app-only | None, but the UI can't show it |
| Matches HA | State enum carrying `recoverable` + `reason` | Same shape, scoped to apps | — |

**Recommendation:** B, because the state is app-only and must outlive unregistration, which is the
registry's job. This keeps `ResourceStatus` unchanged for services.
**Pick A instead if** services later need the same stuck notion (they don't under D2, which escalates
instead).

Under B, `ResourceStatus` is never overwritten to hide reality. It reports the coordinator's actual
phase, and the condition carries why and whether it is recoverable:

| Situation | `ResourceStatus` | Condition |
|---|---|---|
| Init timed out and is still running | `STARTING` | `stuck_initializing` |
| Abandoned init ended | `FAILED` | cleared |
| Shutdown timed out and is still running | `STOPPING` | `stuck_stopping` (the entry stays registered) |
| Abandoned shutdown ended | `STOPPED`, or `FAILED` if it raised; then unregistered | cleared |

D12 leaves no terminal condition: work that never ends keeps the instance stuck.

**A stuck instance is a tombstone, not a live entry.**
- **Registrations:** its listeners and jobs are detached the moment it becomes stuck. Only the
  abandoned work is tracked, for D12's gate.
- **Readers:** every "live" registry reader (the `registry.get(...) is not None` style checks in
  `AppFactory` and the app lifecycle mixins) excludes tombstones, so a stuck instance never counts as
  running.
- **Phase:** `InstanceEntry` carries one phase enum (live / `stuck_initializing` / `stuck_stopping`)
  plus a reason, not separate flags.
- **Transitions:** done-callbacks only *schedule* one coroutine, which performs every post-stuck
  transition while holding the app-key lock.
- **Lock:** a stop that leaves an instance stuck returns a "stuck" outcome and releases the lock.
- **Process shutdown:** stops app instances concurrently under one shared deadline, so a stuck app
  costs no other app its `on_shutdown`. `clear_all()` drops tombstones.

For `AppStatus`, a stuck instance counts as not running, the same way FAILED does
(`DEGRADED` beside running siblings, `FAILED` if none run). The condition is shown next to it.

The app phase vocabulary is deliberately separate from D13's service supervision states. Services and
apps live on separate UI surfaces (diagnostics vs the apps page), and each is mapped once, in its own
place.

The registry condition is the instance's persistent state for later readers. D15's outcome is what one
request did. Both are set in the same transition under the app-key lock.

**Reversibility:** hard (wire shape the UI and client consume)
**Ratified:** Chose an `AppRegistry` instance condition over new `ResourceStatus` values or on-demand derivation, to keep app-only state off the type services share and keep it visible after unregistration, accepting an `AppInstanceInfo` wire change. At the sketch challenge (Findings 3, 11, 15, 16, 20), chose the tombstone model (registrations detached, excluded from live readers, one locked transition coroutine, lock released, concurrent process shutdown) and separate service/app vocabularies, accepting that app shutdown order is no longer sequential.

### D12: What old-instance evidence allows a replacement, and what is terminal?

**Deciding factor:** the danger is two live incarnations (k8s's at-most-one identity), not an exception
in user code. HA marks a raised unload terminal, but hassette reloads on every file save, so a buggy
`on_shutdown` would force a restart on every edit.

"Work ended" means *observed* ended, from what the framework tracks:
- the coordinator's tasks (`_init_task`, `_shutdown_task`, `_shutdown_body_task`);
- the instance's `TaskBucket`, including handler dispatches, job runs, and tasks the app created in
  its context, which the loop task factory attributes via `CURRENT_BUCKET`;
- the same for its children, recursively;
- framework-owned work that bypasses buckets (the app's `AsyncCache`), through an override hook.

The draft primitive is `is_teardown_confirmed_quiescent()` plus the `_has_untracked_teardown_work_pending()`
hook on closed PR #1782's branch (`1716`, head 231ebc7). It is not on this branch, so landing it is the
milestone's blocking first issue: D6, D11, D12 and D15 all depend on it. Threads, subprocesses and
external side effects the user starts outside hassette's context are invisible under every option.

| | A′: No terminal state; stuck until every tracked task ends | A: Terminal after an observation cutoff | B: Terminal for any failed teardown (HA's rule) |
|---|---|---|---|
| `on_shutdown` raised, all work ended | Recoverable: log ERROR, allow replacement | Recoverable | Terminal until manual restart |
| Tracked work still running | `stuck_*`; clears itself when the work ends (done-callbacks, no polling) | `unrecoverable` after the cutoff, even if the work ends later | Terminal |
| Work that never ends | Stuck indefinitely; the condition says to restart hassette if it doesn't clear | Terminal | Terminal |
| States and knobs | 2 conditions, no cutoff | 3 conditions plus a cutoff constant | 3 conditions |
| Dev reload loop | A cleanup bug doesn't block reloading the fix | Same | A cleanup bug forces a restart per edit |
| Matches | Erlang `soft_purge` (refuse only while old code is live) | — | HA `FAILED_UNLOAD` |

**Recommendation:** A′, because it refuses exactly the overlap the gate exists to prevent, has no cutoff
to tune, and never declares dead an instance that later recovers.
**Pick A instead if** a definite "needs restart" signal matters more than avoiding a cutoff.
**Pick B instead if** a raised `on_shutdown` commonly leaves external state (HA entities, sockets)
that a replacement would collide with, and the framework can't see it.
**Reversibility:** easy
**Ratified:** Chose no terminal state (stuck until every tracked task is observed ended) over a cutoff or HA's any-failed-teardown rule, to refuse only real overlap and keep hot reload usable, accepting that work which never ends leaves an instance stuck until a manual restart.

### D13: Where does per-service supervision state live?

**Deciding factor:** each owner holds its own state. `EXHAUSTED_COOLING` and `EXHAUSTED_DEAD` are
supervision outcomes that the watcher writes onto the service through `set_service_status()`, so
today a resource's status mixes its own lifecycle with its supervisor's decisions.

| | A: Episode record in the watcher; outcomes stay on the service's status | B: Watcher state machine owns supervision; `EXHAUSTED_*` leave `ResourceStatus` |
|---|---|---|
| Single source of truth | Yes, but on the wrong owner: the watcher writes its decisions onto the resource | Yes; each owner holds its own state |
| Enforced transitions | Only if the phase is an enum with a check | Yes, from a documented transition table |
| Cooldown | Split between the service status and the episode phase | One state, COOLING |
| Wire and UI | No change | Two values leave `ResourceStatus` (hassette-wire). The WS service payload gains a `supervision` field. Status mapping changes in the frontend (diagnostics service row, sidebar groups, status and status-priority utils), with their tests |
| Matches | OTP's minimal per-child record | systemd: the unit's `ActiveState` stays separate from the manager's job and restart state |

States in B: IDLE, BACKING_OFF, ATTEMPTING, COOLING, DEAD. Exhaustion is a decision made inside a
transition, not a state. `ResourceStatus` keeps only lifecycle values (NOT_STARTED, STARTING,
RUNNING, STOPPING, STOPPED, FAILED, CRASHED). Behavior to pin:
- only IDLE starts an episode from a failure report;
- during ATTEMPTING, a report whose run generation (D8) matches the run the attempt started counts
  as that attempt's failure;
- every other report is dropped;
- all transitions go through one function that rejects illegal moves;
- each attempt is bounded by `startup_timeout_seconds`. On timeout the init attempt is cancelled (as
  D10 does for apps), and the attempt counts as failed against the budget;
- every service-status message carries the lifecycle status and the supervision state together (the
  way `retry_at` rides today), and `Hassette` exposes a read accessor for supervision state;
- once `EXHAUSTED_DEAD` leaves `ResourceStatus`, `handle_failed()`'s terminal guard and
  `_force_terminal()` treat a supervision-DEAD service as plain FAILED. Only the watcher starts
  restarts, so DEAD is enforced by supervision state, not by `VALID_TRANSITIONS`.

**Recommendation:** B, because it is the design we'd build from scratch: no duplicated outcome, an
enforced lifecycle, and resource status that means only what the resource is doing.
**Pick A instead if** this initiative's wire and frontend footprint must stay as small as possible.
**Reversibility:** hard (wire enum and WS payload)
**Ratified:** Chose a watcher-owned supervision state machine with `EXHAUSTED_*` removed from `ResourceStatus` over an episode record that leaves outcomes on service status, to give supervision and lifecycle one owner each with enforced transitions, accepting a wire change and a frontend status-mapping update. Bounded attempts, the merged status payload and the terminal-guard rule were added at the sketch challenge (Findings 8, 14).

### D14: Do the service fatal paths share one exit route?

**Deciding factor:** consistency. Today PERMANENT exhaustion calls `hassette.shutdown()` inline, while
restart refusal records the fatal reason and calls `request_shutdown()` so that `run_forever()` owns
teardown.

**Recommendation:** one escalation function on `ServiceEscalationMixin`:
1. record the fatal reason;
2. mark the session failed directly (the effect `SessionManager.on_service_crashed` has today), so the
   session record doesn't depend on the CRASHED event being delivered;
3. emit CRASHED best-effort;
4. call `request_shutdown()`.

PERMANENT exhaustion, refusal of a required service, `fatal_error_names` routing, fatal-on-first-failure
services (D3) and undelivered reports from required services (D8) all use it.
**Pick keep-both instead if** an inline shutdown is needed somewhere for ordering. None found.
**Reversibility:** easy
**Ratified:** Chose one escalation function ending in `request_shutdown()` over keeping PERMANENT exhaustion's inline `shutdown()`, to let `run_forever()` own every fatal exit, accepting nothing beyond the rename of call sites.

### D15: What do app lifecycle actions return, and how do the routes map it?

**Deciding factor:** report the operation's own result. Reading the registry after the lock is released
is racy, and a stop never shows a failure because stop unregisters regardless. HA's reload endpoint is
synchronous, refuses with a 4xx and returns `require_restart`.

| | A: Typed outcome returned from `AppLifecycleService` | B: Keep registry read-back, change status codes |
|---|---|---|
| Source of truth | The operation's own per-instance results (succeeded / failed / refused / stuck), with reason and recoverable | `get_failed_instance_infos()` after the lock is released |
| Concurrent-request misattribution | Gone | Remains (documented accepted risk today) |
| Stop failures | Visible | Invisible |
| HTTP mapping | 200 with the outcome on success; 409 for refused (stuck, in flight); 500 for failed; the body names each stuck instance and says it clears when its work ends, or needs a hassette restart if it doesn't | 200 instead of 202; refusal codes added |
| Frontend | Minimal: accept 200, show the refusal or failure message and restart-required text | Same |
| Wire | `ActionResponse` reshaped, OpenAPI and types regenerated, `client_compat` entry | Same |

**Recommendation:** A, because it fixes misattribution and invisible stop failures at the source, and
it is the outcome contract the stuck states need anyway.
**Pick B instead if** the outcome type would need to thread through more layers than the lifecycle
mixins already return values from.
**Reversibility:** hard (published API contract)
**Ratified:** Chose a typed per-instance outcome returned by `AppLifecycleService` over registry read-back with new status codes, to report each request's own result including stop failures, accepting an `ActionResponse` wire reshape and a minimal frontend update.

### D16: Which nearby issues ride along?

**Deciding factor:** include an item only if the Done-when fails without it, or if it is cheaper
inside this work than after it.

| Item | Recommendation | Why |
|---|---|---|
| #1222 concurrent init/shutdown interleaving | Close as obsolete | The early return it cites is gone; the single-attempt coordinator covers all three gaps (`.claude/rules/resource-lifecycle.md`, "One attempt per resource") |
| #2697 remove `strict_lifecycle` | In | D7 and D13 change status transitions, which should be tested on the behavior production runs; cheap pre-V1 |
| #1715 handler cancels itself via its own resource's shutdown | Out | Real but independent of outcome recording; keep in `epic:correctness` |
| #1721 remaining function splits | Out, and trim the issue | `restart_service()`/`execute_restart()` are rewritten by D8/D13; the coordinator and `_shutdown_body()` splits are code quality |

**Recommendation:** take the table as written.
**Pick differently if** you want the milestone to carry the correctness bug #1715 too.
**Reversibility:** easy
**Ratified:** Chose closing #1222, including #2697, and leaving #1715 and the trimmed #1721 out over also carrying #1715, to keep the milestone to what its Done-when needs, accepting that the self-cancel bug waits in the correctness bucket.

## Assumed

- No `Service` subclass overrides `after_initialize()`. The only `after_initialize` overrides are on
  `StateManager`, `AppHandler` and `App`, none of them Services. Evidence: `rg "def after_initialize" src/hassette`.
- Services with children: `WebApiService` (`Scheduler`), `RuntimeQueryService` (`Bus`),
  `SchedulerService` (`_ScheduledJobQueue`), `ServiceWatcher` (`Bus`). Evidence: `add_child` calls in
  those modules.
- Readiness stays separate from status. Services that mark ready in `on_initialize()` (`WebApiService`,
  `WebsocketService`, disabled watchers) keep doing so, as listed in
  `.claude/rules/resource-lifecycle.md`. D1 changes when RUNNING is set, not those rules.
- The lifecycle coordinator owns exactly one init and one shutdown attempt per resource and exposes
  `_init_task`, `_shutdown_task`, `_shutdown_body_task` and `teardown_report`. Evidence:
  `src/hassette/resources/lifecycle.py` (`coordinate_initialize`, `coordinate_shutdown`); rule file
  section "One attempt per resource".
- An unsafe `TeardownReport` already blocks in-process restart of the same object
  (`RestartRefusedError`). Apps dodge it only because reload builds a new object. Evidence: rule file
  section "Teardown reports"; `AppLifecycleService` reload paths.
- `Hassette.send_event()` already drops events when the streams are closed. Evidence:
  `src/hassette/core/core.py` (`send_event`, `event_streams_closed`).
- `ResourceStatus` and `AppStatus` are published in `hassette-wire`. `ServiceStatusPayload` is internal
  (`src/hassette/events/hassette.py`). Evidence: `wire/src/hassette_wire/enums.py`.
- `_run_app_action()` already maps bootstrap-not-released, blocked and in-progress to 409, and recorded
  failures to 500. Only the success shape (202 `accepted`) and the read-back source change. Evidence:
  `src/hassette/web/routes/apps.py`.

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
