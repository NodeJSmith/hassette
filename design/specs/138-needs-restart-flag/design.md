# Design: Needs-Restart Flag After a Hook Timeout

**Date:** 2026-10-27
**Status:** ratified
**Mode:** sketch
**Issues:** #3109

## Summary

When a failed or timed-out app init, or any app instance teardown, may leave work running, hassette today reports
the instance STOPPED/FAILED and moves on. A failed init never shuts the instance down. Instead the hand-rolled
`cleanup_failed_instance()` (`src/hassette/core/app_lifecycle_instances.py`) removes listeners and jobs. This change,
item 6 of the milestone ledger `design/specs/134-resource-lifecycle-outcomes/design.md`, does four things:

- **Routes init failure through shutdown.** An instance whose init failed or timed out is shut down under the entry
  deadline. The app's own shutdown hooks are skipped. Its `Bus`/`Scheduler` children still remove listeners and jobs.
- **Redefines `TeardownReport.is_restart_safe`** (`src/hassette/resources/teardown.py`) as "no work may still be
  running".
- **Records needs-restart.** When an instance teardown's report says work may still be running, a needs-restart
  record goes in `AppRegistry` (`src/hassette/core/app_registry.py`). The instance stays FAILED until hassette
  restarts.
- **Surfaces the flag:**
  - wire: `needs_restart` on `AppInstance` and on the WS status event (`wire/src/hassette_wire/apps.py`, `ws.py`;
    added by `RuntimeQueryService`, not by the bus payload), and `needs_restart_count` on `AppSummary`
  - CLI: a column in `hassette app` and a section in `hassette status` (`src/hassette/cli/commands/`)
  - UI: a minimal badge (`frontend/src/`)
  - docs

It also removes `cleanup_failed_instance()` and `failed_instance_cleanup_timeout_seconds`
(`src/hassette/config/models.py`).

