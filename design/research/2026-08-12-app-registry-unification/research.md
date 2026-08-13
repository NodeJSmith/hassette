---
proposal: "Unify AppRegistry's dual-dict instance tracking into a single status-carrying map so partial failure is observable per-instance"
date: 2026-08-12
status: Draft
flexibility: Exploring
motivation: "Partial failure is invisible -- a 3-instance app with 1 failed instance looks like a healthy 2-instance app. This blocks live config editing via UI."
constraints: "Must not break existing web API contracts, WS push events, or frontend rendering. Must align with project's immutability coding style."
non-goals: "Per-instance reload (issue #796) is related but is its own feature, not required in this scope."
depth: deep
---

# Research Brief: Unify AppRegistry Instance Tracking

**Initiated by**: Investigation into making partial app failure visible per-instance, motivated by the live config editing feature needing instance-level observability.

## Context

### What prompted this

A 3-instance app where instance 0 fails but instances 1 and 2 run produces a manifest-level `status` of `"running"` -- the failure is effectively hidden from the app-level view. The user only discovers the failure by expanding the app row in the frontend and inspecting individual instance statuses. This matters for the live config editing feature being built on another branch, which needs to know which specific instances are in what state to make intelligent reload decisions.

### Current state

AppRegistry (`src/hassette/core/app_registry.py`) tracks instance state across three separate dicts:

| Dict | Type | Contents |
|------|------|----------|
| `_apps` | `dict[str, dict[int, App]]` | Running instances only |
| `_failed_apps` | `dict[str, list[tuple[int, Exception]]]` | Failure records (can accumulate duplicates for the same index) |
| `_blocked_apps` | `dict[str, BlockReason]` | Intentionally-not-started apps (currently only `ONLY_APP` from `--app` filter) |

Key behaviors of this design:

1. **`build_manifest_info()` status priority**: `disabled > blocked > running > failed > stopped`. When any instance is running, the manifest status is `"running"` even if other instances have failed. The `instances` list inside `AppManifestInfo` does include both running and failed entries, but the top-level `status` string hides the mixed state.

2. **`get_apps_by_key()`**: Returns only running instances. Failed instances are invisible to this method's callers (`shutdown_all`, `start_app` post-create fan-out, `_fold_unblocked_apps_into_changes`).

3. **`register_app()` side effect**: When registering index N, if index N has a prior failure recorded, it clears ALL failures for that app_key (not just index N) -- a coarse clear keyed on whether any matching index exists in the failure list.

4. **`record_failure()` accumulates duplicates**: The failure list is append-only per `(app_key, index)` -- repeated calls for the same index create multiple entries with no deduplication.

5. **`info_from_failure()` synthesizes `instance_name`**: Failed instances get `f"{class_name}.{index}"` as their name because the real `App` object (with its user-configured `instance_name`) was never successfully constructed. This creates an identity inconsistency between running and failed instances of the same app_key.

