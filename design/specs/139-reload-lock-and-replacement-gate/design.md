# Design: Reload Decisions Under the App-Key Lock, and the Needs-Restart Replacement Gate

**Date:** 2026-10-28
**Status:** built
**Mode:** sketch
**Issues:** #3110
**Parent:** design/specs/134-resource-lifecycle-outcomes/design.md

## Summary

Breakdown item 7 of the Resource Lifecycle milestone ledger. It implements parent D6 (one per-app-key
lock across decide, stop, gate and create) and the gate half of parent D12 (refuse creating an instance
over one flagged needs-restart). The flag itself shipped with #3109 (spec 138, PR #3550).

The problems, in today's code:

- **Stale reload plans (#1689 gap 1).** `AppChangeReconcilerMixin.apply_changes`
  (`src/hassette/core/app_lifecycle_changes.py`) runs `_should_restart` and `_plan_reload` before
  `_restart_apps` takes the app-key locks. Both read registry state. A stop that already holds a lock
  finishes during the wait, and the stale plan then recreates the instances it stopped.
- **Unsafe replacements (#1689 gap 2).** No instance-creating path checks the needs-restart flag. A
  replacement can therefore be created over an instance whose teardown left work running.

The change:

- **Lock move.** `apply_changes` walks every key in `reimport_apps` and `reload_apps` in sorted order,
  one key at a time. It acquires key k's lock, evaluates `_should_restart` and `_plan_reload` for k
  under it, and then, before moving to the next key, either releases k (its plan is empty, D1) or keeps
  it held for the stop and create phases (it restarts). Each key is released exactly once, including
  when its decision raises or the task is cancelled during acquisition or decision. A kept key is
  released after the last replacement is created. Lock acquisition moves out of `_restart_apps`, which
  becomes a caller-holds-locks body (`asyncio.Lock` is not reentrant).
- **Flagged lookup.** A public `AppRegistry.get_needs_restart(app_key, index)`
  (`src/hassette/core/app_registry.py`) returns the index's `NeedsRestartRecord`, or `None` when it
  isn't flagged. The record serves as the gate's test and as the refusal message's data. It reads
  `_needs_restart` with `.get` (the dict is a `defaultdict`, and `[]` access would insert an empty
  entry) and doesn't build an `AppInstanceInfo`.
- **Refusal formatter.** A module-level function in `app_registry.py`, beside `NeedsRestartRecord`,
  takes the app key, the index and the record, and returns the refusal message. Both funnels call it
  and log the result at ERROR with their own logger. It lives with the record because the two
  funnels are in sibling classes (`AppFactory` and `AppLifecycleService`) that both already hold the
  registry.
- **The gate, at the two funnels every instance-creating path passes through:**
  - `AppFactory.create_instances` (`src/hassette/core/app_factory.py`) serves app start, whole-app
    reload, autostart and whole-app restarts. It skips flagged indices before instantiation, the same
    way it already skips live ones. When every configured index is flagged, there is nothing to
    create, so it refuses before `load_class`: no load, and no class-load failure recorded. This is
    not a re-import guarantee. A partly flagged app is still re-imported for its other indices (D2). A class-load failure is recorded against the first
    configured index that is neither live nor flagged; if there is none, the failure is logged and not
    recorded.
  - `_create_instance_unlocked` (`src/hassette/core/app_lifecycle_start_stop.py`) serves instance
    start, instance reload and per-index restarts. It checks the flag right after the blocked check,
    which stays first and still raises `AppBlockedError`, and before
    `factory.load_class(..., force_reload)`. A refused index therefore never re-imports the module or
    records a class-load failure over itself.
  - D2 settles how a refusal is reported. Both funnels build the refusal ERROR with the refusal
    formatter above. The line names the instance, the app key and
    index, the original flag reason and `flagged_at`, and says to restart hassette, so both funnels
    write the same line and it points back to the flag's own ERROR.
- **Docs.**
  - `docs/pages/operating/index.md#instances-that-need-a-restart` explains start and reload refusal.
  - The Start/Stop/Reload table in `docs/pages/web-ui/manage-apps.md` says a flagged instance is
    skipped.
  - The existing "Restart refusal" section of the app lifecycle docs, which covers
    `RestartRefusedError`, is disambiguated from this refusal.
- **Housekeeping the issue requires:**
  - The `_failed_target_instances` docstring in `src/hassette/web/routes/apps.py` points at #3111
    instead of #3110.
  - Spec 138's `design.md` gets an `## Addendum` entry: its "left this for #3110" note (the route
    verdict) now belongs to #3111.
  - Spec 134's Addendum gets a dated entry for this issue. It records that D1 below keeps D6 as
    written: no-op keys release their lock once decided, so the issue body's departure is not
    needed. It also records D2's departure from D12.
  - Spec 138 KI-003 (`design/specs/138-needs-restart-flag/known-issues.md`) is re-checked: with
    replacements over flagged indices refused, can a WS `app_status_changed` event still carry a
    non-null `needs_restart` with a non-failed status? Close or update the entry.

Where new state and behavior live: the lookup and the refusal formatter in `app_registry.py`; the gate in
`AppFactory.create_instances` and `_create_instance_unlocked`; the lock scope in `apply_changes`. No
new state is added; the needs-restart record already exists.

Out of scope:

- Route verdicts for flagged indices, the typed per-instance outcome and response shape (parent D15,
  #3111).
- Deduplicating repeated refusal ERRORs.
- `start_apps`'s pre-existing boot-time race on `autostart` (below, in Assumed).

## Posture

- **Failure handling:** loud. A refusal logs one ERROR naming the instance and saying to restart
  hassette. It is never queued or replayed; the next save decides from scratch. A refused index never
  affects its siblings (parent D4).
- **Compatibility:** break freely (pre-V1). No wire or payload change is expected; the route response
  shape is #3111's.
- **Scope:** minimal: the lock move and the gate only. Repeated refusal ERRORs on each save of a flagged
  autostart app are accepted, not deduplicated.
- **Rollout:** ship outright.
- **Hardening:** project defaults plus the parent's "no silent states" rule: every refusal is logged.
- **Concurrency:** the existing per-app-key `AppKeyLock` is the only serial owner. No new locks. Several
  keys are always taken in sorted order.
- **Altitude:** build; one session builds it, and this ledger cites files.

## Decisions

### D1: What happens to the lock of a key whose reload plan comes out empty?

Supersedes the issue body's resolution, which departs from parent D6's wording. A key in `reimport_apps`
or `reload_apps` can turn out to need nothing: `_should_restart` is false (dormant with autostart false),
or `_plan_reload` finds no per-instance change. The decision must be made under the lock (D6), so the
lock is already held when the answer comes back.

**Deciding factor:** decide under the lock without making an untouched key answer 409 for a batch that
does nothing to it.

| | H: Hold every lock through the batch (issue body) | R: Release a no-op key's lock as soon as it is decided | P: Pre-filter before locking |
|---|---|---|---|
| Decision made under the lock | Yes | Yes | No: the decision can go stale while the lock is awaited, leaving a key silently on stale config |
| HTTP action on a no-op key during the batch | 409 for the whole batch, which can last up to the stop deadlines of the other apps' instances | 409 only while the decision runs (no awaits between acquire and release beyond the decision) | 409 never |
| Departure from parent D6 | Yes; needs an Addendum entry | No; D6 holds as written | Contradicts D6 |
| Code shape in `apply_changes` | One `AsyncExitStack` over all keys | One exit context per key, closed for no-op keys after deciding | Today's shape |
| Deadlock risk | None (sorted acquisition) | None (sorted acquisition; an early release can't introduce a cycle) | None |

**Recommendation:** R, because it keeps the decision under the lock, matches D6 as ratified, and doesn't
make an untouched app's buttons answer 409 while other apps stop. The extra cost is per-key release
bookkeeping in one method.
**Pick H instead if** releasing locks out of order inside the batch feels riskier than a 409 window
users rarely hit. **Pick P instead if** never: it reintroduces the gap D6 closes.
**Reversibility:** easy (local to `apply_changes`)
**Ratified:** Chose releasing a no-op key's lock as soon as it is decided over holding every lock through the batch or pre-filtering, to keep the decision under the lock without a batch-long 409 on untouched keys, accepting per-key release bookkeeping in `apply_changes`, and (sketch challenge, Finding 2) that a batch can wait behind an in-flight HTTP action on a key whose plan comes out empty, holding its earlier restart keys and `_change_event_lock` meanwhile. The wait lasts up to the stop and startup deadlines of the action holding each contended key, and adds up across keys (ship-time challenge, Finding 3).

### D2: How does the gate report a refusal before #3111 gives refusals an outcome?

Supersedes parent D12's "a refused path with no response channel logs one ERROR", for the time until
#3111 lands. Until then, an HTTP request that touches a flagged index keeps today's response, a 500
`ACTION_FAILED` from `_raise_if_target_failed` (`src/hassette/web/routes/apps.py`), because a flagged
index reports FAILED. That response doesn't say why.

**Deciding factor:** every refusal is named exactly once (Posture: no silent states), without building
#3111's outcome type here.

| | L: The gate logs one ERROR on every path and returns without raising (issue body) | X: The gate raises a typed refusal that each caller catches and logs | N: Log only on paths with no response channel (D12's wording) |
|---|---|---|---|
| Refusal named on file-watcher, reconcile and autostart paths | Yes | Yes, once each caller handles it | Yes |
| Refusal named on HTTP paths | Yes, in the log (the 500 still says only "failed") | Yes, in the log; the route could map it, but that is #3111's work | No: a 500 with no named cause |
| Duplicate ERRORs | None: returning keeps `start_instance`'s, `reload_instance`'s and `create_one`'s `except Exception` handlers quiet | Risk: every `except Exception` caller must special-case it, as they already do for `AppBlockedError` | None |
| Work moved later by #3111 | Move the log from the gate to the callers with no response channel | Map the exception to an outcome; the special-casing stays | Add HTTP naming |
| Scope | Smallest | Reaches into #3111's response contract | Small, but leaves a silent state |

**Recommendation:** L, because it names every refusal once with the least code. #3111 then replaces it
cleanly with a returned outcome.
**Pick X instead if** you want #3111 to inherit a refusal exception rather than a log line. **Pick N
instead if** an unnamed 500 for the few weeks before #3111 is acceptable.
**Reversibility:** easy (#3111 replaces it either way)
**Ratified:** Chose logging one ERROR at the gate on every path and returning without raising over a typed refusal exception or logging only on no-channel paths, to name every refusal exactly once with the least code, accepting that HTTP callers see the refusal only in the log until #3111. At the sketch challenge, also accepted that the gate keys on `(app_key, index)` only: a config edit that moves a flagged instance's name to another index or app creates a live instance that shares Bus/Scheduler owner registries with the zombie until hassette restarts (Finding 3), and a partly flagged app's module is still re-imported for its healthy siblings while the zombie runs the old class until restart (Finding 4).

## Assumed

- **Contention split (parent D6), already in place.** An HTTP action on a busy key gets 409 from
  `_require_no_action_in_progress`, over `AppKeyLock.busy`, which counts both the holder and the
  waiters. Internal reloads and config changes wait for the lock. Kept unchanged. Evidence:
  `src/hassette/web/routes/apps.py:109`, `src/hassette/core/app_key_lock.py:21`.
- **Only `apply_changes` decides outside the lock.** `reload_app`, `reload_instance`, `start_app` and
  `start_instance` already re-resolve their inputs under it. Evidence:
  `src/hassette/core/app_lifecycle_start_stop.py` (`start_app`'s post-lock re-fetch, `reload_app`),
  `src/hassette/core/app_lifecycle_changes.py:108-117`.
- **The gate reads only the registry flag, not the `TeardownReport` (parent D12, option H).**
  - The flag is set in the `settle_*` methods before the lock is released, so the gate sees a stop
    earlier in the same batch that left work running.
  - A stop that fails without flagging (timed out with nothing left running, or `on_shutdown` raised)
    stays reloadable. `_stop_for_restart` continuing past it is intentional.
  - Evidence: `src/hassette/core/app_lifecycle_instances.py` (`flag_instance_needs_restart`) and spec
    138.
- **Every instance-creating path passes through one of the two funnels.**
  - `_start_app_unlocked` calls `AppFactory.create_instances`, which serves app start, whole-app
    reload, autostart (including `apply_changes`'s `new_apps` loop) and whole-app restarts.
  - `_create_instance_unlocked` serves instance start, instance reload and per-index restarts.
  - Evidence: `src/hassette/core/app_lifecycle_start_stop.py:88`, `:302`; `app_lifecycle_changes.py:207-232`.
- **A whole-app start with one flagged index still starts its siblings (parent D4).** The factory
  already tracks `live_indices` per call; flagged indices join the skip set. Evidence:
  `src/hassette/core/app_factory.py:72-130`.
- **The autostart reads in `apply_changes` can't go stale while a key lock is awaited.**
  - The `new_apps` loop and `_should_restart` read `autostart`, which comes only from the manifest.
  - In production, manifests change only in `refresh_config`, which `handle_change_event` calls under
    `_change_event_lock`. `apply_changes` is reached only from `_reconcile_changes`, whose callers hold
    that same lock.
  - `AppHandler.apply_changes` is an unlocked delegate with only test callers.
  - `start_apps`, the boot path, reads `autostart_manifests` before each `start_app` waits, and
    `start_app` doesn't re-check `autostart` under the lock. That race is pre-existing, unchanged here,
    and accepted.
  - Evidence: `app_lifecycle_changes.py:248-299`, `:335`, `:376-377`;
    `src/hassette/core/app_lifecycle_service.py:239-241`.
- **A flagged-only app reads as dormant.** `app_key in self.registry` counts running instances only,
  so `should_auto_reconcile` is false unless autostart is true. With autostart true, every
  `reimport_apps`/`reload_apps` save re-decides the app and logs the refusal again. With autostart
  false, the app is skipped at DEBUG and never reaches the gate. This is intended: an autostart=false
  app is started only by an explicit start from the UI, the HTTP API or the CLI, never by a config or
  file change, so a needs-restart record doesn't make it reconcilable (sketch challenge, Finding 6).
  Evidence: `app_lifecycle_service.py:239-241`, `app_registry.py:268`.
- **Needs-restart records never exist at boot.** They live only in process memory (`AppRegistry`, parent
  D11), so the boot `start_apps` path never meets a flagged index. Evidence: `app_registry.py:79`.
- **D4 and the "no silent states" rule apply** (parent Breakdown, "Applies to all"). No wire enum or
  payload changes, so no compat ignore entries.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**

- The refusal formatter is `AppRegistry.refusal_for(app_key, index) -> str | None`, not a module-level function beside `NeedsRestartRecord`. `app_registry` imports `app_factory` at module level, so the factory can't import a function back from `app_registry`, while both funnels already hold the registry. It folds the flagged lookup and the message into one call, and since the registry knows the key and index, no caller can pair a record with the wrong ones. `get_needs_restart` stays, for `resolve_instance_info` and for #3111's structured outcome. (Ship-time challenge, Finding 4, side B.)
- `AppFactory.create_instances` returns before `load_class` whenever no configured index is left to create: all flagged, a mix of flagged and live, or all live. The ledger names only the all-flagged case, but in each there is nothing to create, and the all-live case's `load_class` call was a cached read whose result was discarded (`force_reload` is already dropped when any instance is live). So a class-load failure is always recorded against `to_create[0]`. (Ship-time challenge, Finding 2.)
- Restarts are stopped and created in sorted key order. The buckets are frozensets, so the old order was set iteration, not a meaningful list order.
- `_start_for_restart` still resolves the manifest from the registry; only its comment changed, since the plan is now made under the lock.
- The lock-scope unit tests (`TestApplyChangesLockScope`) also pass against the pre-change code: they pin D1's release behavior against the hold-every-lock alternative rather than reproduce a bug. The two integration tests for #1689's gaps fail on the pre-change code.
- Spec 138 KI-003 stays open with an updated trigger: a STOPPING event sent before a fast teardown flags its index can be dispatched to WS after the flag is set, so it still carries the flag.