GitHub issue #3109 is the detailed work order, combed against the code on 2026-10-27, and lists every file and
reference this touches. Out of scope:
- Refusing to create a replacement over a flagged instance (#3110).
- Typed outcomes for raised, not timed-out, hooks and actions (#3111).
- Sync workers, parallel-mode handlers and scheduler jobs (not covered by the predicate, ledger 134 D18).

Homes for new state and behavior:
- **Needs-restart record:** a keyed map on `AppRegistry`, read only through one `AppRegistry` resolver (D4).
- **Predicate:** `TeardownReport.is_restart_safe`.
- **Hook-skip flag:** see D1.
- **`NeedsRestart` wire model:** `hassette_wire/apps.py`, mirrored on `AppInstanceInfo` (`schemas/app_snapshots.py`).
- **Count:** `AppManifestInfo` / `AppSummary`, mapped in `web/mappers.py`.
- **Walk-away cleanup bound:** a module constant in `app_lifecycle_instances.py`.

## Posture

- **Failure handling:** loud. Every needs-restart or dead-in-place state shows as a status plus one ERROR naming
  the cause (ledger 134 Posture). No retries; recovery is a process restart.
- **Compatibility:**
  - Config may break: hassette is pre-V1. The removed setting is rejected at load like other removed keys, and gets
    a migration note.
  - The wire protects released clients: only optional fields are added, and `client_compat` confirms it.
- **Scope:** the complete issue: API, WS event, CLI, minimal UI badge, docs (`.claude/rules/design-completeness.md`).
- **Rollout:** ships outright; no flag.
- **Hardening:** project defaults.
- **Altitude:** `build`; one session builds it, and the ledger cites files.

## Decisions

### D1: Where does the per-attempt "skip the app's own shutdown hooks" flag live?

**Deciding factor:** one obvious place to look for per-attempt shutdown state, without duplicating the shutdown
body's hook ordering.

| | A: attempt field on `LifecycleMixin`, checked in `Resource._shutdown_body` | B: `App` attribute plus an `App._shutdown_body` override | C: hook-list seam: `Resource._shutdown_body` asks the resource for its user shutdown hooks; `App` returns none while its flag is set |
|---|---|---|---|
| Where a reader finds it | Next to `_shutdown_deadline`, the other per-attempt shutdown state (`resources/mixins.py`) | On `App`, where the apps-only rule lives | Split: a seam on `Resource`, the flag on `App` |
| Reset per attempt | Free: the mixin already resets attempt fields when an attempt ends (`mixins.py`) | Hand-rolled on `App` | Hand-rolled on `App` |
| Duplicated hook ordering | None | Copies `_shutdown_body`'s hooks-then-post-hook-stage order, which already carries a "keep in sync with Service" note (`base.py`) | None |
| Scope leak | `Resource` gains a field only apps set; `Service._shutdown_body` ignores it | None | `Resource` gains a seam only `App` overrides |
| Matches existing patterns | Yes: attempt state set by the operation owner, like the entry deadline (`shutdown_deadline.py`) | No other resource overrides `_shutdown_body` except `Service` | Like `_framework_before_hooks`, a seam subclasses fill |

**Recommendation:** A. The flag is attempt state set by the operation's owner, which is exactly how the entry
deadline already works. The mixin's per-attempt reset comes for free, and the hook ordering isn't duplicated.
**Pick B instead if** keeping every trace of the apps-only rule out of `resources/` matters more than avoiding a
second copy of the shutdown body. **Pick C instead if** a second resource type is expected to want its own
conditional hook list.
**Reversibility:** easy (internal; no public surface)
**Ratified:** Chose an attempt field on `LifecycleMixin` checked in `Resource._shutdown_body` over an `App` override
or a hook-list seam, to keep per-attempt shutdown state in one place with a free reset, accepting a `Resource` field
only apps set.

### D2: What bounds `walk_away_from_instance`'s listener/job cleanup once `failed_instance_cleanup_timeout_seconds` is removed?

**Deciding factor:** keep the protection against a wedged DB worker holding the app-key lock (spec 137) without a
user setting.

**Recommendation:** a fixed module constant in `app_lifecycle_instances.py`, matching ledger 134 D19's fixed
framework caps (the drain cap, the executor join).
**Pick `shutdown_timeout_seconds` instead if** users need to tune it. That couples a framework step to the user-hook
bound. What's left of the entry deadline is always zero here, so that isn't an option.
**Reversibility:** easy
**Ratified:** Chose a fixed module constant over reusing `shutdown_timeout_seconds`, to keep the lock-hang
protection without a setting, accepting that it can't be tuned (user answer, 2026-10-27).

### D3: Which resources skip user shutdown hooks after a failed init?

**Deciding factor:** keep framework cleanup, meaning the children's listener and job removal and the services'
`on_shutdown`, while matching the peer rule at the user-code boundary.

| | A: apps only, per-attempt flag | B: general Resource rule ("own init attempt ran and didn't reach RUNNING") |
|---|---|---|
| Listener/job cleanup | Kept: the flag isn't propagated, and never-initialized `Bus`/`Scheduler` still run `on_shutdown` (`bus.py`, `scheduler.py`) | Kept only with a careful definition; children initialize after the user hooks (`base.py` `_initialize_body`) |
| Framework services | Unaffected | Skip `on_shutdown` after a partial init; needs an audit of every framework `on_shutdown` override |
| Peer fit | HA's rule covers integrations (user code); `App` is the equivalent boundary | Shape of HA/OTP's rule, applied wider than HA does |
| Ledger 134 | D18 as ratified | Widens D18 |

**Recommendation:** A.
**Pick B instead if** framework resources should also stop running teardown after a failed setup and are audited
for it.
**Reversibility:** easy
**Ratified:** Chose apps only with a per-attempt flag over a general Resource rule, to keep children's and services'
framework cleanup, accepting that the skip is opt-in by the caller (user answer, 2026-10-27, after the comb showed
the general rule leaks `Bus`/`Scheduler` cleanup).

Behavior to pin, by its observable outcome rather than by the calls it makes (sketch challenge, Finding 14): after a
failed or timed-out init, the app's DB listener and job rows are retired, and the bus and scheduler hold no listeners
or jobs for its owner. A phantom whose app initialized runs `on_shutdown`. A phantom that never started doesn't (D9).

Also accepting (Finding 12) two cases where `on_shutdown` is skipped even though `on_initialize` completed: an init
that finishes in the few loop turns between its timeout and the shutdown, and a framework child that fails to
initialize after a successful `on_initialize`. Handles opened outside the task bucket stay open until restart.

### D4: What status does a flagged instance show after a stop discards its failure entry, or after its app leaves config?

**Deciding factor:** never show "stopped" while work may still run (ledger 134 Posture: no silent states).

| | A: sticky FAILED | B: status follows the stop |
|---|---|---|
| Matches peers | HA `FAILED_UNLOAD`, systemd `failed` | No |
| UI/CLI truth | FAILED plus `needs_restart` until restart | STOPPED plus a separate badge |
| Code | Status derivation and `_emit_stopped_events` read the record; orphaned rows rendered from it | Less |

**Recommendation:** A.
**Pick B instead if** status must strictly mirror the resource object.
**Reversibility:** easy
**Ratified:** Chose sticky FAILED over a status that follows the stop, to never show "stopped" while work may run,
accepting extra reads of the record in status derivation and stop events (user answer, 2026-10-27).

**Resolver (sketch challenge, Findings 1, 4, 5, 9).** Exactly one `AppRegistry` method combines an index's instance
entry with its needs-restart record and returns the index's effective `AppInstanceInfo`:
- If a record exists, the result is FAILED plus `needs_restart`, whatever the entry says. When the entry is gone,
  the record's `reason` serves as the error.
- If there is no record, the result is the entry as today.

Every reader of per-index state goes through it:
- `get_snapshot`, `build_manifest_info`, `overlay_runtime_state`, `get_failed_instance_infos`
- `_emit_stopped_events`
- `needs_restart_count`, the `AppStatus` tally, and `AppStatusSnapshot.running_count`

No reader combines entry and record on its own.

A live replacement at a flagged index exists only between the #3109 and #3110 merges. #3110 refuses creation over
a flagged index, and no release ships until the milestone is complete. So there is no special case for it: the
record wins. No tests pin interim behavior. The first record at an index stands until restart, with no merge. A later
flag at the same index only logs its own ERROR.

**Ratified:** Chose one registry resolver with record-wins and first-record-stands over per-reader derivation, a
live-status interim rule, or merging re-flags, to give "flagged" one definition, accepting that a replacement created
in the unreleased interim reads FAILED (user answer, 2026-10-27, sketch challenge).

### D5: One predicate or two, and do child shutdown failures count?

**Deciding factor:** one name for one predicate (HA uses one `recoverable`).

| | A: redefine `is_restart_safe` in place | B: keep `is_restart_safe` ("any cause"), add a second predicate |
|---|---|---|
| Names | One | Two near-identical |
| Behavior change | `_on_children_stopped` runs after a child hook that raised but finished | None for existing readers |
| Docs/rules | `internals/lifecycle.md`, `.claude/rules/resource-lifecycle.md` and the docstrings change with it | Both meanings documented |

**Recommendation:** A, with `CHILD_SHUTDOWN_FAILED` and `CHILD_SHUTDOWN_TIMED_OUT` counted as incomplete evidence
(HA: "can't assume it's still loaded"), and `CHILD_RESTART_UNSAFE` meaning a child's report satisfies the predicate.
**Pick B instead if** a reader genuinely needs "any cause was recorded".
**Reversibility:** easy
**Ratified:** Chose redefining `is_restart_safe` in place over a second predicate, to keep one name, accepting the
`_on_children_stopped` behavior change (user answer, 2026-10-27).

### D6: Wire shape of the flag

**Deciding factor:** no state where a flag exists without its reason.

| | A: `needs_restart: NeedsRestart \| None` (`reason`, `pending_tasks`, `flagged_at`) | B: `needs_restart: bool` plus `needs_restart_reason: str \| None` |
|---|---|---|
| Invalid states | None | The two fields can disagree |
| Since | `flagged_at` | Absent |
| Peer | Like k8s condition's `lastTransitionTime`, scaled to one fact | HA's enum plus reason string |

**Recommendation:** A.
**Pick B instead if** clients need a flat boolean to filter on.
**Reversibility:** hard once a release ships (public wire)
**Ratified:** Chose a nullable nested object over a flat bool plus reason, to rule out a flag without a reason,
accepting one more wire model (user answer, 2026-10-27).

### D7: Does the WS `app_status_changed` event carry the flag?

**Deciding factor:** the UI shows the badge the moment the FAILED status arrives. The frontend mirrors event fields
into its `appStatus` store and doesn't refetch on status events (`frontend/src/hooks/use-websocket.ts`).

| | A: carry it on the WS event, added at the WS dispatcher | A′: carry it on the bus payload and thread it through every emit site | B: refetch on FAILED |
|---|---|---|---|
| Badge latency | Immediate | Immediate | One extra fetch; brief lag |
| Wire | One more optional field on `AppStatusChangedData` | Same, plus `AppStateChangePayload` (public bus surface) | None |
| Emit sites that can drop it | None: `RuntimeQueryService.on_app_state_changed` reads the D4 resolver when it builds `AppStatusChangedData` | Any of about ten sites, several of which build `HassetteAppStateEvent` directly | None |
| Peer | HA sends the full entry from its one registry on each event | Same | No |

**Recommendation:** A.
**Pick A′ instead if** app authors should react to `needs_restart` on bus events. **Pick B instead if** the event
payload must stay minimal.
**Reversibility:** hard once released
**Ratified:** Chose carrying the flag on the WS event, added at the WS dispatcher from the D4 resolver, over threading
it through the bus payload or a refetch. This shows the badge with the status and leaves no emit site able to drop it,
accepting that bus subscribers don't see the flag (user answer, 2026-10-27; amended at the sketch challenge,
Finding 3). `AppStateChangePayload` and `emit_app_state_change` are unchanged.

### D8: Where does the CLI surface needs-restart?

**Deciding factor:** someone scanning `hassette app` learns that a restart is the fix.

| | A: "Restart" count column in `hassette app` plus a flagged-instances section in `hassette status` | B: `hassette status` section only |
|---|---|---|
| Discoverability | Both views | Status only |
| Data | `AppSummary.needs_restart_count`; status makes a second `GET /api/apps` | Second request only |
| Peer | systemd/kubectl: aggregate in the list, detail elsewhere | Same |

**Recommendation:** A.
**Pick B instead if** the app list must not grow a column.
**Reversibility:** easy
**Ratified:** Chose a column plus a status section over the status section only, accepting a count field on
`AppSummary` (user answer, 2026-10-27).

### D9: When does a stopping instance leave the registry? (sketch challenge, Finding 6)

**Deciding factor:** readers never see STOPPED for a stop in flight, with the least new state. Today
`_stop_app_unlocked`/`_stop_instance_unlocked` (`app_lifecycle_start_stop.py`) call `unregister_app` before
`shutdown_instances`. For up to the entry deadline, `build_manifest_info` fills the index with a STOPPED placeholder
while `on_shutdown` may still be running.

| | A: unregister after the teardown, before the outcome is recorded | B: provisional record before unregister | C: accept the window |
|---|---|---|---|
| New state | None | An "in progress" record state the D4 resolver must understand | None |
| REST/CLI mid-stop | The instance's own STOPPING | FAILED/needs-restart until settled | STOPPED placeholder |
| Exit path | `shutdown_all` reaches in-flight runtime stops and joins their single shielded attempt (`resources/lifecycle.py`, `coordinate_shutdown`); `AppHandler._force_terminal` now records them for the hard exit | Unchanged: in-flight runtime stops stay invisible to exit | Unchanged |
| Peers | HA keeps an entry in its registry until unload finishes | Unknown | Unknown |

**Recommendation:** A.
**Pick B instead if** joining an in-flight attempt at exit proves unsafe. **Pick C instead if** a mid-stop STOPPED in
REST/CLI is acceptable.
**Reversibility:** easy

The behavior to pin:
- Each stopped index stays registered until its teardown has finished. It is unregistered after that and before the
  outcome is recorded (flag, `record_failure`, event). The order matters: unregistering after the outcome would
  discard the failure entry the outcome just wrote.
- **Home:** `shutdown_instance` (`app_lifecycle_instances.py`) unregisters its own `(app_key, index)` with
  `unregister_app(app_key, index)`. It does so once the teardown wait ends, a walk-away included, and before its
  outcome branch. Every path through it does this: runtime stop, reload, init-failure teardown, the phantom path, and
  `shutdown_all` (harmless before `clear_all`). `_stop_app_unlocked` and `_stop_instance_unlocked` no longer unregister
  running indices up front, and nothing unregisters app-wide before a teardown, so recording one index's outcome can't
  clobber a sibling's entry.
- **Init-failure and phantom paths:** `shutdown_instance` takes an optional cause, the init or post-registration
  exception. With a cause, the outcome is always FAILED with that exception and init-specific log/exception wording,
  with no STOPPED emit. It is recorded with `record_failure` synchronously right after the unregister, with no
  `await` between them. The instance is flagged if the report satisfies the predicate. Without a cause, the outcome is
  the stop outcome described above. The caller sets D1's skip field on the instance before calling
  `shutdown_instance`; it is not derived from the cause. The field resets everywhere `_shutdown_deadline` resets
  (`LifecycleMixin.__init__` and the report-consuming reset in `resources/lifecycle.py`). With a cause, the FAILED
  event's `previous_status` is `STARTING`, as the init path emits today, because no STOPPING event was sent. It is set exactly when the init `try` fails (exception or
  timeout), and for a phantom that never started:
  - **Init path.** The init `try` in `initialize_instances` covers only `inst.initialize()` and `mark_ready`. The
    RUNNING emit runs after it, in its own `try` that logs the failure (`logger.exception`) and continues the loop. An
    emit failure is a telemetry failure, not an app failure. The app keeps running and its siblings still initialize,
    on both callers (`_start_app_unlocked` and `_create_instance_unlocked`).
  - **Phantom path (`_create_instance_unlocked`).** A local boolean, set just before `initialize_instances` is
    called, separates the two branches. If the exception came before that call (the instance never started), the path
    sets the skip field. If it came after (the app initialized and then reconcile raised), it passes its cause
    without the skip.
  - So a phantom whose app initialized runs `on_shutdown`, and one that never started doesn't. D3's accepted cases
    (Finding 12) still apply on the init path.