6. **No locking in AppRegistry**: It is a plain synchronous data structure. Concurrency is managed by `AppLifecycleService` via per-app-key `asyncio.Lock`s (protecting only `start_app`'s create-initialize-reconcile pipeline) and `_change_event_lock` (serializing file-watcher hot-reload). Notably, `stop_app` is not locked.

### Key constraints

- **Immutability rule**: The project's `coding-style.md` mandates creating new objects rather than mutating existing ones. The current design violates this -- `_apps` and `_failed_apps` are mutated in place.
- **Existing API contracts**: `AppStatusResponse`, `AppManifestResponse`, `AppInstanceResponse`, and `DashboardAppGridEntry` are established web API models consumed by the frontend. Breaking changes would require frontend migration.
- **Frontend already has per-instance infrastructure**: The frontend has instance-level display (expandable table rows, instance switcher, multi-instance overview, per-instance WS status keying). The gap is upstream: the backend's manifest-level `status` field doesn't surface partial failure.
- **`ManifestStatus` is a 5-value Literal**: `"disabled" | "blocked" | "running" | "failed" | "stopped"`. No `"degraded"` or `"partial_failure"` value exists today.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Registry internals | `app_registry.py` | Med | Core data structure change; many consumers |
| Snapshot models | `app_snapshots.py` | Med | Dataclass shape change; affects mappers |
| App factory | `app_factory.py` | Low | 4 call sites for `register_app`/`record_failure` |
| App lifecycle service | `app_lifecycle_service.py` | Med | ~15 call sites across 8 methods |
| Runtime query service | `runtime_query_service.py` | Low | 3 wrapper methods |
| Web mappers | `web/mappers.py` | Low | 4 mapper functions |
| Web models | `web/models.py` | Low | Add `ManifestStatus` value or new field |
| Web routes | `web/routes/apps.py`, `telemetry.py` | Low | Consumers of snapshot/manifest models |
| Test utilities | `test_utils/reset.py`, `harness.py`, `web_mocks.py` | Med | ~6 direct registry access points |
| Unit tests | `test_app_registry.py`, `test_overlay_runtime_state.py` | High | ~30 `record_failure` sites, ~30 `register_app` sites, ~17 `get_snapshot` sites |
| Integration tests | Multiple files | Med | ~25 `get_apps_by_key` sites, ~17 `get_full_snapshot` sites |
| Frontend components | `apps.tsx`, `apps-table-row.tsx`, `app-detail.tsx` | Low | Already per-instance; only aggregate stats strips need changes |
| Generated types | `generated-types.ts`, `ws-types.ts` | Low | Auto-generated from backend schema |

### What already supports this

1. **Frontend is already instance-aware**: `appStatusKey(appKey, index)` keying in the store, expandable instance rows in the table, `InstanceSwitcher` and `MultiInstanceOverview` in app detail, WS handler that processes per-instance `app_status_changed` events. The infrastructure is mature and tested (`apps-table-row.test.tsx`, `app-detail.instances.test.tsx` with 19 tests).

2. **`build_manifest_info()` already builds a combined `instances` list**: Lines 207-221 iterate both `_apps` and `_failed_apps` to produce a single list of `AppInstanceInfo` entries with their individual statuses. The per-instance data IS available downstream; the problem is only the top-level `status` field's priority chain.

3. **DB schema is instance-keyed**: Telemetry tables use `(app_key, instance_index)` as their natural key. No schema migration needed.

4. **WS push is already per-instance**: `emit_app_state_change` fires for each instance individually with `index`, `instance_name`, `status`, and `exception`.

5. **`AppRegistry.unregister_app(app_key, index)` already supports single-instance removal**: The `index` parameter exists and works. `get(app_key, index)` works too.

6. **CLI already resolves instance names to indices**: `cli/client.py:185-215` `resolve_instance()` accepts either a digit index or a name string.

### What works against this

1. **Dual-dict + list structure is deeply embedded**: `_apps` is a `dict[str, dict[int, App]]`, `_failed_apps` is a `dict[str, list[tuple[int, Exception]]]`. These are fundamentally different shapes -- one holds `App` objects, the other holds `(int, Exception)` tuples. Unifying them requires a wrapper type that can represent both states.

2. **`get_apps_by_key()` callers assume running-only semantics**: `shutdown_all()` iterates results and calls `shutdown_instances()`. `start_app()` uses results to emit `NOT_STARTED` events and call `initialize_instances()`. Both would break if failed instances appeared in the results, since you cannot shut down or initialize a failed `App` object (it may not even exist as a real `App`).

3. **`__contains__` and `app_keys()` mean "has running instances"**: `should_auto_reconcile()` uses `app_key in self.registry` to check if the app is already running. `_fold_unblocked_apps_into_changes()` uses `set(self.registry.app_keys())` for the same purpose. These callers depend on failed apps being excluded.

4. **`register_app()` coarse clear**: Registering index 0 clears ALL failures for the app_key, not just index 0's. With a unified structure, this logic would need to be refined to per-index clearing.

5. **`record_failure()` accumulates duplicates**: The list-based structure allows multiple failure records per `(app_key, index)`. A dict-based structure would naturally deduplicate (last write wins), which may or may not be desired.

6. **Test surface is large**: ~160+ call sites across unit and integration tests reference the current API directly. Many tests set up registry state by calling `register_app` and `record_failure` with the current argument shapes.

## Options Evaluated

### Option A: Unified dict with frozen InstanceEntry dataclass

**How it works**: Replace `_apps` and `_failed_apps` with a single `_instances: dict[str, dict[int, InstanceEntry]]` where `InstanceEntry` is a frozen dataclass:

```python
@dataclass(frozen=True)
class InstanceEntry:
    index: int
    app: App[AppConfig] | None  # None for failed-at-startup instances
    status: ResourceStatus
    error: Exception | None = None
    error_message: str | None = None
    error_traceback: str | None = None
    instance_name: str | None = None  # from config or synthesized
```

`register_app()` creates an `InstanceEntry(app=app, status=RUNNING, ...)`. `record_failure()` creates an `InstanceEntry(app=None, status=FAILED, error=error, ...)`. All queries go through `_instances` with filtering by status as needed.

`get_apps_by_key()` would filter to entries where `entry.app is not None` (or `entry.status in ACTIVE_STATUSES`) to preserve backward compatibility for lifecycle callers. A new `get_all_instances_by_key()` method returns everything, including failed entries.

`build_manifest_info()` status derivation adds a new `"degraded"` status when both running and failed instances exist for the same app_key. This requires adding `"degraded"` to `ManifestStatus` and `MANIFEST_STATUS_KEYS`, plus a frontend mapping for the new status badge.

`frozen=True` on the dataclass enforces immutability -- state transitions create new `InstanceEntry` objects via `dataclasses.replace()` rather than mutating fields.

**Pros**:
- Single source of truth for instance state -- no synchronization bugs between `_apps` and `_failed_apps`
- Natural deduplication: one entry per `(app_key, index)` at any time
- `frozen=True` aligns with the project's immutability rule (current design violates it)
- `instance_name` can be preserved from the manifest config even on failure, by extracting it from the manifest before attempting to construct the `App` -- this fixes the identity inconsistency in `info_from_failure()`
- Clean migration path: old methods can be reimplemented on top of the new structure without changing their signatures
- `build_manifest_info()` becomes simpler: iterate `_instances[app_key].values()` instead of consulting two separate dicts

**Cons**:
- `app: App | None` is an awkward union -- callers that need the actual `App` object must handle `None`
- Test surface is large (~160+ call sites); many tests construct registry state directly
- `InstanceEntry` holds a reference to the mutable `App` object inside a frozen dataclass, which is semantically odd (the entry is immutable but its contents are not)
- Adding `"degraded"` to `ManifestStatus` is a breaking API change for any consumers that match exhaustively on the 5-value literal

**Effort estimate**: Medium-Large. The registry internals and snapshot builders are a focused change, but the test migration is extensive and the `ManifestStatus` addition ripples through models, mappers, generated types, and frontend badge rendering.

**Dependencies**: None (all internal types).

### Option B: Keep dual-dict, add a `"degraded"` status in the derivation layer

**How it works**: Leave `_apps` and `_failed_apps` as they are. Change `build_manifest_info()` to derive a `"degraded"` status when both `_apps.get(app_key)` and `_failed_apps.get(app_key)` are non-empty. Add `"degraded"` to `ManifestStatus`. No structural change to AppRegistry.

The status priority becomes: `disabled > blocked > degraded (running + failed) > running > failed > stopped`.

Optionally, add an `instance_health` summary field to `AppManifestInfo` (e.g., `running_count` and `failed_count`) to give consumers quick access to the breakdown without iterating `instances`.

**Pros**:
- Smallest change to AppRegistry itself -- no structural migration
- Directly solves the stated problem (partial failure visibility) with minimal blast radius
- `build_manifest_info()` change is ~5 lines
- Instance-level data already flows through the `instances` list in `AppManifestInfo` -- the only missing piece is the top-level status string

**Cons**:
- Preserves the dual-dict design debt (synchronization bugs, coarse `register_app` clear, duplicate accumulation in `record_failure`)
- Does not fix the `info_from_failure()` identity inconsistency (synthesized `instance_name`)
- Does not improve immutability alignment -- `_apps` and `_failed_apps` are still mutated in place
- Adds `"degraded"` to `ManifestStatus` (same API ripple as Option A, though smaller overall diff)
- `AppStatusSnapshot.running`/`.failed` split would still exist as a separate, parallel view of the same data

**Effort estimate**: Small. ~5 lines in `build_manifest_info()`, plus `ManifestStatus` update, frontend badge for `"degraded"`, and corresponding tests.

**Dependencies**: None.

### Option C: Keep dual-dict, surface partial failure through instance counts, no new status value

**How it works**: Leave `_apps`, `_failed_apps`, and `ManifestStatus` unchanged. Add two new fields to `AppManifestInfo` and `AppManifestResponse`:

```python
running_instance_count: int = 0
failed_instance_count: int = 0
```

These are already derivable from the `instances` list (by filtering on status), but adding them as top-level fields makes them queryable without iterating. The manifest-level `status` stays `"running"` for mixed-state apps, but the frontend can use these counts to show a warning badge or chip (e.g., "2/3 running").

**Pros**:
- No breaking API change -- existing `ManifestStatus` values unchanged
- Additive fields are backward-compatible
- Frontend can render "2/3 running" or a warning indicator without a new status concept
- Smallest backend change of all options
- Avoids the question of what "degraded" means semantically (is 1 failed out of 10 "degraded"? is 9 failed out of 10?)

**Cons**:
- The top-level `status` field still says `"running"` -- any consumer that filters/sorts by status will treat a partially-failed app the same as a fully-healthy one
- No structural improvement to the registry
- Dashboard/stats strips that count by status will still lump partially-failed apps into "running"
- Does not fix any of the underlying registry design debt

**Effort estimate**: Small. ~10 lines in `build_manifest_info()`, 2 new fields on `AppManifestInfo`/`AppManifestResponse`, frontend rendering.

**Dependencies**: None.

## Concerns

### Technical risks

- **`get_apps_by_key()` semantic change is the main risk for Option A**: Three callers (`shutdown_all`, `start_app`, `_fold_unblocked_apps_into_changes`) depend on this returning only running instances. If the unified dict changes this method to return all instances, these callers would attempt to shut down or iterate over `None`-app entries. Mitigation: keep `get_apps_by_key()` as running-only and add a separate `get_all_instances_by_key()`.

- **`ManifestStatus` addition (`"degraded"`)** is a wire-format change that ripples through: `web/models.py` (Literal type), generated TypeScript types, frontend badge/color mapping, `tally_manifest_statuses()`, `MANIFEST_STATUS_KEYS`, `AppFullSnapshot` (new `degraded: int` count field), `AppManifestListResponse` (new `degraded: int` count), and the dashboard stats strip. This is wider than it looks.

- **`register_app()` coarse clear** (Options B/C): The current behavior of clearing ALL failures for an app_key when any index is re-registered masks a real issue. If instance 0 is re-registered after a reload, instance 2's failure record vanishes. This is not a regression from Options B/C (it's pre-existing), but it limits their correctness.

