# Design: The app registry owns app status transitions

**Date:** 2026-11-13
**Status:** built
**Mode:** sketch
**Issues:** #4092
**Prior art:** `design/research/2026-11-13-framework-timeline/structural-gaps.md` (Gap 1: the Prefect, Airflow and HA `force_update` claims in D1–D3) and `peer-check.md` beside it, copied from commit `f1cf5699` on the `3678` branch; `design/research/2026-11-13-unsafe-teardown-restart/prior-art.md` (needs-restart, D6)

## Summary

No single component owns app instance status. `AppRegistry` (`src/hassette/core/app_registry.py`) stores only RUNNING or FAILED, and it is written from two places: `AppFactory` (`core/app_factory.py`, sync) and the lifecycle mixins (`core/app_lifecycle_start_stop.py`, `core/app_lifecycle_instances.py`). It never knows the previous status and sends nothing. Each lifecycle site builds its own `HassetteAppStateEvent` with a hand-picked `previous_status`, which is often missing or a literal. Create-time failures (which the factory records silently) reach the UI only through a loop that re-sends every current failure on each start (`app_lifecycle_start_stop.py`, the `get_failed_instance_infos` loop in `_start_app_unlocked`).

The change makes the registry the one writer of app instance status and the one source of the from-state:

- **`AppRegistry.set_status(app_key, instance_name, to, *, app=None, error=None, needs_restart=None) -> StatusChange | None`** lives in `app_registry.py`. This is the only place its signature is stated. It reads the from-state from the entry, applies the write, and returns a frozen `StatusChange`, or `None` when nothing changed. Change detection follows D5, missing entries follow D3, and flagged entries follow D6. **`None` means no event is owed.** There are three cases. Nothing changed (D5). A registration onto a missing entry, which still creates the NOT_STARTED entry (D4). A rejected write onto a missing entry (D3) or onto a flagged entry (D6), which changes nothing. `StatusChange` is also defined in `app_registry.py` and carries app_key, instance_name, class_name, from, to and error. Its `class_name` comes from `app` when one is given, otherwise from the loaded manifest for `app_key`, otherwise `"Unknown"`, the same fallback `_info_from_entry` uses. `InstanceEntry.status` widens to every `ResourceStatus` an app goes through: NOT_STARTED, STARTING, RUNNING, STOPPING and FAILED. An entry holds its `App` only while the status is NOT_STARTED, STARTING, RUNNING or STOPPING. A FAILED entry holds no App and can carry `needs_restart` (D6). STOPPED removes the entry (D3).
- **`register_app`, `record_failure`, `unregister_app`, `flag_needs_restart` and `NeedsRestartRecord` are deleted.** `get_needs_restart` returns `NeedsRestartInfo | None`, read from the entry. `set_status` writes `_instances` directly, and their test callers migrate. Bulk removal stops writing directly: `prune_stale_failed` becomes a read that returns the names of stale, unflagged failure entries, and the lifecycle method writes STOPPED for each one.
- **One write path.** `AppInstanceLifecycleMixin` (`app_lifecycle_instances.py`) gets a single async method, `set_app_status(app_key, instance_name, to, *, app=None, error=None, needs_restart=None)`. Its parameters are `set_status`'s. The event's exception fields come from `error`, and its identity and class name come from the returned `StatusChange`, so a create-time failure with no `App` needs nothing extra. It calls `registry.set_status` and emits the returned change, and does nothing for `None`. Lifecycle code calls only that method, never `registry.set_status` directly (D1). It replaces `emit_app_state_change` and `send_outcome_event`. The event is built with a new `HassetteAppStateEvent.from_change` (`events/hassette.py`), which replaces `from_app` and `from_instance_info`. As `send_outcome_event` does today, a failed send is logged and not raised. The registry gets no bus dependency. The sync settle helpers `settle_failed_init` and `settle_failed_stop` become async so they can call it.
- **The re-send loop is deleted** (D2), and so is `_emit_failure_event_if_present`. Each create-time failure becomes an ordinary transition event (D1).

Out of scope: #1446's status projector, #3678's history rows, the App resource's own lifecycle status (D8), and any transition-legality table (see Posture).

The paths that write status today, all of which go through `set_app_status` afterwards except `clear_all` (D7):

