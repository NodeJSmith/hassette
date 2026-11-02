# Design: Key the app registry and lifecycle on instance name

**Date:** 2026-11-02
**Status:** built
**Mode:** sketch
**Issues:** #3099
**Parent:** design/specs/133-log-identity-axes/design.md
**Prior art:** design/research/2026-10-18-log-identity-axes, design/research/2026-11-01-rekey-history-by-instance-name/prior-art.md

## Summary

`AppRegistry` tracks instances by `(app_key, index)`, and the lifecycle passes indices everywhere. The index is a position in the config list, so reordering entries restarts them today (`_plan_reload` compares by position, `src/hassette/core/app_lifecycle_changes.py:202`), and a needs-restart flag or failure entry stays at the position instead of following the instance. This change keys all of that on the instance name, so a reorder restarts nothing and every per-instance record follows its instance. HTTP routes, wire models, the client, the CLI and frontend URLs keep using the index until #3100, through one temporary lookup.

Where each piece lives:

- **Instance and needs-restart maps:** `_instances` and `_needs_restart` in `src/hassette/core/app_registry.py`, plus every per-instance method there (`register_app`, `unregister_app`, `record_failure`, `flag_needs_restart`, `get_needs_restart`, `refusal_reason`, `resolve_instance_info(s)`, `get`, `get_running_apps`, `get_instances`, `get_failed_instance_infos`, `prune_stale_failed_indices`, `tracked_indices`). `prune_stale_failed_indices` removes non-running entries whose name isn't configured, and keeps needs-restart records as today. `_index_in_current_config` becomes the same membership test. A class-load failure records against the first configured name that is neither running nor flagged.
- **Display order:** derived in `AppRegistry` from the manifest (and tracked orphans, see D4). `AppInstanceInfo.index` (`src/hassette/schemas/app_snapshots.py`), `InstanceOutcome.instance_index` (`src/hassette/schemas/app_outcomes.py`) and `HassetteAppStateEvent` (`src/hassette/events/hassette.py`) keep carrying an index for the wire. It is display order when built from the registry; `HassetteAppStateEvent.from_app` carries the construction-time `App.index` until #3100 (D3).
- **Index-to-name lookup, until #3100:** `AppRegistry.instance_name(app_key, index)`, which already exists and already backs `instance_name_filter` in `src/hassette/web/dependencies.py`. Each instance route in `src/hassette/web/routes/apps.py` translates index to name with it once, then calls the lifecycle by name. `_require_valid_instance_index` and `_orphan_instance_permitted` read the same order. Nothing below the route layer takes an index. `_instance_index_in_range` becomes a check that the name is in the manifest's configured names, re-checked under the app-key lock as today. `stop_instance` keeps skipping it, so an orphan stays stoppable.
- **Lifecycle:** `src/hassette/core/app_lifecycle_start_stop.py`, `app_lifecycle_instances.py`, `app_lifecycle_common.py` (`ActionOutcomes` slots are keyed by name and carry the display index for the outcome), `app_handler.py`, `app_factory.py`.
- **Selective restart:** `AppRestart` and `_plan_reload` in `src/hassette/core/app_lifecycle_changes.py` compare old and new configs by name (D2). `AppRestart.indices` becomes names.
- **Retiring removed names' rows:** a new method on `DatabaseRetentionMixin` (`src/hassette/core/database_retention.py`) holding the retire step extracted from `_run_parent_guard_deletes`, enqueued from `_restart_apps_unlocked` when a restart stopped a name that left the config (D2).
- **Cache keys:** `App.cache_key` and `resolve_cache_keys` (D5). `resolve_cache_keys` takes each name from `normalize_app_config(manifest.app_config)`, already resolved by manifest validation. The docstrings of `resolve_cache_keys` and `unsafe_app_key_reason`, and the comment in `unsafe_cache_path_reason`, move to `{app_key}/{instance_name}`.
- **Blocking attribution:** `resolve_owner` in `src/hassette/core/block_io_guard.py` and its caller in `loop_watchdog.py` move to `instance_name`, which both already carry. A stale index would pick the wrong app's blocking behavior.
- **Status lookup:** `on_app_state_changed` in `src/hassette/core/runtime_query_service.py` resolves by the event's `instance_name`.
- **Public API:** `Hassette.get_app` is removed from `src/hassette/core/core.py`. `AppHandler.get` and `AppRegistry.get` take an optional `instance_name` (D7).
- **Doubles:** `tests/support/mock_hassette.py`, `tests/support/web_mocks.py`, `tests/support/app_staging_helpers.py`, `tests/e2e/mock_fixtures/manifests.py`, `tools/client_compat_live_state.py`.
- **Docs:** `docs/pages/core-concepts/apps/configuration.md` (instance names section) says a reorder restarts nothing, and its "within one retention cycle" line narrows to removals a live reload didn't apply (D2). `docs/pages/core-concepts/cache/index.md` moves to the name (D5). The cache reset and the `Hassette.get_app` removal go in the PR's `BREAKING CHANGE:` footer, which becomes the changelog's migration note.