### Complexity risks

- **Option A introduces a new type (`InstanceEntry`)** that wraps `App` with lifecycle metadata. This adds a layer of indirection: code that previously reached `registry._apps[key][idx]` to get an `App` now gets an `InstanceEntry` and must access `.app`. The wrapper must coexist with the `App` type (which already has its own `status` field), creating a question of which `status` is authoritative.

- **The `App.status` vs `InstanceEntry.status` duality** in Option A needs careful design. `App.status` is a mutable field on the `App` object that changes during its lifecycle (NOT_STARTED -> STARTING -> RUNNING -> ...). `InstanceEntry.status` would be the registry's view, set at registration/failure time. If they can disagree, consumers need to know which to trust. If they must agree, the entry must be replaced on every `App.status` transition, which is a broader change.

### Maintenance risks

- **Test migration cost for Option A**: ~160+ test call sites reference the current API. Even with backward-compatible method signatures, tests that directly manipulate `_apps` or `_failed_apps` (via mock attribute assignment) will all break.

- **Ongoing `"degraded"` semantics** (Options A/B): Once added, `"degraded"` must be handled everywhere that `ManifestStatus` is matched. This is a permanent API surface expansion.

## Per-Instance Reload Feasibility (Question 3)

Per-instance reload is tracked as issue #796 (open) with an explicit comment at `app_handler.py:37`. The current design is fundamentally per-app-key for all control operations:

- **What exists**: `unregister_app(app_key, index)` supports single-instance removal. `get(app_key, index)` supports single-instance lookup. DB natural keys are `(app_key, instance_index)`. CLI `resolve_instance()` maps names to indices.

- **What does not exist**: `start_app`, `stop_app`, and `reload_app` on `AppLifecycleService` all take only `app_key` with no instance targeting. `AppFactory.create_instances()` rebuilds all instances. `reconcile_app_registrations()` reconciles the whole app_key's listener/job DB rows at once. The web API endpoints are app-key-only.

- **What it would require**: Optional `index` parameter on `start_app`/`stop_app`/`reload_app`. `AppFactory.create_instances()` scoped to a single index. `reconcile_app_registrations()` scoped to instance-level. New web API endpoint `POST /apps/{app_key}/instances/{index}/reload`. A design decision on whether per-instance locks should replace per-app-key locks.

- **Assessment**: Per-instance reload is a real, multi-file feature. The data layer supports it, but the control plane does not. It is orthogonal to the registry unification proposed here -- the registry change makes it easier (cleaner instance state tracking) but is not a prerequisite. The two can be developed independently.

## Open Questions

- [ ] **Should `"degraded"` be a new `ManifestStatus` value, or should partial failure be communicated through counts/flags only?** Adding a status value has a wider API ripple but gives cleaner semantics for filtering/sorting. Counts/flags are additive and backward-compatible but leave the status field misleading.