- In `AppFactory.create_instances` and `create_single_instance`: registration, a class-load failure, and a failure in config validation or the constructor (D1). `create_single_instance` returns `App | Exception`, and `create_instances` returns `dict[str, App | Exception]`. For a class-load failure, the factory still picks the one representative name and returns the error under it alone. The factory keeps recording per-name `outcomes` as it does today. Its callers (`_start_app_unlocked`, `_create_instance_unlocked`) write each result through `set_app_status`: NOT_STARTED with `app=` for an App, FAILED with `error=` for an exception.
- In `_create_instance_unlocked`: a class-load failure.
- The NOT_STARTED events sent for newly created instances in `_start_app_unlocked` and `_create_instance_unlocked`. These are replaced by registration writes, which emit only when the name had an entry (D4).
- In `initialize_instance`: STARTING (new, per D4) and RUNNING.
- In `shutdown_instances.stop_one`: STOPPING.
- In `shutdown_instance`, `settle_raised_shutdown`, `settle_failed_init` and `settle_failed_stop`: STOPPED and FAILED. These write directly over the live STARTING or STOPPING entry, with no unregister first, so the from-state comes from the entry (STARTING → FAILED for a failed init, STOPPING → FAILED or STOPPED for a stop). The FAILED write is what drops the `App` reference, and STOPPED removes the entry. The `finally` debug-capture check (`registry.get(...) is not inst`) keeps working, because neither leaves `inst` registered.
- In `_discard_failed_instances` and the `prune_stale_failed` → `_emit_discarded_entry_events` path: FAILED → STOPPED for a discarded failure entry. Both select unflagged entries only (D6).
- In the `_create_instance_unlocked` exception handler: the phantom-instance FAILED write.
- In `shutdown_all`: `clear_all()`. This is not a status write: it stays a raw reset outside `set_status` (D7).

## Posture

- **Failure handling:** no retries and no recovery machinery. A failed event send is logged at ERROR and not raised, as `send_outcome_event` behaves today. An odd sequence gets a DEBUG log, and there is no transition table.
- **Compatibility:** break freely. The project is pre-V1, and the registry's mutators are internal to the framework, so their test callers migrate in this change. The wire payload `AppStatusChangedData` keeps its shape.
- **Scope:** minimal: the issue's acceptance criteria. It leaves out the #1446 projector, the #3678 history rows, and the App resource's own lifecycle.
- **Rollout:** ships outright; no flag or migration.
- **Hardening:** project defaults.
- **Altitude:** build; one session builds it from the files cited here.

## Decisions

### D1: How do the factory's create-time status writes reach an event?

**Situation:** `AppFactory.create_instances` and `create_single_instance` are sync. They call `register_app` on success and `record_failure` on a class-load, config-validation or constructor failure. Sync code can't await an event send, so these writes go out silently, and the re-send loop exists to cover for that. When `set_status` returns a change, someone has to emit it.

**Deciding factor:** one layer writes app status, so no write can skip its event.

| | A: Factory returns results; the lifecycle writes status | B: Factory calls `set_status` and returns the changes for the caller to emit | C: Factory becomes async and writes and emits itself |
|---|---|---|---|
| Who writes status | lifecycle mixins only | factory and lifecycle | factory and lifecycle |
| Can a write miss its event? | no: the writer emits | yes, if a caller drops the returned list | no |
| Factory's role | builds instances and reports failures; no registry writes | builds and writes | builds, writes and emits; gains a bus dependency |
| Diff | `create_instances`/`create_single_instance` return a per-name result (App or exception) instead of `set[str]`/`bool`; callers change | return types change; callers change | every caller and the factory's tests become async |
| Write sites outside the factory | each goes through one lifecycle method that writes and emits | same | same |
| Peer fit | Prefect: only the orchestration layer sets state | Airflow-style per-site handling, missed twice upstream | — |

**Recommendation:** A, because it leaves exactly one layer that writes status and emits for every write. The factory goes back to constructing apps. For a class-load failure, the factory still picks the one representative name, returns the error under it, and leaves the write to its caller.
**Inside the lifecycle:** every status write goes through one async mixin method that calls `set_status` and emits, so a site can't take the change and drop it. That holds for bulk prune too: the method loops one write per name.
**Pick B instead if** the factory has to stay the registration point for a reason the scan didn't find. **Pick C instead if** the factory is due to become async anyway.
**Reversibility:** easy (internal signatures).
**Ratified:** Chose A (the factory returns a per-name result, and the lifecycle mixins write status through one async method that writes and emits) over having the factory return changes or go async, so that no status write can skip its event. Accepted: the factory's return types and callers change, and the two sync settle helpers become async.