- Indices that hold only a failure entry, with no running instance, have no teardown. The stop callers discard them
  per index up front and emit STOPPED for them, as today.
- The "not found" check moves to before the stop.
- At exit, `shutdown_all` joins a runtime stop already in flight. Both owners handle the report. The flag is written
  once (D4: the first record stands). Events sent after the bus closes are dropped.
- `AppHandler._force_terminal`'s docstring, which says in-flight runtime stops aren't reached, is updated.

**Ratified:** Chose unregistering after the teardown and before the outcome over a provisional record or accepting the
window, to never show STOPPED mid-stop without new state, accepting a possible duplicate ERROR/event for one instance
when a hung runtime stop overlaps process exit. Deduping that was rejected: it would have exit skip outcome handling and
trust a runtime owner that exit may cancel, which risks silence (user answer, 2026-10-27, after the safety check above).
The home (`shutdown_instance` unregisters its own index between the teardown wait and the outcome) was re-ratified after
the sketch comb, over splitting `shutdown_instance` so callers unregister between teardown and outcome. The second comb
added the optional cause parameter for the init and phantom paths, chosen over the same split, to keep one home for
the ordering (user answer, 2026-10-27). At the ledger gate, the user also chose to end the init `try` before the
RUNNING emit, over deciding the skip from the instance's status, and to set the skip flag for a never-started phantom,
over accepting `on_shutdown` on an app that never initialized. A later comb showed the bulk start path has no phantom
`except`, so the user chose to log a failed RUNNING emit and continue. The alternatives were tearing the instance down
or wrapping `initialize_instances` in the bulk path.
Also accepting (Finding 7) that a stop whose caller is cancelled mid-teardown leaves the instance unflagged with no
ERROR, because `shutdown_instance` catches only `Exception`. No routine path cancels the caller mid-stop: Starlette
doesn't cancel handlers on client disconnect, and the file-watcher handler's timeout (600 s) far exceeds the entry
deadline. At exit, the join above covers the instance.
Also accepting two rare cases:
- **Finding 8.** An exception raised inside `shutdown_instance` outside the coordinator can flag a clean instance or
  leave an untorn-down one unflagged.