- [ ] **For Option A, should `InstanceEntry.status` be authoritative over `App.status`?** If so, every `App.status` transition must update the entry. If not, the entry's status is only set at registration/failure time and may diverge from the live `App.status` during normal lifecycle transitions (STARTING -> RUNNING).

- [ ] **Should `record_failure()` preserve the user-configured `instance_name` from the manifest config?** The config is available in `AppManifest.app_config[index]` before the `App` object is constructed, so it could be extracted for the failure record. This would fix the identity inconsistency but requires threading the manifest through `record_failure()` or `AppFactory.create_instances()`.

- [ ] **Is the `register_app()` coarse clear (clearing all failures for an app_key when any index is re-registered) intentional or a bug?** If instance 0 is re-registered, should instance 2's failure record persist? The answer affects whether the unified dict approach needs per-index clearing.

- [ ] **Does the live config editing feature need per-instance reload, or is per-instance visibility sufficient?** This determines whether #796 is a dependency or just a related feature.

## Recommendation

**Option B (keep dual-dict, add `"degraded"` status) is the right first move for the stated motivation.** It directly solves the visibility problem with minimal risk and positions the codebase for Option A later.

The reasoning:

1. The stated motivation is "partial failure is invisible." Option B makes it visible with a ~5-line change to `build_manifest_info()`, plus the `ManifestStatus` addition and frontend badge. The frontend already has all the per-instance rendering infrastructure; it just needs the top-level signal.

2. Option A is a better long-term design, but its value is primarily in cleaning up registry internals (deduplication, immutability, single source of truth). Those benefits are real but not blocking the live config editing feature. The test migration cost (~160+ sites) makes it a multi-day effort that should be its own PR.

3. Option C (counts-only, no new status) avoids the `ManifestStatus` ripple but leaves the status field actively misleading. Consumers that filter by `status == "running"` will continue to treat partially-failed apps as healthy. This is the status quo's problem restated.

4. The `register_app()` coarse clear and `record_failure()` duplication issues are worth fixing but are independent of the visibility problem. They can be addressed alongside or after Option A.

Confidence: **Supported** -- multiple pieces of evidence converge: the frontend is ready for per-instance status, `build_manifest_info()` already constructs combined instance lists, and the only missing piece is the top-level status derivation. No single source states the design intent, but the architecture is clearly oriented toward per-instance granularity at the display layer while lacking it at the status-summary layer.

### Suggested next steps

1. **Implement Option B** as a focused PR: add `"degraded"` to `ManifestStatus`, update `build_manifest_info()` status derivation, add frontend badge rendering for the new status, update tests.

2. **File a follow-up issue for Option A** (registry unification) as a separate, non-blocking design improvement. Reference this brief and the identified debt (coarse clear, duplicate accumulation, immutability violation, `info_from_failure` identity inconsistency).

3. **Keep issue #796** (per-instance reload) as a separate track. The registry unification in Option A would make #796 cleaner to implement, but neither blocks the other.

4. **Fix the `register_app()` coarse clear** as part of either Option B or Option A -- this is a correctness bug where re-registering instance 0 silently discards instance 2's failure record.

5. **Dead code**: `iter_all_instances()` at `app_registry.py:136` has zero callers in production or tests. Remove it.