### D2: With the re-send loop deleted, how does the UI learn about create-time failures?

**Situation:** The issue proposes a snapshot push to replace the re-send loop. Under D1, though, every create-time failure becomes a real FAILED transition with its own event, so the case the loop covered no longer exists. The only things left are failures that haven't changed. The UI already received those through their own events, or picks them up on reconnect, where `handleWsConnected` in `frontend/src/state/store.ts` clears `appStatus` and the manifests are refetched. The existing `apps_changed` signal can't serve as a snapshot: the frontend's `appStatus` cache takes priority over refetched manifest data (`instanceLiveStatus` in `utils/app-data.ts`).

**Deciding factor:** the fewest moving parts that still keep the UI correct.

| | A: No push; transition events are enough | B: New WS snapshot message; the frontend replaces `appStatus` wholesale | C: Send `apps_changed`, and have the frontend also clear `appStatus` on it |
|---|---|---|---|
| UI sees create-time failures | yes, as FAILED events | yes | yes |
| New protocol or frontend work | none | new message type, wire model, validator regen, store action | frontend handler change |
| Meets the AC "not a re-sent state event" | yes; they arrive as real changes | yes, literally | yes |
| Peer fit | HA: a state that hasn't changed sends no event | HA's `force_update` path | — |

**Recommendation:** A, because once D1 makes create-time failures real changes, there is nothing left for a push to carry. The PR will say that this AC is met by real transitions rather than a snapshot.
**Pick B instead if** a case turns up where a client misses a change without disconnecting. **Pick C instead if** we want a cheap safety-net resync after each load pass.
**Reversibility:** easy (a push can be added later on its own).
**Ratified:** Chose A (no snapshot push; create-time failures arrive as real FAILED transitions) over a new snapshot message or an `apps_changed` cache clear, to avoid new protocol and frontend work, accepting that the PR has to explain why the snapshot AC is met by transitions, and that a FAILED event whose send raises (logged at ERROR) leaves that UI row stale until the app's next start or a WS reconnect.

### D3: What does a clean stop leave in the registry, and what from-state does a restart read?

**Situation:** A clean stop calls `unregister_app` today, which removes the entry. For a configured name with no entry, `build_manifest_info` shows a synthetic STOPPED. When the instance is next started, `set_status` finds no entry, so the restart reports NOT_STARTED → STARTING instead of STOPPED → STARTING.

**Deciding factor:** the registry tracks live instances, and each start creates a new `App` object.

| | A: STOPPED removes the entry; a missing entry reads as NOT_STARTED | B: Keep a STOPPED entry (no App) after a clean stop | C: Remove the entry, but remember stopped names in a separate set so they read as STOPPED |
|---|---|---|---|
| Restart's from-state | NOT_STARTED (a new instance) | STOPPED | STOPPED |
| Readers that treat "tracked" as running-or-failed (`tracked_names`, `_stop_targets`, `_record_untracked_stops`, `prune_stale_failed`, display of orphans) | unchanged | all need to ignore STOPPED entries; a stopped orphan would otherwise be displayed forever | unchanged, plus a new set to clear |
| New state | none | entry lifetime changes | a second collection |
| Peer fit | Prefect: each run begins in its initial state | — | — |
| Writes onto a missing entry (late writers racing exit or a concurrent stop) | accepts NOT_STARTED and FAILED only; anything else returns `None` with a DEBUG log | the STOPPED entry is there to compare against | the set is there to compare against |