- **Finding 11.** At process exit, a flagged instance's ERROR still says to restart hassette.

## Assumed

- Ledger 134's ratified decisions hold:
  - D5: flag on a timed-out hook when the predicate holds.
  - D10: cancel a failed init by shutting the instance down.
  - D11: a keyed record in `AppRegistry`, outside the instance map, surviving unregistration and config edits,
    cleared only by restart, exposed in API, CLI and UI but not in the liveness payload.
  - D12: only the flag. The reload gate is #3110.
  - D18: the predicate, and the removals.
  - D19: init-timeout teardown under the entry deadline, with a flag on every expiry.

  Evidence: `design/specs/134-resource-lifecycle-outcomes/design.md` and its 2026-10-27 Addendum.
- The app layer's own stop timeout is already gone. `shutdown_instance` runs under the entry deadline and walks
  away on expiry. Evidence: `app_lifecycle_instances.py` (`shutdown_instance`, `walk_away_from_instance`), #3104
  (closed).
- Children initialize after the user's init hooks, and shutdown runs a resource's body whatever its status. So a
  failed `on_initialize` leaves `Bus`/`Scheduler` `NOT_STARTED`, and their `on_shutdown` still removes listeners
  and jobs. Their removal callbacks are registered in `__init__`. Evidence: `resources/base.py` (`_initialize_body`),
  `resources/lifecycle.py` (`_run_shutdown_coordinator`), `bus/bus.py`, `scheduler/scheduler.py`.
