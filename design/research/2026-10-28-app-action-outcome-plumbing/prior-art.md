---
topic: "How frameworks carry per-target lifecycle outcomes internally, through gathers and multi-phase operations"
date: 2026-10-28
status: Draft
---

# Prior Art: Carrying Per-Target Lifecycle Outcomes Internally

## The Problem

Spec 140 has each app action (start, stop, reload, app-wide or per instance) report one outcome per targeted
instance, decided under the app-key lock. Inside hassette, those outcomes are decided deep in the lifecycle
code. There's a class load shared by every index, config validation per index, init per index (settled by a
shutdown on failure), and a post-ready DB reconciliation. Stops run concurrently through a gather that
re-raises the first exception and drops its siblings' results. Reload runs stop then start under one lock.
Many failures are recorded into `AppRegistry` as side effects instead of being returned. This brief asks
how peers carry such outcomes back to the caller, and what went wrong for them.

The companion brief `2026-10-28-app-action-outcomes/prior-art.md` covers the wire side.

## How We Do It Today

Lifecycle methods return `None`. Failures go to `AppRegistry.record_failure` and `flag_needs_restart`, and
the route reads the registry back after the lock is released. `gather_all` re-raises the first exception.
Class-load failure is recorded at one index only. `create_single_instance` swallows validation failures, and
its caller detects them by `registry.get(...) is None`.

## Answers by Peer

### Home Assistant core (`config_entries.py`)
- **Carrier:** state on the target, plus a bool. `ConfigEntry.async_setup` returns `None` and records
  `SETUP_ERROR`/`SETUP_RETRY` on the entry. `async_unload` catches `Exception`, sets `FAILED_UNLOAD` with
  `reason=str(exc)`, and returns `False`. The `ConfigEntries` methods return bools, sometimes re-derived from
  state (`entry.state is LOADED`).
- **Gathers:** `async_forward_entry_setups` uses a plain `asyncio.gather`, so the first exception wins and the
  siblings run unobserved. `async_unload_platforms` is `all(await gather(...))` over bools, and is only safe
  because each child catches its own exceptions.
- **Reload:** under `setup_lock`, `if not unload_result: return unload_result`. A failed unload short-circuits
  and setup never runs. Otherwise reload returns setup's bool.
- **History:**
  - #117756 fixed a setup race by re-checking state after taking the lock.
  - #111784 was a concurrent-reload race.
  - #138522 added `UNLOAD_IN_PROGRESS` and made a `False` from `async_unload_entry` set `FAILED_UNLOAD`, because
    "a failed unload means partial unload".
  - #170163 is a hung unload with no timeout that leaves the entry stuck.

### Node-RED (`flows/Flow.js`)
- **Carrier:** none. Log and continue. `stopNode` races `node.close()` against a per-node timeout and catches
  everything, so `Promise.all` never rejects, and no per-node result exists.

### AppDaemon (`app_management.py`)
- **Carrier:** a mix. `stop_app` returns a bool, `start_app` raises `InitializationFail` after setting state,
  and an `objects[name].running` / admin state holds the rest.
- **Known defect:** `stop_app` discards `terminate_app`'s `False`, so a raising `terminate()` reports a
  successful stop.
- **Multi-phase:** `_stop_apps` collects a `failed_to_stop` set and subtracts it from the init and reload sets,
  so a failed stop gates the start phase.

### NetDaemon (`Application.cs`)
- **Carrier:** a derived `State` property on the target (error flag, plus whether a context exists).
- Unload exceptions and timeouts were logged and the unload "succeeded". Commit 4aede33 later blocked
  re-instancing after a faulty unload, the same lesson as hassette's needs-restart gate.