**Recommendation:** A, because every start builds a new `App`, and a new instance's life starts at NOT_STARTED, as Prefect's new runs start in their initial state. It also leaves every entry reader untouched. #3678's history can still show the earlier stop, since that row's own STOPPED event came just before.
**Missing-entry rule:** a missing entry accepts only NOT_STARTED (registration) and FAILED (a create-time failure, D1). Any other write to a missing entry (STARTING, RUNNING, STOPPING, STOPPED) returns `None` with a DEBUG log. That way a late writer that races process exit or a concurrent stop can't create a ghost entry or report a bogus NOT_STARTED → STOPPED.
**Pick B instead if** #3678 needs STOPPED → STARTING rows to reconstruct restarts. **Pick C instead if** that need shows up but B's churn for every reader is too much.
**Reversibility:** easy.
**Ratified:** Chose A (STOPPED removes the entry, a missing entry reads as NOT_STARTED, and a missing entry accepts only NOT_STARTED and FAILED) over keeping STOPPED entries or a separate set of stopped names, to leave every entry reader untouched, treat each start as a new instance, and define `set_status` for late writers. Accepted: a restart reports NOT_STARTED → STARTING, and a second FAILED with a new error in an exit race still emits.

### D4: What does registration record, and when does STARTING begin?

**Situation:** `register_app` stores RUNNING as soon as the instance is constructed, before `on_initialize` runs. `start_app` constructs every instance first and then initializes them one by one, so a sibling can show RUNNING for some time before it starts. The issue's acceptance criteria make STARTING a real registry state with its own event.

**Deciding factor:** the registry reports what is actually happening.

| | A: Registration records NOT_STARTED; STARTING is set right before `inst.initialize()` | B: Registration records STARTING |
|---|---|---|
| Accurate while siblings wait | yes: NOT_STARTED until its own init begins | no: STARTING while it waits |
| Event on registration | none on a missing entry (it already reads as NOT_STARTED); FAILED → NOT_STARTED on a retry over an unflagged failure entry, which clears the stale failure in the UI | NOT_STARTED → STARTING |
| Matches the App resource's own status | yes (the App is NOT_STARTED until initialize) | no |

**Recommendation:** A, because it reports each instance's real phase and matches the App's own status. The STARTING transition is written and sent before `initialize_instance` opens `anyio.fail_after(self.startup_timeout)`, so the event send never counts against the app's startup timeout. Snapshots report the entry's status for each instance: `_info_from_entry` reads `entry.status` for live entries rather than `app.status`. The app-level status is unchanged: `build_manifest_info` still counts any instance that hasn't failed as running, so an app row reads RUNNING while one of its instances is STARTING, because `AppStatus` has no STARTING member. A configured name with no entry keeps its synthetic STOPPED row.
**Known effect:** registering onto a missing entry sends no event. After a clean stop or the stop half of a reload, queued siblings therefore keep showing STOPPED until their own STARTING arrives.
**Known limitation:** if a cancellation lands between a status write and its event, or before init finishes, the entry and the UI stay at the last status written (for example, a STARTING entry left by a cancelled init). In practice that is process exit, and `clear_all` follows straight after. Today's code is equally wrong in that case: it reads RUNNING.
**Pick B instead if** the UI needs an event the moment an instance is constructed.
**Reversibility:** easy.
**Ratified:** Chose A (registration records NOT_STARTED; STARTING is written and sent right before `initialize_instance` opens the startup timeout) over registering as STARTING, so each instance reports its real phase. Accepted: registration onto a missing entry sends no event, so queued siblings show STOPPED after a stop until their own STARTING. A retry over an unflagged failure emits FAILED → NOT_STARTED. The app-level row stays RUNNING while an instance is STARTING, and a cancellation at exit leaves the last status written.

### D5: Does FAILED → FAILED with a new error count as a change?

**Situation:** `start_app` on an app that has already failed overwrites the failure entry with a new error, without any stop in between. If only the status were compared, that would return `None`, and the UI would keep showing the old exception.

**Deciding factor:** the UI and the future history table see every new failure.

| | A: Compare the status only | B: A change in status, or a different error object, is a change |
|---|---|---|
| UI exception after a repeated failure | stale | current |
| Number of events | fewer | one per real failure |
| Matches issue #4092's proposed shape | no | yes ("returns `None` when nothing changed", including the error) |

**Recommendation:** B, because each failure is a separate occurrence the UI should show. The error is compared by identity, so the same exception written twice still returns `None`.
**Pick A instead if** repeated failures turn out to be noisy in practice.
**Reversibility:** easy.
**Ratified:** Chose B (a change of status or a different error object counts as a change) over comparing status alone, so the UI always shows the current failure, accepting one event for every real failure.