- `AppRegistry.clear_all()` also clears the needs-restart record. Its callers are process exit (`shutdown_all`,
  `app_lifecycle_instances.py`) and the test harness reset (`testing/_reset.py`), the harness's stand-in for a
  restart. "Cleared only by restart" means no runtime operation clears it. Evidence: `app_registry.py` (`clear_all`).
- `App.cleanup()` already closes the app cache. Evidence: `src/hassette/app/app.py` (`cleanup`).
- `AppStateChangePayload.from_app`/`from_instance_info` have no registry access. Evidence: `src/hassette/events/hassette.py`.
- A removed config key is rejected at load by `ExcludeExtrasMixin`, listed in the removed-keys admonition, and has
  a rejection test. Evidence: `docs/pages/operating/index.md`, `tests/unit/config/test_unknown_keys.py`.
- Peer evidence for D3–D8: `design/research/2026-10-27-needs-restart-flag/prior-art.md`.
- The file-level work order (every caller, docstring, doc, test and regeneration step) is issue #3109's body as
  updated 2026-10-27. Where it differs from this ledger, the ledger wins. The sketch challenge and comb changed five
  points:
  - D4: one resolver; record wins; no merge on re-flag.
  - D7: the flag is added at the WS dispatcher; `AppStateChangePayload` and `emit_app_state_change` are unchanged.
  - D9: unregister after teardown, before the outcome.
  - D9: the cause parameter; a never-started phantom does set the skip flag, unlike the issue's "phantom path does
    not set the hook-skip flag"; a failed RUNNING emit is logged and the loop continues.
  - D3: observable cleanup assertion.

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
