---
topic: "Lifecycle outcomes and failure ownership in async frameworks"
date: 2026-10-18
status: Draft
---

# Prior Art: Lifecycle Outcomes and Failure Ownership

Builds on `design/research/2026-04-28-service-supervision/research.md` (restart budgets, retryability,
readiness vs liveness) and `design/research/2026-04-26-resource-service-lifecycle/research.md` (state
machines, LIFO shutdown, cleanup contexts). Those briefs cover *how to restart*. This one covers what
the resource-lifecycle milestone is about: who owns a failure, when "started" is true, what happens
to work that outlives its timeout, how a live instance is replaced, and how an operation reports what
actually happened.

## The Problem

Hassette infers lifecycle outcomes instead of recording them, in three places:

- **Service supervision.** `ServiceWatcher` works out who owns a failure from the `_restarting` set,
  the service's status, and the step order in `restart_service()`. A failed restart attempt reports
  twice: `restart()` raises, and the service emits a FAILED event onto the bus. #3034 needed six local
  guards (#3036).
- **App instances.** Start and stop wrap the coordinator in `anyio.fail_after`, but the coordinator
  shields the real task, so a timeout abandons the hook while the instance is marked STOPPED/FAILED
  (#1797, #2780). Reload replaces an instance without checking its teardown (#1689).
- **Operation results.** Web start/stop/reload return 202 "accepted" even after the operation failed
  (#1698).

Two structural gaps sit underneath: a service is RUNNING (and can be ready) before `initialize()`
returns, and the bus delivers its own FAILED event, so a dead bus can't be noticed (#1224).

## How We Do It Today

- **Per resource:** one coordinator owns exactly one init attempt and one shutdown attempt
  (`_init_task`, `_shutdown_task`, joined through `asyncio.shield`). `TeardownReport` records
  `TeardownCause` evidence. `is_restart_safe` is derived from it, and an unsafe report blocks any
  in-process restart (`RestartRefusedError`).
- **Services:** `RestartSpec` + `ServiceWatcher`, driven by FAILED events on the bus. A refused
  restart escalates to root `request_shutdown()`: the process exits and Docker or systemd restarts it.
- **Apps:** `app_lifecycle_instances.py` wraps `initialize()`/`shutdown()` in `fail_after` and sets
  status directly on timeout. Nothing consults the old instance's `TeardownReport` before a
  replacement is created.
- **Service start:** `_initialize_body()` starts `serve()` (marks RUNNING) before `after_initialize()`
  and child initialization run.

## Patterns Found

### Pattern 1: One serial owner per child, with incarnation identity

**Used by**: Erlang/OTP supervisor, systemd (one job slot per unit), kubelet (one worker per pod UID)

**How it works**: The OTP supervisor is a single process that handles messages one at a time, so two
failure reports for one child are never processed concurrently. Exits are keyed by the pid of the
incarnation. An EXIT from a pid no longer in the child table is silently dropped. A restart whose
start fails leaves the child as `{restarting, OldPid}` and re-queues the retry as a message to
itself, so every attempt passes through the same handler and counts against the restart intensity.
Other operations (`delete_child`) are rejected with `{error, restarting}` while in that state.

The key property: **a failed start is a return value, not a second notification.** No new child was
linked, so no EXIT arrives for it. One failed attempt produces one signal.

systemd and kubelet reach the same shape differently: one installed job per unit with explicit
merge/replace rules, and one goroutine per pod with a latest-wins pending slot.

**Strengths**: Ownership follows from state and identity, not from step order. Stale reports are
discarded by identity rather than by checking current status.

**Weaknesses**: Needs a real per-incarnation identity and a stated policy for triggers that arrive
mid-episode (drop, coalesce, replace).

**Example**: https://raw.githubusercontent.com/erlang/otp/master/lib/stdlib/src/supervisor.erl

### Pattern 2: "Started" means initialization returned

**Used by**: OTP `start_link` / `init/1` / `handle_continue`; systemd `Type=notify` and `Type=exec`;
trio `nursery.start()` / `task_status.started()`

**How it works**: The started ack is withheld until initialization finishes. OTP's `start_link` "does
not return until Module:init/1 has returned or failed". For supervisors that also means until every
child has started. Post-init work (`handle_continue`) runs after the ack but before any external
message is served, and a crash there is an ordinary crash of a started child. systemd `Type=notify`
is started only at `READY=1`. `ExecStartPost` is part of the start transaction, and its failure fails
the unit. trio splits failure ownership on the handoff: an exception before `started()` goes to the
caller of `start()`, and one after it goes to the nursery.

The peer that reports started early, systemd `Type=simple`, is documented as reporting success even
when exec fails. `notify` and `exec` exist to fix that.

**Strengths**: A service can't look healthy mid-initialization. A pre-start failure has exactly one
owner, the starter.

**Weaknesses**: A long init blocks the starter, so it needs a start timeout. Services that
deliberately serve before their children are up need to be audited.

**Example**: https://www.erlang.org/doc/apps/stdlib/gen_server.html,
https://trio.readthedocs.io/en/stable/reference-core.html

### Pattern 3: Failure detection outside the supervised channel, and accepting process exit at the root

**Used by**: OTP (links/monitors delivered by the VM), systemd (SIGCHLD/cgroup plus a watchdog
deadline), HA Supervisor (external API probe of Core)

**How it works**: The thing that detects a death is never the thing that died, or a channel it can
wedge. OTP exit signals come from the VM's link table, not a user message bus. The systemd watchdog
is a deadline the manager enforces: a missed `WATCHDOG=1` is itself the failure. It arms only after
start-up completes. HA Core does not supervise its own event bus. The HA Supervisor probes Core's API
and restarts the container after two missed responses (user-reported logs; no official doc found).
At the top of an OTP tree, a supervisor that exceeds its intensity terminates itself and something
outside the tree restarts it.

In asyncio the analogue is a done-callback on the task, or awaiting it, rather than a published
status event. That is an inference; no asyncio write-up was found.

**Strengths**: A detector can't be lost along with the bus. There's no "the dead thing restarts
itself" case.

**Weaknesses**: Two sources (task exit and the published status) must be reconciled unless one is
made authoritative. Root failure costs a full process restart.

**Example**: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html

### Pattern 4: Stop waiting and document the limitation (the Python norm)

**Used by**: HA core integration setup, AppDaemon, pyscript

**How it works**: Python can't kill a coroutine. The anyio docs state that asyncio cancellation can
be ignored, and nothing forcibly ends a task that shields or never yields. Peers that can kill
(Erlang shutdown timeout then `kill`, systemd `TimeoutStopSec` then SIGKILL, k8s grace period then
SIGKILL) rely on an OS or VM boundary. Python peers stop waiting. HA's `setup.py` logs "Startup will
proceed without waiting any longer" after `SLOW_SETUP_MAX_WAIT = 300` and returns False, without
tracking the task. A comment there calls a cancelled setup "in an indeterminate state". HA has no
per-entry timeout on `async_setup_entry` or unload, so a hung entry holds its lock. AppDaemon
documents that a slow `terminate()` hangs AppDaemon. pyscript lets old functions run to completion
across a reload, and `task.unique()` is the opt-in for killing them.

No Python framework was found that tracks abandoned hook tasks after a timeout.

**Strengths**: No machinery.

**Weaknesses**: Reported state and reality diverge, and late completions can mutate registries. This
is exactly #1797 and #2780.

**Example**: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/setup.py,
https://anyio.readthedocs.io/en/stable/cancellation.html

### Pattern 5: A non-recoverable instance state that refuses reload

**Used by**: Home Assistant config entries; Erlang code server (`soft_purge`); Kubernetes StatefulSet
(at-most-one identity)

**How it works**: `ConfigEntryState` values are `(value, recoverable)` pairs. If
`async_unload_entry` returns False, raises, or doesn't exist, the entry becomes `FAILED_UNLOAD` with a
`reason` string. That state is non-recoverable, so `async_unload`, and therefore `async_reload`,
raises `OperationNotAllowed`. The user's remedy is restarting HA (community reports; the docs don't
say). Since 2022.7 HA also refuses a reload while setup is in progress, instead of cancelling the
setup, after reloads during setup caused unrecoverable states. A per-entry `setup_lock` covers the
whole unload-then-setup sequence. If unload fails, reload returns without running setup.

Erlang keeps at most two code versions. Loading a third either refuses (`soft_purge` /
`not_purged`) or kills the processes still in old code (`purge`). Kubernetes frees a StatefulSet
pod's identity only after the kubelet confirms termination. Its docs name force-delete, which frees
the name early, as the way duplicate live pods happen.

**Strengths**: Cheap, truthful, and makes an overlapping incarnation impossible without killing
anything. It is the same rule hassette already applies to services (`RestartRefusedError`), applied
to a single instance.

**Weaknesses**: One bad unload takes the instance out until process restart.

**Example**: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/config_entries.py,
https://www.erlang.org/doc/apps/kernel/code.html,
https://kubernetes.io/docs/tasks/run-application/force-delete-stateful-set-pod/

### Pattern 6: Operation result separate from subject state, reported truthfully

**Used by**: systemd (job result vs unit state), HA (`ConfigEntryState` + `reason` + `recoverable`),
Erlang (`{ok, Pid} | ignore | {error, Reason}`), Kubernetes conditions (detail unverified)

**How it works**: The operation's result is a small vocabulary that carries the cause. systemd job
results are `done`, `canceled`, `timeout`, `failed`, `dependency` and `skipped`, so timeout is
distinct from failure. The subject's state is separate and persistent (`ActiveState`, `SubState`,
`Result`). systemd notes that a `canceled` job may leave the operation running: stopping the wait is
not stopping the work. HA folds outcome into entry state, but the `recoverable` bit makes the
consequence machine-readable.

Delivery: HA's reload endpoint is synchronous. Refusal maps to 403, and otherwise the response is
200 `{"require_restart": not recoverable}`. systemd returns a job handle and reports completion
through `JobRemoved`, because its operations can be long and queued. No peer returns "accepted" for
an operation it already knows failed.

**Strengths**: Consumers can tell timeout from error and act on "restart required".

**Weaknesses**: Two vocabularies to keep consistent.

**Example**: https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html,
https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/config/config_entries.py

## Anti-Patterns

- **Reporting "stopped" when only the wait ended.** systemd (`canceled`), k8s force-delete and HA's
  own setup comment all document this failure. Hassette's `inst.status = STOPPED` in the timeout
  branch is this.
- **Freeing an identity before termination is confirmed.** k8s force-delete permits duplicate live
  pods. Hassette's reload creates a replacement with the same `instance_name`/owner_id without
  consulting teardown evidence.
- **Reporting started before the start phase ends.** systemd documents `Type=simple` reporting
  success when exec fails. This is hassette's RUNNING-before-`initialize()`-returns.
- **Two failure channels for one incarnation with neither authoritative.** No source documents this
  by name; it is what Pattern 1 avoids.
- **Reload during in-flight setup.** HA saw unrecoverable states from it before 2022.7, and now
  refuses.

## Relevance to Us

**Failure ownership (#3036).** OTP avoids double handling with three things: a serial owner,
incarnation identity, and a failed start being a return value instead of a second event. Hassette's
episode already gets the return value from `restart()`. What creates the second signal is the FAILED
event published during the attempt. Pattern 2's handoff decides who owns it: before "started", the
attempt's caller; after, the watcher. With that rule plus an incarnation id on status events, most of
the six guards become a rule rather than step order. The proposed six-state machine is more than
OTP needs. OTP's per-child state is only "running pid" or `restarting`, and serial handling does the
rest. The state machine may still be the right Python expression of "serial owner", but it should be
sized to that job.

**When "started" means started (#3036 comments).** Every peer withholds "started" until init returns,
and the one that doesn't is documented as a mistake. That supports holding back RUNNING (and serve
readiness) until `initialize()` completes, which closes the fifth and sixth #3034 instances at the
lifecycle layer. The cost noted in #3036 still holds: services that serve before their children are
up need an audit.

**Bus self-supervision (#1224).** No peer supervises its own event channel from inside it. Detection
moves out of band (a done-callback on the bus's serve task), and the outcome for a dead bus is
process exit with an external restart, as HA Core does under the Supervisor. That is much smaller
than #1224's current acceptance criteria (re-clone the stream and restart in-process), and hassette
already exits on refused restarts.

**Timed-out hooks (#1797, #2780).** Hassette can't kill a coroutine either, so "kill on timeout" isn't
available. The peer norm is to stop waiting and say nothing. Hassette can do better at little cost,
because the coordinator already owns the task and the evidence: on timeout, keep the instance in a
named "abandoned/stuck" state backed by its `TeardownReport`, rather than setting STOPPED. No peer
tracks abandoned hooks, so this is beyond the ecosystem norm, but only slightly.

**Replacing a live instance (#1689, #2481).** HA's config entries are the direct model and match
hassette's existing service rule. A failed unload is a non-recoverable instance state, reload refuses
it with `OperationNotAllowed`, and one per-entry lock covers unload plus setup. That covers #1689 gap
1 (decide under the lock) and gap 2 (don't create over an unconfirmed teardown). **Load-before-stop
(#2481) has no peer.** HA doesn't reload code on config-entry reload, AppDaemon and pyscript point at
the log, and Erlang's two-version loading is a VM feature. Building it is novel, not catching up.

**Scope of a failure (#1716).** The services side and the apps side disagree with each other, and HA
sides with apps. HA keeps a broken entry stuck in place with `require_restart` and leaves the rest of
the process running. Hassette rejected "degraded in place" for services when it closed PR #1782, and
exits the process instead. For user apps, the HA shape is the peer norm and less disruptive: one bad
app shouldn't restart every app. For framework services, exiting still holds.

**Outcomes (#1698).** Synchronous completion with a truthful status is what HA does for the same
operation, and fits hassette's routes, which already await completion. A refusal maps to a 4xx (HA
uses 403; 409 fits hassette's case), and the body carries a `require_restart`-style flag derived from
the instance's recoverable state. systemd's distinction between timeout and failed is worth keeping.
`TeardownCause` already records it.

## Recommendation

Take five things, in this order of leverage:

1. **Adopt "started = `initialize()` returned"** (Pattern 2), and split failure ownership on that
   handoff. That alone closes two of #3034's six instances and fixes the rule the rest depend on.
2. **Size #3036 to OTP's shape** (Pattern 1): one serial owner per service, an incarnation id that
   discards stale reports, and a failed attempt reported once, through the attempt's result. Decide
   in the sketch whether that needs six named states or two.
3. **Give app instances HA's config-entry rules** (Pattern 5):
   - a non-recoverable state, backed by the `TeardownReport`, for a teardown that didn't finish or a
     hook that timed out;
   - reload refused from that state, and refused while setup is in flight;
   - one per-app-key lock across stop plus create;
   - a stuck app stays stuck in place, without taking down the process.

   This replaces the `fail_after` + `status = STOPPED` pattern behind #1797, #2780 and #1689.
4. **Report outcomes like HA's reload endpoint** (Pattern 6): synchronous, 4xx on refusal, plus a
   restart-required flag (#1698).
5. **Make bus death fatal and detect it out of band** (Pattern 3) instead of restarting the bus
   in-process (#1224).

Leave out:

- **Abandoned-task tracking beyond a named stuck state.** No peer does it.
- **Load-before-stop (#2481).** It would be novel, so treat it as its own feature, not a hardening
  item.

Coverage gaps: the Kubernetes pod-lifecycle and condition details weren't verified against the page,
and the kubelet sources are v1.15-era. No source covered OTP's handling of a child that starts and
then crashes immediately during a restart, or the HA Supervisor watchdog's documented behavior. No
won't-fix issues were found for these questions; the "accepted limitation" evidence comes from docs
and code comments.

## Sources

Note: these URLs were not live-verified after research.

### Reference implementations
- https://raw.githubusercontent.com/erlang/otp/master/lib/stdlib/src/supervisor.erl — stale EXIT dropped by pid; `{restarting, OldPid}` and self-cast retry
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/config_entries.py — `ConfigEntryState` with `recoverable`; `OperationNotAllowed`; `setup_lock` around reload
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/setup.py — `SLOW_SETUP_MAX_WAIT`; stop waiting and proceed
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/config/config_entries.py — sync reload endpoint, 403 on refusal, `require_restart`
- https://third-party-mirror.googlesource.com/systemd/+/refs/heads/master/src/core/job.h — one job per unit, merge/replace modes
- https://git.microlab.ntua.gr/tzeneto/custom-kube-scheduler/src/master/kubernetes/pkg/kubelet/pod_workers.go — per-pod serial worker (v1.15 mirror)
- https://mode.readthedocs.io/en/stable/_modules/mode/supervisors.html — Python supervisor using an event wake plus periodic poll

### Blog posts & writeups
- https://contributors.home-assistant.io/blog/2022/06/13/unsafe_reloads_during_entry_setup/ — HA refuses reload during setup (summary only, not fetched)
- https://community.home-assistant.io/t/tado-failed-to-unload/760594 — FAILED_UNLOAD remedy is restarting HA
- https://community.home-assistant.io/t/problems-with-restarts/682579 — Supervisor watchdog restarts Core after missed API responses
- https://www.alibabacloud.com/blog/understanding-the-kubelet-core-execution-frame_593904 — kubelet pod worker model

### Documentation & standards
- https://www.erlang.org/doc/apps/stdlib/supervisor.html — `start_link` blocks through children; shutdown timeout then kill; `restarting` state
- https://www.erlang.org/doc/apps/stdlib/gen_server.html — `start_link` blocks on `init/1`; `handle_continue`
- https://www.erlang.org/doc/apps/kernel/code.html — two code versions; `soft_purge` refuses, `purge` kills
- https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html — `Type=`, `ExecStartPost`, timeouts, watchdog
- https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html — job results vs unit state; job handles
- https://trio.readthedocs.io/en/stable/reference-core.html — `nursery.start()` failure split on `started()`
- https://anyio.readthedocs.io/en/stable/cancellation.html — asyncio cancellation can be ignored; shielding only for bounded cleanup
- https://contributors.home-assistant.io/core/integrations/config-entries/ — config entry states, `async_on_unload`
- https://contributors.home-assistant.io/apps/reference/configuration/ — add-on `watchdog` probe
- https://kubernetes.io/docs/tasks/run-application/force-delete-stateful-set-pod/ — at-most-one identity; force-delete hazard
- https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/ — grace period, conditions (unverified)
- https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html — slow `terminate()` hangs AppDaemon; no init timeout
- https://hacs-pyscript.readthedocs.io/en/latest/reference.html — old functions keep running through reload; `task.unique()`