### D6: Where does the needs-restart condition live once the registry owns status?

**Situation:** `flag_needs_restart` keeps a separate `_needs_restart` record per name. `_combine_instance_info` lays it over the entry, so the resolved status reads FAILED. The record survives `unregister_app`, and only `clear_all` clears it. Every site that flags it (`settle_raised_shutdown`, `settle_failed_init`, `settle_failed_stop`) writes FAILED first. `_discard_failed_instances` and `prune_stale_failed` still remove a flagged name's FAILED entry, and the overlay keeps the name looking FAILED after that. Under `set_status`, the overlay is the one place where the stored entry and the reported status disagree. The removal would read FAILED → STOPPED while the instance still shows FAILED. The mechanism exists (specs 138–140) so that a replacement instance can't be created alongside an old instance's leftover work. That work shares the replacement's Bus/Scheduler owner id, so a late teardown could remove the replacement's registrations.

**Deciding factor:** one stored truth per instance, matching the closest peer.

| | A: Fold it into the entry (HA's `FAILED_UNLOAD`) | B: Keep the overlay; discard and prune skip flagged names | C: Remove the mechanism (log and proceed) |
|---|---|---|---|
| Stored and reported status agree | yes; the entry is FAILED with `needs_restart` set | yes, once the skips are in, but two structures still have to agree | yes |
| Reload/start refusal and 409 | kept | kept | gone |
| Owner-id collision guard (specs 138/139) | kept | kept | gone: leftover work can remove a replacement's registrations |
| Wire, UI, CLI | unchanged (`status: failed` + `needs_restart`) | unchanged | the badge, column and error are removed |
| Diff | delete `_needs_restart` and the overlay branch in `_combine_instance_info`; the flag becomes a parameter of the FAILED `set_status` write, and `set_status` keeps the original flag and refuses any non-FAILED write to a flagged entry | two filters | reverts three specs; user-visible; changelog |
| Peer fit | HA core: a non-recoverable state on the entry that blocks setup and reload | none: no peer keeps a separate record that outlives the instance | NetDaemon, Node-RED, AppDaemon |
| Scope under the posture | within #4092: it is part of who owns status | within #4092 | a behavior change of its own, outside #4092 |

**Recommendation:** A, because it removes the only second holder of instance status, the same way HA does, while keeping the guard against the failure specs 138 and 139 were written for. Evidence: `design/research/2026-11-13-unsafe-teardown-restart/prior-art.md`.

**Write contract:**
- **Flagging is part of the FAILED write.** It is `set_status(app_key, name, FAILED, error=..., needs_restart=NeedsRestartInfo(...))`. The separate `flag_needs_restart` mutator is removed, and with it the "flagging isn't a transition" special case and the rule that the flag must follow the FAILED write.
- **`set_status` owns the rule that a flagged entry is protected.** A FAILED write over a flagged entry keeps the original flag (the first flag stands) and replaces the stored error. It is still a change under D5 when the error differs. Any other write to a flagged entry returns `None` and logs a WARNING, since no normal path should attempt one. Only `clear_all` removes a flagged entry. The normal paths never try: start, reload and stop of a flagged name are refused before they write (`refusal_reason`), and the `prune_stale_failed` read and `_discard_failed_instances` select unflagged entries only. That way the WARNING marks a real bug, not routine traffic.
- **"Newly flagged" is read before the write.** A FAILED write's `StatusChange` doesn't say whether this write flagged the name. Callers that need it (`record_flagged_outcome` chooses between a `failed(needs_restart=True)` outcome and a refusal) check `get_needs_restart` before writing, the way `flag_needs_restart`'s boolean is used today.
- **Every reader of `_needs_restart` derives from the entries instead.** These are `get_needs_restart`, `refusal_reason`, `tracked_names`, `flagged_app_keys` (read by `database_retention.py`), `get_snapshot`, `build_orphaned_flag_info`, `build_manifest_info` and `_combine_instance_info`, whose overlay branch is deleted.
- **No `class_name` on the entry.** A flagged instance whose app leaves the config shows its class as "Unknown" until restart.

**Pick B instead if** the change should stay as small as possible and the record's separate lifetime has to be kept. **Pick C instead if** the loud-failure posture of spec 138 is itself in question. In that case file it as its own issue rather than folding it into #4092.
**Reversibility:** easy for A and B. C is hard to walk back once users stop seeing the refusal.
**Ratified:** Chose A (fold needs-restart into the FAILED instance entry, as HA does with `FAILED_UNLOAD`, and delete the separate record and the overlay; the flag is a parameter of the FAILED `set_status` write, which keeps it; normal paths never attempt to write to a flagged entry; "newly flagged" is read before the write) over keeping the overlay or removing the mechanism, so each instance has one stored truth and the protection rule lives in the single writer. Accepted: a flagged orphan's class shows as "Unknown" until restart.

### D7: Does `clear_all()` at process exit send events?

**Situation:** `shutdown_all` stops every running instance; each stop sends its own events through `shutdown_instance`. It then calls `clear_all()`, which silently drops what is left: failure entries (flagged ones included, per D6) and blocked apps. This happens at process exit, and `testing/_reset.py` also calls it.

**Deciding factor:** don't emit events no one can act on.

**Recommendation:** send nothing. `clear_all` stays a raw reset outside `set_status`, and its docstring and the PR say why: it runs only at process exit and on test reset, after every instance registered when `shutdown_all` began has sent its own STOPPED or FAILED. An instance a runtime start registers after that point is cleared without an event, because `shutdown_all` takes its list once and holds no app-key lock. This meets the AC's "named in the PR with the reason" branch.
**Pick "emit STOPPED for each dropped failure entry" instead if** #3678 needs a closing history row for failures that are still standing at exit.
**Reversibility:** easy.
**Ratified:** Chose to send nothing from `clear_all` (a raw reset outside `set_status`, with the reason stated in its docstring and the PR) over a closing STOPPED per dropped entry, because no one can act on events at exit, accepting that failures still standing at exit get no closing event.

### D8: Does the App resource's own `status` setter defer to the registry?

**Situation:** Each `App` also tracks its own status through `LifecycleMixin.status` (`resources/mixins.py`) and the `handle_*` functions in `resources/lifecycle.py`. Those functions send service-status events, which `RuntimeQueryService` filters out for apps. After this change there are still two holders. The registry's status is the one reported for app instances; the App's is the resource's internal lifecycle.

**Deciding factor:** the minimal scope agreed in the posture.

| | A: Keep them separate, and file the second holder as a debt issue | B: The App's setter calls `set_status` |
|---|---|---|
| Scope | as the issue states | reaches into `resources/` and every resource's lifecycle |
| Sync/async mismatch | none | the setter is sync, so it can't emit |
| Two holders remain | yes, written down | no |

**Recommendation:** A, as the Gap 1 research brief suggests: the issue's acceptance criteria cover app instance status as the registry reports it. File a follow-up issue for the second holder.
**Pick B instead if** the history table (#3678) turns out to need the App's own transitions, such as CRASHED.
**Reversibility:** easy.
**Ratified:** Chose A (keep the App resource's own status separate, and file the second holder as a debt issue) over having the setter call `set_status`, to keep within #4092's scope, accepting that two holders remain until that issue is done.

## Assumed

- Gap 2 of the brief (one owner for the connection state) has landed, so nothing blocks this change. Evidence: #4091 is closed; PR #4102 merged as `af1ccd7b`.
- Every site that flags needs-restart today writes FAILED in the same sync step just before it flags, so folding the flag into that FAILED write (D6) changes no ordering. Only the source of the "newly flagged" boolean changes. Evidence: `app_lifecycle_instances.py` `settle_raised_shutdown` (record_failure, then flag), `settle_failed_init`, `settle_failed_stop`.
- The only production consumer of `HassetteAppStateEvent` is `RuntimeQueryService.on_app_state_changed`, which overwrites the UI's cached status. Evidence: `core/runtime_query_service.py` `on_app_state_changed`; `frontend/src/hooks/use-websocket.ts` case `app_status_changed`.
- On reconnect, the frontend clears `appStatus` and refetches. Evidence: `frontend/src/state/store.ts` `handleWsConnected`.
- `InstanceEntry.is_running` means "holds a live App", not "status is RUNNING". Evidence: `app_registry.py` `InstanceEntry.is_running`; `get_running_apps` relies on it.
- The registry has no bus dependency, and gets none. Evidence: `app_registry.py` imports.
- `testing/_simulation.py` builds `HassetteAppStateEvent`s for the test harness and moves to `from_change` too. Evidence: `testing/_simulation.py` event builders.

## Build

- [x] Implementation and tests committed
- [x] Docs (bus/methods.md on_app_state_changed statuses, operating/index.md flagged-stop wording, core REVIEW.md, .claude test rules)
- [x] Ship-time challenge

**Calls made during the build:**
- `prune_stale_failed` is renamed `stale_failed_names`: under the Summary it only reads, and a read named "prune" misleads.
- `StatusChange.previous` is `ResourceStatus | None`: the test harness's `simulate_app_state_changed` has no known previous status; `set_status` always fills it.
- `settle_raised_shutdown` loses its `is_init_failure` parameter: it only chose a hand-written previous status, which now comes from the entry.
- `_create_instance_unlocked`'s init-started/skip-hooks branch is removed: nothing between registration and init can raise any more (registration writes never send, and send failures are caught).
- `set_status` raises `ValueError` for FAILED without `error` and NOT_STARTED without `app` (programmer misuse), and drops a live-status write onto an entry with no App, logged at DEBUG.
- The factory tests' mock registry is spec'd and its `set_status` raises, pinning D1 (the factory writes nothing).
- `get_running_apps` is renamed `get_live_apps` and `InstanceEntry.is_running` is renamed `holds_app`: with entries carrying NOT_STARTED, STARTING and STOPPING, "running" misread the filter, which is "holds its App".
- `_record_created` re-checks the needs-restart flag right before each NOT_STARTED write and records a flagged name as refused, registering and initializing only the rest: process exit flags names without the app-key lock, and an earlier name's event send is an `await` it can land in, after which the registry would drop the write and the App would run unregistered.
- `fail_needs_restart` takes `flag_reason`, `shutdown_outcome` and `outcome_reason` as keywords: two near-identical reason strings passed positionally invited a swap.
- D8's follow-up issue is #4113.
- The PR is titled `feat!:` and ends with one `BREAKING CHANGE:` footer: `HassetteAppStateEvent.from_app` and `from_instance_info` are removed (build events through the `hassette.testing` simulate helpers instead), instances now emit STARTING, and NOT_STARTED is no longer sent on a first start, only on a retry over a failed instance. The commits are plain `feat:`/`fix:`, and the squash title is what reaches the changelog.
- Process exit stays lock-free: `shutdown_all`'s docstring records, as one known limitation, that its races with in-flight lifecycle work can leave wrong statuses between exit and `clear_all` (a late RUNNING after STOPPING, a stale STOPPED removing a same-name replacement, a FAILED entry left after `clear_all`). HA config entries, NetDaemon and pyscript stop the same way, and none guards late status writes (design/research/2026-11-14-exit-vs-inflight-lifecycle/prior-art.md).
- `initialize_instance` skips `initialize()` for an instance exit reached first, checking right before the STARTING write: a flagged name is refused (so the registry logs no refused-write WARNING), and one no longer NOT_STARTED (STOPPING, or removed) fails with "stopped before it was initialized". The check reads `AppRegistry.get_status`, so `set_app_status` still returns nothing.
- A FAILED write that adds the needs-restart flag is a change even when the error object is unchanged, so the flag always reaches an event.
- `needs_restart` rides on `StatusChange` and `HassetteAppStateEvent`'s payload (a FAILED change carries the entry's flag after the write), and `RuntimeQueryService.on_app_state_changed` reads it from the event instead of the registry, so an earlier event handled after a flag lands no longer shows it. `NeedsRestartInfo` is exported from `hassette.schemas`, and `simulate_app_state_changed` takes `needs_restart=`.
- D2's accepted limitation covers every status event, not only FAILED: a send that raises (logged at ERROR) leaves the UI row at its previous status until the instance's next transition or a WS reconnect. The underlying fix, ordering the REST snapshot against WS deltas, is filed with the server-owned rollup as #4147.
- `is_failed_info` reads `info.status is FAILED` instead of inferring failure from `error`/`needs_restart`.
- The frontend's `appLiveStatus` reports "degraded" when a failed instance sits beside any instance that is neither failed nor stopped, the server's manifest rollup rule (a "stopped" instance there is an untracked configured name).