**Out of scope:** name-addressed routes, wire models, client, CLI and frontend URLs, and removing `instance_index` from wire models and tables (#3100). Moving a live instance's stored telemetry on rename. Instance-level changes to `AppChangeDetector`, which still reports changes per app key.

## Posture

- **Failure handling:** loud and minimal, as in the parent. No new fallbacks.
- **Compatibility:** break freely for internal APIs, pre-v1. No HTTP or wire change, since those belong to #3100, so `client_compat` needs no ignore entries. A public Python change gets a migration note.
- **Scope:** minimal. Registry, lifecycle, selective restart and the temporary index lookup.
- **Rollout:** one PR, shipped outright, no flag.
- **Hardening:** project defaults.
- **Altitude:** `build`. One session builds it next, and this ledger cites files.

## Decisions

### D1: What shape do the name-keyed maps take?

**Situation:** Names are unique across the whole config, so a name alone could be the key. But nearly every registry reader asks per app key ("all instances of this app", manifest status, stop targets), and an orphan left running under one app key can briefly share a name with a newly configured instance under another, because config validation only sees the config.

**Deciding factor:** smallest diff that keeps today's readers direct.

| | A: Nested, `app_key -> name -> entry` | B: Flat, `name -> entry` with `app_key` on the entry |
|---|---|---|
| Per-app readers | Unchanged shape; one dict read | Each filters every entry by `app_key`, or needs a second index |
| Orphan sharing a name with a new instance in another app | Both tracked; the owner-registry collision is unchanged from today | One silently overwrites the other |
| Diff | Key type changes | Key type changes, plus every per-app reader |
| Peer behavior | AppDaemon keys on the name alone, but has no app-key grouping to preserve | Same note |

**Recommendation:** A, because every reader already starts from an app key.
**Pick B instead if** you expect app key to stop being a grouping concept soon.
**Reversibility:** easy (private to `AppRegistry`)
**Ratified:** Chose nested `app_key -> name -> entry` maps over a flat name-keyed map, to keep per-app readers a single dict read, accepting that the app key stays part of the lookup even though names are unique across the config.

### D2: What does a config change that adds or removes an instance restart, and what retires a removed instance's rows?

**Situation:** A changed instance count restarts every instance of the app today (`_plan_reload`, the `len` branch), and otherwise restarts changed positions. Comparing by name, a change falls into three sets: names only in the old config (stop), names only in the new config (create), and names in both with a different config (stop and create). A rename is then simply one stop and one create. The issue only requires that a reorder restarts nothing.

A removed instance leaves the app's instance list as soon as it stops, and its jobs leave the job lists on a clean stop, because scheduler shutdown writes `removed_at` (`Scheduler.on_shutdown` -> `SchedulerService._remove_jobs`). Its listeners don't: bus shutdown skips that write (`Bus.remove_all_listeners`), and they stay active until something retires them. Until then they appear in `GET /bus/listeners` (the Handlers page and global `hassette listener`) and count in the app's `handler_count` (`active_listeners`). Renames already have this lag, per ledger 142 D1.

The sweep's retire step (`build_retire_unconfigured_instances_query`, run first in `_run_parent_guard_deletes`, `src/hassette/core/database_retention.py`) retires every unretired app-tier row whose `(app_key, instance_name)` isn't in `live_instances()` (configured or running). It never deletes, so a queued execution keeps a valid parent, and it has no `once=True` branch. `reconcile_app_registrations` with empty live sets was rejected for this job: it deletes rows with no history, which drops a queued first execution on the foreign key (`executions` enforces it, migration `009.sql`), it awaits the database with every app-key lock held, and its `once=True` delete can roll back the whole call.

**Deciding factor:** unchanged instances keep running and dead handlers don't appear live, using the one owner of "no longer configured".

| | A: Changed names; queue the sweep's retire step after the stop | B: Keep full reload on a count change | C: Changed names; new retire statement scoped to removed names | D: Changed names; only the hourly sweep retires |
|---|---|---|---|---|
| Unchanged siblings when one is added or removed | Keep running | Restart | Keep running | Keep running |
| Plan code | One name diff; the `len` branch is deleted | Name diff plus the `len` branch | One name diff; the `len` branch is deleted | One name diff; the `len` branch is deleted |
| Removed or renamed instance's handlers still listed | Until the queued write runs; a UI refetch can occasionally beat it | Removed: gone at the reload. Renamed: up to one retention cycle | Gone at the reload | Up to one retention cycle (default 1 hour) |
| Queued execution still inserts | Yes | Yes | Yes | Yes |
| Database stall delays the reload | No, it is queued | Yes, as today's full reconcile does | Yes, unless placed past lock release | No |
| Surviving `once=True` row | Not touched | Can roll back the full reconcile, as today | Not touched | Not touched |
| Owners of "no longer configured" | One | Two, as today | Two | One |
| New code | Extract the retire step into a method on `DatabaseRetentionMixin`, plus one `enqueue_if_ready` | None | New repository method, SQL and executor wrapper | None |
| If it fails or the queue is full | The hourly sweep catches it | n/a | The hourly sweep catches it | n/a |
| A name moved between apps | Covered: stop-before-create already spans all restarts (`_restart_apps_unlocked`) | Same | Same | Same |
| Peer behavior | Airflow retires absent registrations and keeps history, and its users filed #11901 when a renamed DAG stayed listed (`design/research/2026-11-01-rekey-history-by-instance-name/prior-art.md`) | unknown | Same as A | Matches the complaint in #11901 |

**Recommendation:** A, because it keeps "gone at the reload" with existing SQL and one owner, and removes the delete, lock and `once=True` problems instead of guarding against them.
**Pick B instead if** you'd rather keep restarting siblings on a count change. **Pick C instead if** rows must be retired before the reload's completion event. **Pick D instead if** stale handler rows for up to an hour are acceptable and you want no new code.
**Reversibility:** easy
**Ratified:** Chose touching only the names that changed and enqueuing the sweep's existing retire step after the stop half, over keeping a full reload on a count change, a new retire statement, or relying on the hourly sweep alone, so unchanged siblings keep running, nothing is deleted under a queued execution, and the reload doesn't wait on the database, accepting that a UI refetch can occasionally beat the queued write and show dead handlers until the next fetch, and that because the plan still works from the config diff, an instance tracked outside that diff (left by an earlier partial failure) isn't stopped by a later edit and stays until a full reload or restart, with its rows retired once it stops running.

### D3: What happens to a running instance's `App.index` when a reorder no longer restarts it?

**Situation:** `App.index` is set at construction and listed in the public `_APP_PUBLIC_API`. Today a reorder recreates the instance, so the value stays right. Once a reorder restarts nothing, it goes stale. It feeds `HassetteAppStateEvent.from_app`, and the frontend stores live status under `appStatusKey(app_key, index)` (`frontend/src/hooks/use-websocket.ts:139`). So after a reorder, a stale event would paint one instance's status on another instance's row. It also feeds `cache_key` (D5) and the log identity stamp (`src/hassette/app/app.py:204`). Nothing in docs, `examples/` or the hautomate corpus reads `self.index`.

**Deciding factor:** live status stays on the right row until #3100, with the least code that #3100 has to remove.

| | A: Refresh in place | B: Events read the registry; delete `App.index` | C: Leave it frozen |
|---|---|---|---|
| Mechanism | `AppRegistry.set_manifests` writes each running App's `index` to its new position (one writer) | `from_app` callers pass the index from the registry; constructor parameter and public attribute go | Nothing |
| Live status after a reorder | Right row | Right row | Wrong row until that instance restarts or the page refetches |
| Public surface | `self.index` stays, documented as display order, and can change | `self.index` removed now, migration note | `self.index` stays and can be wrong |
| New state to keep in sync | One write, one writer | None | None |
| Log stamp and stored `instance_index` | Frozen until restart; lookups use the name, so only display links can be stale (ledger 142 D3 accepted this until #3100) | Log identity needs another source for the stamp | Same as A |
| Test harness (`_simulation.py` calls `from_app` with no registry entry guaranteed) | Unaffected | Needs a route to the index | Unaffected |

#3099 and #3100 ship in one release, so a wrong status row can only exist on `main` between the two merges, never in a release.

**Recommendation:** C, because no release can show the gap, so a refresh would be code that exists only between two merges. #3100's pickup decides whether `App.index` survives.
**Pick A instead if** you run `main` and a wrong status row after a reorder would mislead you between the merges. **Pick B instead if** you'd rather remove the public attribute here than leave that to #3100.
**Reversibility:** easy
**Ratified:** Chose leaving `App.index` frozen at construction, over refreshing it in place or deleting it now, so no code exists only between two merges, accepting that on `main` before #3100 a status event after a reorder can land on the wrong row, and requiring #3100 to key live status on the name and decide whether `App.index` survives.

### D4: What index does an orphan report?

**Situation:** An orphan is an instance still tracked but no longer in config: a removed instance mid-stop, or a needs-restart record that outlives its config entry. With index keys, it kept its old index. With name keys, it has no position, yet `AppInstanceInfo.index`, `InstanceOutcome.instance_index` and the `/instances/{index}/stop` route all need an integer until #3100.

**Deciding factor:** the index resolves to exactly one instance, with no stored position.

| | A: Derive: configured names in config order, then orphans sorted by name | B: Store the last known index on the entry | C: Report no index (`None`) |
|---|---|---|---|
| Index unique per app | Yes | No: a new configured instance can take the same position, so the route can't resolve it | Yes, for configured instances |
| Orphan stoppable from the UI and CLI | Yes | Ambiguous | No, the route has no address for it |
| Wire change | None | None | `int | None` on `AppInstance.index`, `InstanceOutcome.instance_index` and the WS `index`, plus regenerated schemas and types, and possibly a `client_compat` ignore entry |
| Frontend | None | None | Null handling wherever `index` is the row key, status key or action target (`multi-instance.tsx`, `app-data.ts`, `action-buttons.tsx`) |
| New state | None | One field | None |
| Stability | An orphan's index can shift when config changes; each request resolves afresh | Stable but colliding | n/a |
| After #3100 | Deleted whole | Deleted whole | Wire and frontend edits redone against names |

**Recommendation:** A, because it's a pure function of config and tracked names, needs no wire or frontend change, and #3100 deletes it whole.
**Pick B instead if** a UI link to an orphan must survive a config edit. **Pick C instead if** no derived order is worth the wire and frontend round.
**Reversibility:** easy
**Ratified:** Chose deriving display order (configured names in config order, then orphans sorted by name), over a stored index or reporting none, so each index resolves to one instance with no wire or frontend change, accepting that an orphan's index can shift when config changes, which is harmless because #3099 and #3100 ship in one release.

### D5: Does the default cache directory move from the index to the name?

**Situation:** An app's default cache lives at `data_dir/{app_key}/{index}/cache/cache.db` (`App.cache_key`, `src/hassette/app/app.py:235`; `resolve_cache_keys`, `src/hassette/config/config.py:629`). A reorder therefore hands each instance another's cache at its next start, now that the reorder itself no longer restarts anything. The parent's Done-when says a reorder never moves an instance's history, but neither the parent nor #3099 mentions the cache. An explicit `cache_key` is unaffected.

**Deciding factor:** position stops carrying meaning anywhere an instance stores data.

| | A: Move to `{app_key}/{instance_name}` | B: Keep `{app_key}/{index}` | C: Move, and migrate old directories at startup |
|---|---|---|---|
| Reorder | Each instance keeps its cache | Instances swap caches at next start | Each instance keeps its cache |
| Upgrade | Default caches start empty; old directories stay on disk | No effect | Caches carry over |
| Rename | New cache, matching telemetry's "renaming starts a new history" | No effect | New cache |
| New code | Two lines plus a doc change (`docs/pages/core-concepts/cache/index.md`) and migration note | None; #3100 has to settle it anyway if `App.index` goes | A startup migration that outlives its use |
| Peer behavior | unknown | unknown | unknown |

**Recommendation:** A, because a cache is rebuildable and the parent's posture already accepts no-backfill resets.
**Pick B instead if** cold caches on upgrade would hurt a real install more than swapped caches on a rare reorder. **Pick C instead if** caches here hold data that can't be rebuilt.
**Reversibility:** easy (hard for users only in that the old directories are orphaned)
**Ratified:** Chose moving the default cache directory to `{app_key}/{instance_name}` (in `App.cache_key` and `resolve_cache_keys`), over keeping the index or migrating old directories, so a reorder never moves an instance's cache, accepting that default caches start empty on upgrade, old directories stay on disk, and a rename starts a new cache, all stated in the docs and migration note, and that on a native Windows host an instance named after a device such as `con` has an unusable default cache directory, as app keys already do.

### D6: What does a needs-restart flag do when its instance is renamed or its name moves to another app?

**Situation:** A flag means the old instance's teardown left work that may still be running, so no replacement is created over it until Hassette restarts. By name, a reorder now correctly keeps the flag on its instance (today it stays on the position and blames a neighbor). But a rename looks like a new instance, so it starts beside the old work, which today's position-keyed gate refuses. A name moved to another app key also passes a per-app check; that gap exists today.

**Deciding factor:** least machinery for a rare overlap: a teardown that hung, followed by a rename before restarting.

| | A: Gate on `(app_key, name)`; a rename starts fresh | B: Gate on the name across all app keys | C: Refuse any new name in an app with a flagged instance |
|---|---|---|---|
| Reorder | Flag follows the instance | Same | Same |
| Rename while flagged | New instance starts; the old name stays FAILED in the UI until restart | Same as A | Refused until restart |
| Name moved to another app while flagged | New instance starts, sharing an owner id with the old work's leftovers | Refused | Refused only if the target app is flagged |
| New code | None | A scan in `refusal_reason` | A new check at creation, and an unrelated new instance gets blocked too |
| Frequency | Needs a hung teardown plus a config edit before restart | Same | Same |

**Recommendation:** A, because the old name stays visibly FAILED with its reason, and guarding a rare overlap isn't worth new checks. The behavior goes in the `refusal_reason` docstring.
**Pick B instead if** you consider a shared owner id with leftover work worse than one scan. **Pick C instead if** a rename while flagged must never run beside the old work.
**Reversibility:** easy
**Ratified:** Chose gating replacements on `(app_key, name)`, over a cross-app name scan or refusing new names in a flagged app, so no new checks guard a rare overlap, accepting that a renamed or moved instance can start beside the old instance's leftover work while the old name stays FAILED with its reason until restart, and that for a moved name the leftover work shares an owner id, so a late teardown can remove the new instance's registrations until Hassette restarts, stated in the `refusal_reason` docstring.

### D7: What does the public `Hassette.get_app(app_name, index=0)` become?

**Situation:** `get_app` (`src/hassette/core/core.py:261`) takes an index that defaults to 0, and any app can reach it as `self.hassette.get_app`. Nothing in docs, `examples/` or the hautomate corpus calls it; only tests do. `#3100` would break the signature in the same release anyway, so there is no compatibility to preserve by keeping it.

**Deciding factor:** no index in a public signature, and the smallest public surface.

| | A: `get_app(app_key, instance_name=None)` | B: `get_app(instance_name)` | C: Keep `index`, translated through the lookup | D: Remove `Hassette.get_app` |
|---|---|---|---|---|
| Common call `get_app("env_reader")` | Unchanged | Breaks | Unchanged | Breaks |
| Public surface | Same size, new parameter to support | Same size, new meaning | Same size, positional | Smaller |
| Migration note | One line | Every caller | None now; #3100 breaks it in the same release | One line: removed |
| In-repo callers | Unchanged | Rewritten | Unchanged | Tests move to `app_handler.get` |
| Internal `AppHandler.get` / `registry.get` | Takes a name, with `None` for "first running in config order" (`web/config_view.py:334`) | Needs a separate method | Unchanged | Takes a name, with `None` for "first running in config order" |

**Recommendation:** D, because nothing uses it, and every other option commits to supporting a method that wasn't designed for this.
**Pick A instead if** user apps turn out to need the lookup.
**Reversibility:** easy (pre-v1)
**Ratified:** Chose removing `Hassette.get_app`, over re-signing it around the name or keeping the index, so the public surface shrinks and no unused method needs support, accepting a breaking removal with a one-line migration note; tests move to `AppHandler.get`, whose `instance_name` is optional and defaults to the first running instance in config order.

## Assumed

- #3099 and #3100 ship in one release, so a state that exists only between their merges never reaches a user. Evidence: the user's statement during this sketch; both are the last open issues in the *Instance Identity* milestone.
- Parent D11 holds: the instance name is the sole identity, unique across the config, and `instance_index` is display order only. Renaming makes a new instance. Evidence: `design/specs/133-log-identity-axes/design.md` D11.
- Parent 2026-10-21 addendum holds: a live reload stops every replaced instance across all app keys before creating any replacement, with each key's lock held across both phases. Evidence: `_restart_apps_unlocked` in `src/hassette/core/app_lifecycle_changes.py`.
- Bus and Scheduler owner registries already key on the name, so this change needs no edit there. Evidence: `App.unique_name` returns `app_config.instance_name` (`src/hassette/app/app.py:175`); `owner_id` returns the parent's `unique_name` (`src/hassette/resources/base.py:263`).
- The name-overlap detection the issue asks to delete is already gone. Evidence: no match for `overlap` in `src/hassette/core/app_lifecycle_changes.py`; parent 2026-10-21 addendum.
- Each normalized instance config carries its resolved `instance_name`. Evidence: `INSTANCE_NAME_KEY` and `create_single_instance` in `src/hassette/core/app_factory.py`.
- Telemetry already filters and reconciles by name, and retires names no longer configured within one retention cycle. Evidence: `design/specs/142-rekey-telemetry-instance-name/design.md` D1; `instance_name_filter` in `src/hassette/web/dependencies.py`.
- A reorder still reaches `_plan_reload` through the `reload_apps` bucket, and `_reconcile_changes` still broadcasts `APP_LOAD_COMPLETED`, so the UI refetches the new order even when the plan is empty. Evidence: `src/hassette/core/app_change_detector.py`; `_reconcile_changes` in `app_lifecycle_changes.py`.
- `instance_name_filter` relies on `AppRegistry.instance_name` returning an invalid label for an unknown index, which matches no stored row. Evidence: `src/hassette/web/dependencies.py:115`; ledger 142 Summary.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- An index or name the app doesn't have (an orphaned-app stop naming no instance, a name removed while an action waited for its lock) reports the display index just past the app's names: an outcome needs an integer until #3100, and `ActionResponse.instance_index` still echoes what the route was given.
- `NeedsRestartRecord` drops its `instance_name`: the map key now holds it, and two owners of one value would be the only way they could disagree.
- An `App`'s own name is the single source once one exists: `shutdown_instance`, `initialize_instance` and the `settle_*` helpers read `inst.instance_name`, `shutdown_instances` takes apps rather than a name-keyed dict, and `AppRegistry.register_app(app_key, app)` files the entry under the app's name, so a key can't disagree with it. `AppConfig.read_framework_fields_by_name` keeps that field equal to the validated config name for `alias` and `alias_generator`; a config class that changes it another way (`validation_alias`, a transforming validator) fails that instance at creation, because callers read an app back by its configured name. Paths that can run with no `App` (`stop_instance`, `_create_instance_unlocked`, `record_failure`, `flag_needs_restart`) still take a name. Ship-time challenge, user's choice.
- The queued retire step is skipped when no `DatabaseService` is wired (a test harness). An exception there would have aborted the create half; the ledger's "the hourly sweep catches it" means it must not.
- `docs/pages/operating/index.md` and `docs/pages/core-concepts/cache/patterns.md` change too, though the Summary doesn't list them: the first states D6's old position-keyed gate, the second the old cache path.
- Deleting a whole app block queues the retire step too, after its `stop_app`: D2's trigger named restarts, but the outcome it ratifies is that a removed name's handlers don't appear live. An orphan stopped by hand still waits for the sweep, as D2 accepts. Ship-time challenge, user's choice.
- A dropped retire write logs a WARNING, so D2's fallback to the sweep is visible.
- `AppHandler.get` takes `instance_name` by keyword only, so a stale `get(key, 0)` raises `TypeError` rather than returning `None` for a running app; the PR's `BREAKING CHANGE:` footer says so. `AppRegistry.get` stays positional. Ship-time challenge, user's choice.
- `NOT_IN_CONFIG_REASON` now says "instance" rather than "index", and the refusal ERROR no longer carries an index. Outcome reasons are free text, not part of the wire contract.