### Python structured concurrency
- `gather` drops sibling results on the first exception, and `return_exceptions=True` returns a mixed list.
- `TaskGroup` cancels siblings on the first failure (cpython#101581 asks for an opt-out).
- trio leaves result collection to the caller, and its maintainers recommend wrapping each child to store
  its result keyed by target (trio#2633).

### Kubernetes kubelet (`container/sync_result.go`)
- **Carrier:** a per-request collector. `PodSyncResult{SyncResults []*SyncResult, SyncError}`, with one
  `SyncResult{Action, Target, Error, Message}` per (action, target), filled with `.Fail()` and appended.
  `Error()` aggregates every failed result.
- **Multi-phase:** `AddPodSyncResult` merges phases. Known gotcha: it overwrites `SyncError`, so an earlier
  phase's error is lost (last writer wins).
- **Shared failure:** has its own slot (`SyncError`, or a pod-level action), and isn't copied onto every
  container.

### systemd (`core/job.c`)
- **Carrier:** a typed `JobResult` per job, delivered by `job_finish_and_invalidate` and also stored on the
  unit.
- **Shared failure:** dependents get their own `JOB_DEPENDENCY` result ("Dependency failed for X") that points
  at the root, while the root job keeps `JOB_FAILED`.

## Patterns Found

### Pattern 1: State on the target, bool as convenience
**Used by**: Home Assistant, NetDaemon, partly AppDaemon
**How it works**: the failing code sets the target's state and reason where it fails. The caller reads the
state, or a bool derived from it.
**Strengths**: little plumbing; survives an escaping exception when set in `except`/`finally`.
**Weaknesses**: the caller learns the target's state, not what this call did. It races when state is read
outside the deciding lock (HA #117756, #111784, and hassette's own bug). It leaves stuck intermediate states
on hangs (#170163). This is hassette's registry, and spec 140's option C.
**Example**: HA `ConfigEntry.async_unload`.

### Pattern 2: Per-request collector with per-target slots
**Used by**: kubelet `PodSyncResult`
**How it works**: a result object passed through the operation; each (action, target) gets a slot; a separate
slot holds failures that belong to no single target; an aggregate method builds the overall error.
**Strengths**: sibling results are never lost, a shared failure has an explicit home, and merging phases is
one method.
**Weaknesses**: the merge rule is easy to get wrong (kubelet's overwrite); it needs plumbing.
**Example**: https://github.com/kubernetes/kubernetes/blob/master/pkg/kubelet/container/sync_result.go

### Pattern 3: A child never raises, so the gather is safe by construction
**Used by**: Node-RED (`.catch` per node), HA `async_unload` (try/except → `False`), the trio recipe
**How it works**: each concurrent child catches its own failure and returns or records an outcome.
**Strengths**: sibling outcomes are always kept.
**Weaknesses**: `BaseException`/`CancelledError` still escape, and a catch-all hides bugs unless the outcome
records the exception.

### Pattern 4: A failed first phase gates the second
**Used by**: HA `async_reload`, AppDaemon `_stop_apps`
**How it works**: if the stop/unload half fails, the start/setup half doesn't run, and the result is the
failing half's.
**Strengths**: never starts on top of a half-stopped target.
**Weaknesses**: to report both halves, the stop half's information has to be kept explicitly.

### Pattern 5: A distinct result for a shared cause
**Used by**: systemd `JOB_DEPENDENCY`
**How it works**: every dependent gets its own outcome, which names the root cause rather than duplicating it.

## Anti-Patterns

- Discarding a callee's result (AppDaemon `stop_app` drops `terminate_app`'s `False`).
- A last-writer-wins merge across phases (kubelet `AddPodSyncResult`).
- A plain `gather` over children that can raise (HA's forward setups).
- Reading state outside the lock that decides it (HA #117756, #111784, and hassette's current route).

## Relevance to Us

- Hassette's registry is Pattern 1, and its bug (reading after the lock) is the race HA fixed by reading under
  the lock. Reading under the lock (option C) would match HA. But HA's single-entry targets never need to know
  "what did *this* call do" across several indices and two phases, and hassette's outcomes do.
- Pattern 2 (kubelet) is a direct match for spec 140's needs. It gives one slot per targeted index, a home for a
  shared failure (class load), and siblings that survive an escaping exception. It also makes the "every
  targeted index exactly once" invariant enforceable in one place. Its documented pitfall is the merge rule,
  which is Finding 4's question.
- Pattern 3 is what `gather_all` should do whatever the carrier is.
- Pattern 4 is what hassette's reload already does implicitly: a stop that newly flags an index makes the
  create half's gate refuse it. HA and AppDaemon both let the failing half's outcome stand.
- Pattern 5 answers class-load attribution: each `to_create` index gets `failed` with a reason naming the
  shared import failure.

## Recommendation

Use a per-request collector (Pattern 2) passed explicitly down the lifecycle paths. It should have one slot per
targeted index declared up front, children that record before returning (Pattern 3), class-load failures
attributed to every target with a shared-cause reason (Pattern 5), and a stated merge rule for reload where a
failing stop half stands (Pattern 4), avoiding kubelet's overwrite. Return-value threading reaches the same
end state, but needs a try/except at every level to keep partial results. That is exactly what the challenge
found missing.

Coverage gaps: systemd's restart-job result merging wasn't read. No Node-RED or AppDaemon issue about lost
sibling results was found. Line numbers come from branch heads and may drift.

## Sources

(Not live-verified.)

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py
- https://github.com/node-red/node-red/blob/master/packages/node_modules/%40node-red/runtime/lib/flows/Flow.js
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/app_management.py
- https://github.com/net-daemon/netdaemon/blob/main/src/AppModel/NetDaemon.AppModel/Internal/Application.cs
- https://github.com/kubernetes/kubernetes/blob/master/pkg/kubelet/container/sync_result.go
- https://github.com/systemd/systemd/blob/main/src/core/job.c

### Issues, PRs & commits
- https://github.com/home-assistant/core/pull/117756 — re-check state after taking the lock
- https://github.com/home-assistant/core/issues/111784 — concurrent reload race
- https://github.com/home-assistant/core/pull/138522 — `UNLOAD_IN_PROGRESS`, failed unload is `FAILED_UNLOAD`
- https://github.com/home-assistant/core/issues/170163 — hung unload stuck forever
- https://github.com/net-daemon/netdaemon/commit/4aede33a509ff7b4d5cdeb83fe372515fb4ee50c — block re-instancing after faulty unload
- https://github.com/python-trio/trio/issues/2633 — collect results yourself
- https://github.com/python/cpython/issues/101581 — TaskGroup sibling cancellation opt-out

### Documentation
- https://docs.python.org/3/library/asyncio-task.html — gather, `return_exceptions`, TaskGroup
