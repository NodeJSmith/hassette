# Design: Unify AppRegistry Instance Tracking

**Date:** 2026-08-12
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-08-12-app-registry-unification/research.md

## Problem

A multi-instance app where one instance fails at startup looks identical to a fully healthy app with fewer instances. `AppRegistry` tracks running and failed instances in two separate dicts (`_apps` and `_failed_apps`), and the manifest-level status priority chain (`disabled > blocked > running > failed > stopped`) makes "running" mask "failed" when both coexist. The dashboard shows the app as healthy when it is not.

This blocks the live config editing feature (in progress on another branch), which needs instance-level visibility to make intelligent reload decisions. It also masks real startup failures in production — a user has to expand the app row and inspect individual instance statuses to discover that one of their instances never started.

Secondary issues in the same code:

- `register_app()` clears ALL failure records for an app_key when re-registering any single index (coarse clear — a correctness bug where re-registering instance 0 silently discards instance 2's failure record).
- `record_failure()` accumulates duplicate entries for the same `(app_key, index)` with no deduplication.
- `info_from_failure()` synthesizes `instance_name` as `f"{class_name}.{index}"` because the real name is lost when the `App` object was never constructed — an identity inconsistency between running and failed instances.
- `clear_failures()` and `iter_all_instances()` are dead code with zero production callers.
- `ManifestStatus` is defined as a `Literal` in `web/models.py` and a hand-maintained `MANIFEST_STATUS_KEYS` tuple in `app_snapshots.py` — two independent definitions of the same set, a drift invitation.
- `AppStatusSnapshot` splits instances into separate `.running` and `.failed` lists, mirroring the registry's dual-dict design downstream.
- `stop_app()` does not acquire the per-app-key lock, unlike `start_app()`.

## Goals

- **Partial failure is visible at the manifest level** — a multi-instance app with at least one running and one failed instance shows `ManifestStatus.DEGRADED`, not `"running"`.
- **Single source of truth** — one dict holds all instance state; no synchronization between parallel data structures.
- **Correctness bugs are fixed** — per-index failure clearing (not per-app_key), replacement semantics (not accumulation).
- **Instance identity preserved on failure** — failed instances show their configured `instance_name` from the manifest config, not a synthesized name.
- **Dead code removed** — `clear_failures()` and `iter_all_instances()` deleted.
- **Immutability compliance** — instance state transitions create new frozen entries via `dataclasses.replace()`.
- **Existing callers don't break** — `get_running_apps()` still returns running-only `App` objects; `get_instances()` exposes all entries (running and failed) as `dict[int, InstanceEntry]`.
- **`ManifestStatus` is a single source of truth** — one `StrEnum` in `types/enums.py` replaces the separate Literal and tuple.
- **`AppStatusSnapshot` unified** — `.running`/`.failed` lists collapsed into a single `.instances` list.
- **`stop_app` concurrency fixed** — wrapped in the per-app-key lock, consistent with `start_app`.

## Non-Goals

- Per-instance lifecycle operations (start/stop/reload with index parameter) — issue #796.
- Frontend instance-level action buttons (depends on #796).
- Changes to `_blocked_apps` dict — different concern, different lifecycle.
- `stop_app` lock reentrancy — `asyncio.Lock` is not reentrant by design; the internal-method extraction handles `reload_app`.

## User Scenarios

### Hassette User: App Author

- **Goal:** Understand why their multi-instance automation isn't fully running
- **Context:** Checking the hassette dashboard after deploying a config change

#### Partial failure diagnosis

1. **Opens the apps page**
   - Sees: app row shows `degraded` status badge (amber/warning), not `running`
   - Decides: expands the row to see instance details
   - Then: individual instances show their specific status (`RUNNING` or `FAILED` with error message)

### Framework: AppRegistry

- **Goal:** Track instance state with a single source of truth
- **Context:** App startup, failure recording, shutdown, snapshot generation

#### Instance lifecycle

1. **App instance created successfully (`register_app`)**
   - Entry: `InstanceEntry(app=app_instance, status=RUNNING)`, keyed by `(app_key, index)` in `_instances`
   - If an entry already exists at that key, it is replaced (not accumulated alongside)

2. **App instance fails at startup (`record_failure`)**
   - Entry: `InstanceEntry(app=None, status=FAILED, error=exc, ...)`, keyed by `(app_key, index)`
   - If a running entry exists at that key, it is replaced (the running app is removed)
   - No duplicates accumulate — dict keying enforces one entry per `(app_key, index)`

3. **Snapshot requested (`get_snapshot`, `build_manifest_info`)**
   - Iterates `_instances[app_key].items()`, using the dict key as the index
   - For running entries: reads `entry.app.status` for the live lifecycle status, `entry.instance_name` (property → `entry.app.app_config.instance_name`) for identity
   - For failed entries: uses `entry.status` (always `FAILED`), looks up `instance_name` from `self._manifests[app_key].app_config[index]`

## Functional Requirements

- **FR#1** `AppRegistry` stores all instance state (running and failed) in a single `dict[str, dict[int, InstanceEntry]]` keyed by `(app_key, index)`.
- **FR#2** `InstanceEntry` is a frozen dataclass with fields `app`, `status`, `error`, `error_message`, `error_traceback` and a property `instance_name` that delegates to `self.app.app_config.instance_name` (returning `None` when `app is None`).
- **FR#3** `register_app(app_key, index, app)` creates an `InstanceEntry(app=app, status=ResourceStatus.RUNNING)` and stores it at `_instances[app_key][index]`, replacing any prior entry at that key.
- **FR#4** `record_failure(app_key, index, error)` creates an `InstanceEntry(app=None, status=ResourceStatus.FAILED, error=error, ...)` and stores it at `_instances[app_key][index]`, replacing any prior entry at that key (including a running entry — the app reference is discarded).
- **FR#5** `build_manifest_info()` derives `ManifestStatus.DEGRADED` when an app_key has at least one running entry and at least one failed entry in `_instances`.
- **FR#6** `ManifestStatus` is a `StrEnum` in `types/enums.py` with values `DISABLED`, `BLOCKED`, `DEGRADED`, `RUNNING`, `FAILED`, `STOPPED`. `MANIFEST_STATUS_KEYS` is derived from it via `tuple(ManifestStatus)`.
- **FR#7** `AppStatusSnapshot` has a single `instances: list[AppInstanceInfo]` field (no separate `running`/`failed` lists). Count properties (`running_count`, `failed_count`, `running_apps`, `failed_apps`) are computed by filtering on `error is None` (running) vs `error is not None` (failed) — reproducing the current list-membership semantics, since a running entry's live `AppInstanceInfo.status` may be any `ResourceStatus` value (`STARTING`, `STOPPING`, etc.), not just `RUNNING`.
- **FR#8** `get_running_apps(app_key)` returns only entries where `entry.app is not None` (backward-compatible running-only semantics).
- **FR#9** `stop_app()` acquires the per-app-key lock before unregistering and shutting down instances.
- **FR#10** `clear_failures()` and `iter_all_instances()` are removed (dead code — zero production callers).
- **FR#11** For failed instances in snapshot output, `instance_name` is sourced from the manifest config (via `AppFactory.normalize_configs()` to handle the `dict | list[dict]` shape), not synthesized.
- **FR#12** `__contains__` and `app_keys()` consider only entries where `entry.app is not None` (running instances — backward-compatible with callers like `should_autostart`).
- **FR#13** A `get_instances(app_key)` method returns all entries (running and failed) as `dict[int, InstanceEntry]` — the all-instances accessor that replaces the deleted `iter_all_instances()`.
- **FR#14** `RuntimeQueryService.collect_boot_issues()` treats `ManifestStatus.DEGRADED` the same as `"failed"` for boot-issue surfacing — a partially-failed app is a boot issue.
- **FR#15** `AppFullSnapshot` and `AppManifestListResponse` use a single `status_counts: dict[str, int]` field (keyed by `ManifestStatus` values) instead of individual `running: int`, `failed: int`, etc. fields. `tally_manifest_statuses()` returns this dict directly — no field enumeration, no drift.
- **FR#16** `unregister_app(app_key)` pops ALL entries (running and failed) from `_instances[app_key]`. Returns only `App` objects from running entries as `dict[int, App]` for shutdown. `unregister_app(app_key, index)` pops only the single entry at that index.

## Edge Cases

- **All instances failed** — `build_manifest_info` returns `ManifestStatus.FAILED` (not `DEGRADED`), matching current behavior.
- **Single-instance app fails** — equivalent to all-failed; status is `FAILED`.
- **Re-registration after failure** — `register_app(key, 0, app)` replaces only the entry at index 0. Other indices' failure records are preserved (fixes the coarse-clear bug).
- **`record_failure` for a running instance** — the running entry at that index is replaced with a failed entry. The `App` reference is discarded from the registry (callers must have already shut it down or it crashed).
- **`unregister_app` clears all entries** — `unregister_app(app_key)` pops ALL entries for the app_key (running and failed) from `_instances`. Returns only the `App` objects from running entries (where `entry.app is not None`) as `dict[int, App]` for the caller to shut down. Failed entries are discarded — they have no `App` to shut down. After stop, `build_manifest_info()` sees no entries → derives `"stopped"`. This fixes the current behavior where failed entries persist after a stop and the app shows as `"failed"` instead of `"stopped"`.
- **`unregister_app` with index** — `unregister_app(app_key, index)` pops only the single entry at that index. Returns `{index: app}` if the entry was running, `None` otherwise (preserving the current `dict[int, App] | None` return type).
- **Failed entry with no manifest config** — if `self._manifests` has no entry for the app_key (removed-from-config app), `instance_name` for failed entries falls back to `f"{class_name}.{index}"` (the current synthesized name).
- **`reload_app` under the lock** — `reload_app` acquires the per-app-key lock once and calls internal unlocked methods (`_stop_app_unlocked`, `_start_app_unlocked`) to avoid deadlock on the non-reentrant `asyncio.Lock`.
- **Stopping a failed-only app** — an app with only failed instances (no running ones) returns `{}` from `unregister_app` (running subset is empty). The existing `if not instances: warn("not found")` guard in `stop_app` would log a misleading warning despite the failed entries being cleared. Adjust the guard to distinguish "no entries existed at all" (truly not found) from "entries existed but none were running" (cleared, no shutdown needed).
- **Concurrent `stop_app` and `start_app`** — both acquire the same per-app-key lock, so they serialize. Previously `stop_app` was unprotected.

## Acceptance Criteria

- **AC#1** A test registers 3 instances for an app_key, records failure for index 0, and asserts `build_manifest_info().status == "degraded"` — verifies FR#5.
- **AC#2** A test calls `register_app(key, 0, app)` after `record_failure(key, 2, error)` and asserts the failure record for index 2 is still present — verifies FR#3/FR#4 per-index clearing.
- **AC#3** A test calls `record_failure(key, 0, err1)` then `record_failure(key, 0, err2)` and asserts only one entry exists at `(key, 0)` with `err2` — verifies dedup via FR#4.
- **AC#4** `get_running_apps()` returns only entries with `app is not None` when failed entries exist for the same app_key — verifies FR#8.
- **AC#5** `AppStatusSnapshot` has no `.running` or `.failed` attributes; `.instances` contains all entries; `.running_count` and `.failed_count` return correct filtered counts — verifies FR#7.
- **AC#6** `prek -a && prek pyright -a --stage pre-push` passes with no errors — verifies type consistency.
- **AC#7** `ManifestStatus` is importable from `hassette.types.enums` and `tuple(ManifestStatus)` matches `MANIFEST_STATUS_KEYS` — verifies FR#6.
- **AC#8** Frontend `statusToVariant("degraded")` returns `"warning"` and `statusToKind("degraded")` returns `"warn"` — verifies frontend status map update.
- **AC#9** Failed instance snapshot entries show the configured `instance_name` from manifest config (not `ClassName.N`) when the manifest is available — verifies FR#11.
- **AC#10** `clear_failures` and `iter_all_instances` do not exist in the codebase — verifies FR#10.

## Key Constraints

- `InstanceEntry` must NOT store `index` or `instance_name` as fields — both are functional dependencies on the dict key / app reference that invite drift. `index` comes from the dict key; `instance_name` is a property delegating to `self.app`.
- `get_running_apps()` must NOT return failed entries — callers (`shutdown_all`, `start_app`) iterate results and call shutdown/initialize on the `App` objects. Failed entries have `app=None`.
- `__contains__` and `app_keys()` must NOT include app_keys that only have failed entries — callers (`should_auto_reconcile`, `_fold_unblocked_apps_into_changes`) use these to check if an app is already running.
- `reload_app` must NOT call `stop_app()` / `start_app()` directly after the lock fix — both public methods acquire the lock, causing deadlock. Use internal unlocked methods.

## Dependencies and Assumptions

- The `status` field on `InstanceEntry` is the registry's category (RUNNING or FAILED), not the app's live lifecycle state. For running entries, snapshot builders read `entry.app.status` for the live `ResourceStatus`. These two can temporarily disagree (e.g., an app transitioning to STOPPING still has `entry.status == RUNNING` until `unregister_app` removes it). This is accepted because the registry's role is to track "is this entry a running instance or a failed startup" — the app's own lifecycle state machine handles the rest.
- `asyncio.Lock` is not reentrant. The internal-method extraction pattern (`_stop_app_unlocked` / `_start_app_unlocked`) is the standard solution.
- **Failure history lost on stop (accepted risk)** — `unregister_app` clears failed entries on stop, so the dashboard shows `"stopped"` instead of `"failed"`. Mitigation: the telemetry DB already persists failure events, so history isn't lost — it's just not surfaced alongside the stopped status. A follow-up could query recent DB failures for stopped apps.

## Architecture

### InstanceEntry

A frozen dataclass, private to `app_registry.py`:

```python
@dataclass(frozen=True)
class InstanceEntry:
    app: App[AppConfig] | None
    status: ResourceStatus
    error: Exception | None = None
    error_message: str | None = None
    error_traceback: str | None = None

    @property
    def instance_name(self) -> str | None:
        return self.app.app_config.instance_name if self.app else None
```

No `index` field — the dict key `_instances[app_key][index]` is the single source of truth. No stored `instance_name` — delegated to the `App` object via property, returning `None` for failed entries.

### Registry storage

Replace `_apps: dict[str, dict[int, App]]` and `_failed_apps: dict[str, list[tuple[int, Exception]]]` with:

```python
self._instances: dict[str, dict[int, InstanceEntry]] = defaultdict(dict)
```

`_blocked_apps` is unchanged — different concern, different lifecycle.

### ManifestStatus enum

Move from `Literal` in `web/models.py` to `StrEnum` in `types/enums.py`:

```python
class ManifestStatus(StrEnum):
    DISABLED = "disabled"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    RUNNING = "running"
    FAILED = "failed"
    STOPPED = "stopped"
```

`MANIFEST_STATUS_KEYS` in `app_snapshots.py` becomes `tuple(ManifestStatus)`. `web/models.py` imports and uses the enum directly.

### Status derivation in build_manifest_info

The priority chain becomes:

```
disabled > blocked > degraded (has_running AND has_failed) > running > failed > stopped
```

`has_running` and `has_failed` are derived from `_instances[app_key]` by checking `entry.app is not None` and `entry.status == FAILED` respectively.

### AppStatusSnapshot collapse

`AppStatusSnapshot` fields change from:

```python
running: list[AppInstanceInfo]
failed: list[AppInstanceInfo]
```

to:

```python
instances: list[AppInstanceInfo]
```

Count properties (`running_count`, `failed_count`, `running_apps`, `failed_apps`, `total_count`) are preserved as computed properties that filter `.instances` by status. The `app_status_response_from` mapper in `web/mappers.py` already merges `running + failed` into one list (line 61) — it simplifies to reading `.instances` directly.

### Instance name resolution for failed entries

For failed entries where `entry.app is None`, `instance_name` is resolved at snapshot-build time from the manifest config. `AppManifest.app_config` is typed `dict[str, Any] | list[dict[str, Any]]` — a plain dict when configured via flat/extra fields, a list when configured via nested `config:` key. Use `AppFactory.normalize_configs()` to bridge this before indexing:

```python
manifest = self._manifests.get(app_key)
if manifest:
    configs = AppFactory.normalize_configs(manifest.app_config)
    if index < len(configs):
        instance_name = configs[index].get("instance_name", f"{manifest.class_name}.{index}")
    else:
        instance_name = f"{manifest.class_name}.{index}"
else:
    instance_name = f"Unknown.{index}"  # fallback for removed-from-config apps
    # class_name also falls back to "Unknown" (matching info_from_failure's default)
```

When building `AppInstanceInfo` from a failed entry, `class_name` comes from `manifest.class_name` when the manifest exists, or `"Unknown"` otherwise (matching the current `info_from_failure(class_name: str = "Unknown")` default). `normalize_configs()` is a static method on `AppFactory` — it can be called without an `AppFactory` instance.

### stop_app lock fix

Extract internal unlocked methods:

- `_stop_app_unlocked(app_key)` — the current `stop_app` body
- `_start_app_unlocked(app_key, ...)` — the current `start_app` body (minus admission check, which stays outside the lock)

Public methods acquire the lock and delegate:

```python
async def stop_app(self, app_key):
    async with self._get_app_key_lock(app_key):
        await self._stop_app_unlocked(app_key)

async def reload_app(self, app_key, ...):
    await self._admit_start(...)
    async with self._get_app_key_lock(app_key):
        await self._stop_app_unlocked(app_key)
        await self._start_app_unlocked(app_key, ...)
```

### AppFullSnapshot and AppManifestListResponse

Replace the individual count fields (`running: int`, `failed: int`, `stopped: int`, `disabled: int`, `blocked: int`) on both `AppFullSnapshot` (dataclass) and `AppManifestListResponse` (Pydantic model) with a single `status_counts: dict[str, int]` field. `tally_manifest_statuses()` returns this dict directly — keyed by `ManifestStatus` values, automatically includes any new status without field changes.

The mapper `app_manifest_list_response_from()` in `web/mappers.py` passes `status_counts=full.status_counts` instead of enumerating individual fields. Note: the frontend `apps.tsx` computes `statusCounts` locally from per-app manifest status — it does not consume `AppManifestListResponse`'s count fields. The `status_counts` field serves API consumers and the CLI.

### Boot issue detection

`RuntimeQueryService.collect_boot_issues()` at `runtime_query_service.py:385` checks `manifest.status == "failed"`. Update the condition to also match `"degraded"` — a partially-failed app with error information is a boot issue that should be surfaced to the user.

### Frontend

Add `"degraded"` to:
- `APP_STATUS_MAP`: `["degraded", "warning"]`
- `STATUS_KIND_MAP`: `["degraded", "warn"]`
- `FILTER_OPTIONS` in `apps.tsx`
- `statusCounts` fixed-key initializer in `apps.tsx` (line 64 — add `degraded: 0`; the dynamic builder at line 197 already handles any status value via `??`)
- `AppStatus` type union in `status.ts`

`"degraded"` is its own filter — filtering by "running" shows only fully-healthy apps.

## Implementation Preferences

- Frozen dataclasses for `InstanceEntry` (project immutability convention). State transitions (`register_app`, `record_failure`) construct new entries and assign to the dict key — wholesale replacement, not `dataclasses.replace()` off a prior entry, since no fields carry over between states.
- `StrEnum` in `types/enums.py` for `ManifestStatus` (matches `ResourceStatus` pattern).
- Schema regeneration via `uv run python scripts/export_schemas.py --types` after model changes.
- `overlay_runtime_state()` continues as the single overlay function web routes call — it delegates to `build_manifest_info()`, which inherits the status derivation change.

## Replacement Targets

| Target | Location | Replacement | Action |
|---|---|---|---|
| `_apps: dict[str, dict[int, App]]` | `app_registry.py:32` | `_instances: dict[str, dict[int, InstanceEntry]]` | Remove |
| `_failed_apps: dict[str, list[tuple[int, Exception]]]` | `app_registry.py:33` | Same unified dict | Remove |
| `clear_failures()` | `app_registry.py:80-85` | Dead code | Delete |
| `iter_all_instances()` | `app_registry.py:136-138` | Dead code | Delete |
| `info_from_failure()` synthesized name | `app_registry.py:156` | Manifest config lookup | Replace inline |
| `ManifestStatus` Literal | `web/models.py:25` | `StrEnum` import from `types/enums.py` | Replace with import |
| `MANIFEST_STATUS_KEYS` tuple | `app_snapshots.py:13` | `tuple(ManifestStatus)` | Replace with derivation |
| `AppManifestInfo.status` inline comment | `app_snapshots.py:74` | Update comment to include `"degraded"` | Update |
| `AppStatusSnapshot.running`/`.failed` | `app_snapshots.py:35-36` | Single `.instances` list | Replace |
| `get_apps_by_key()` | `app_registry.py:132` | Renamed to `get_running_apps()` — makes filtering explicit | Rename + migrate 2 production callers + 1 test util |
| `AppFullSnapshot` individual count fields | `app_snapshots.py:95-99` | Single `status_counts: dict[str, int]` field | Replace |
| `AppManifestListResponse` individual count fields | `web/models.py:172-176` | Single `status_counts: dict[str, int]` field | Replace |
| `app_manifest_list_response_from()` field enumeration | `web/mappers.py:105-109` | `status_counts=full.status_counts` | Replace |

## Convention Examples

### Frozen dataclass pattern

**Source:** `src/hassette/schemas/app_snapshots.py`

```python
@dataclass
class AppInstanceInfo:
    app_key: str
    index: int
    instance_name: str
    class_name: str
    status: ResourceStatus
    error: Exception | None = None
    error_message: str | None = None
    error_traceback: str | None = None
    owner_id: str | None = None
```

`InstanceEntry` follows this shape but is `frozen=True` and omits identity fields (index, instance_name) that are derivable from the dict key and app reference.

### StrEnum in types/enums.py

**Source:** `src/hassette/types/enums.py`

```python
class ResourceStatus(StrEnum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    CRASHED = "crashed"
    SHUTTING_DOWN = "shutting_down"
    EXHAUSTED_DEAD = "exhausted_dead"
    EXHAUSTED_COOLING = "exhausted_cooling"
```

`ManifestStatus` follows this pattern — `StrEnum` with lowercase string values.

### Status mapping convention

**Source:** `frontend/src/utils/status.ts`

```typescript
const APP_STATUS_MAP: ReadonlyMap<string, StatusVariant> = new Map<string, StatusVariant>([
  ["running", "success"],
  ["failed", "danger"],
  // ...
]);

const STATUS_KIND_MAP: ReadonlyMap<string, StatusKind> = new Map<string, StatusKind>([
  ["running", "ok"],
  ["failed", "err"],
  // ...
]);
```

Add `["degraded", "warning"]` to `APP_STATUS_MAP` and `["degraded", "warn"]` to `STATUS_KIND_MAP`.

### Registry method signatures

**Source:** `src/hassette/core/app_registry.py`

```python
def register_app(self, app_key: str, index: int, app: "App[AppConfig]") -> None:
def record_failure(self, app_key: str, index: int, error: Exception) -> None:
def get_running_apps(self, app_key: str) -> dict[int, "App[AppConfig]"]:  # renamed from get_apps_by_key
def get_instances(self, app_key: str) -> dict[int, InstanceEntry]:  # new — all entries
```

`register_app` and `record_failure` signatures unchanged. `get_apps_by_key` renamed to `get_running_apps` (2 production callers + 1 test util to migrate). `get_instances` is new.

## Alternatives Considered

### Option B: Keep dual-dict, add "degraded" status in derivation only

Change only `build_manifest_info()` to derive `"degraded"` when both `_apps` and `_failed_apps` have entries for the same app_key. ~5 lines changed, smallest possible fix.

**Rejected because:** preserves the dual-dict design debt (synchronization bugs, coarse clear, duplicate accumulation, identity inconsistency). Would unblock the config editing feature but leave the same class of bugs in place for the next consumer. The user chose to fix the root cause.

### Option C: Counts only, no new status value

Add `running_instance_count` and `failed_instance_count` to `AppManifestInfo` without adding a `"degraded"` status. The manifest-level `status` stays `"running"` for mixed-state apps.

**Rejected because:** the top-level `status` field remains actively misleading. Consumers that filter or sort by status treat partially-failed apps as healthy. The count fields help display but don't fix the semantic gap.

## Test Strategy

### Required Test Types

- **Unit** — `InstanceEntry` frozen dataclass, new registry methods, `"degraded"` status derivation, coarse-clear fix, dedup fix, instance_name preservation.
- **Integration** — registry → snapshot → mapper → web response chain (the `AppStatusSnapshot` collapse changes the data shape flowing through mappers).
- **Frontend unit** — `"degraded"` in `statusToVariant()`, `statusToKind()`, filter options.
- **System/E2E: not required** — existing CI suites exercise the app status pipeline end-to-end; this change adds a new status value through existing paths.

### Existing Tests to Adapt

- `tests/unit/core/test_app_registry.py` (~584 lines) — all tests reference `_apps`/`_failed_apps` directly or via `register_app`/`record_failure`. Tests for `clear_failures` must be removed. Tests for `get_snapshot` and `get_full_snapshot` must be updated for the new snapshot shape.
- `tests/unit/core/test_overlay_runtime_state.py` — tests the overlay function; may reference `ManifestStatus` Literal.
- `tests/integration/web_api/` — web API tests that assert on response shapes with `running`/`failed` count fields.
- `src/hassette/test_utils/web_mocks.py` — mocks `get_full_snapshot`.
- `src/hassette/test_utils/web_manifest_helpers.py` — `make_manifest()` factory uses `ManifestStatus` Literal.
- `frontend/src/` — any test files that reference the 5-value status set.
- `tests/e2e/mock_fixtures.py` — sets `registry.iter_all_instances.return_value` (orphaned mock for deleted method).

### New Test Coverage

- **Characterization tests** (before refactor) — pin `get_snapshot()`, `get_full_snapshot()`, and `build_manifest_info()` output shapes (FR#1-FR#5).
- **Degraded status derivation** — mixed running/failed → `"degraded"`; all-failed → `"failed"`; all-running → `"running"` (FR#5).
- **Per-index clearing** — register at index 0 after failure at index 2 → index 2's failure preserved (FR#3, FR#4).
- **Dedup on record_failure** — two failures at same index → one entry with last error (FR#4).
- **Instance name from manifest** — failed entry snapshot shows configured name, not synthesized (FR#11).
- **Unified snapshot shape** — `AppStatusSnapshot.instances` contains both running and failed; no `.running`/`.failed` attributes (FR#7).
- **Frontend status maps** — `"degraded"` maps to `"warning"` variant and `"warn"` kind (AC#8).

### Tests to Remove

- Tests for `clear_failures()` — dead code being deleted (FR#10).
- Tests for `iter_all_instances()` — dead code being deleted (FR#10).

## Documentation Updates

- No docs site pages document `AppRegistry` internals or `ManifestStatus` — these are framework internals, not user-facing API.
- If `"degraded"` is visible in the dashboard UI, the docs site screenshots may need regeneration: `uv run python scripts/capture_screenshots.py --only web_ui_apps` (only if the apps page visually changes).
- `CLAUDE.md` may need an update to the Architecture section's `ManifestStatus` references if any exist.

## Impact

<!-- Gap check 2026-08-12: 21 gaps included — schemas/__init__.py → T01, cli/client.py+cli/commands/app.py → T03, test_ws_endpoint.py+web_api/conftest.py+test_mappers.py+test_runtime_query_service.py+test_app_factory_lifecycle.py → T03, test_model_types.py → T01, test_app_lifecycle.py+test_app_lifecycle_service.py+test_app_lifecycle_service_coverage.py+test_app_lifecycle_service_operations.py+conftest.py → T04, test_cli_smoke.py+test_commands_app.py → T03, frontend factories.ts+handlers.ts+use-manifests.test.ts → T05, endpoints.ts → T03 (auto-generated) -->

### Changed Files

**Shared / cross-cutting:**
- `src/hassette/types/enums.py` — create: `ManifestStatus` StrEnum
- `src/hassette/schemas/app_snapshots.py` — modify: `MANIFEST_STATUS_KEYS` derived from enum; `AppStatusSnapshot` unified; `AppFullSnapshot` individual count fields replaced with `status_counts: dict[str, int]`; `tally_manifest_statuses` inherits via MANIFEST_STATUS_KEYS
- `frontend/src/utils/status.ts` — modify: add `"degraded"` to maps, `AppStatus` type
- `frontend/src/api/generated-types.ts` — modify: regenerated (auto)
- `frontend/src/api/ws-types.ts` — modify: regenerated (auto)

**Core:**
- `src/hassette/core/app_registry.py` — modify: `InstanceEntry` dataclass, unified `_instances` dict, updated methods, delete `clear_failures`/`iter_all_instances`
- `src/hassette/core/app_lifecycle_service.py` — modify: `stop_app` lock, extract `_stop_app_unlocked`/`_start_app_unlocked`, update `reload_app`
- `src/hassette/core/app_handler.py` — modify: passthrough changes for snapshot shape (if any)

**Web layer:**
- `src/hassette/web/models.py` — modify: import `ManifestStatus` from `types/enums.py` instead of defining Literal; replace individual count fields on `AppManifestListResponse` with `status_counts: dict[str, int]`
- `src/hassette/web/mappers.py` — modify: simplify `app_status_response_from` (read `.instances` instead of merging `.running + .failed`); replace field enumeration in `app_manifest_list_response_from` with `status_counts=full.status_counts`
- `src/hassette/web/routes/apps.py` — modify: change `**tally_manifest_statuses(manifest_infos)` unpacking to `status_counts=tally_manifest_statuses(manifest_infos)`
- `src/hassette/core/runtime_query_service.py` — modify: `collect_boot_issues()` condition to include `"degraded"` alongside `"failed"`

**Frontend:**
- `frontend/src/pages/apps.tsx` — modify: add `"degraded"` to filter options, local `statusCounts` initializer, and summary `cells` array (cells are computed locally, not from API response count fields)

**Test utilities:**
- `src/hassette/test_utils/web_manifest_helpers.py` — modify: update `ManifestStatus` import source; update `make_manifest_list_response` and `make_full_snapshot` for `status_counts` field
- `src/hassette/test_utils/web_mocks.py` — modify: update snapshot mock shape

**Tests:**
- `tests/unit/core/test_app_registry.py` — modify: update for unified storage, add characterization tests, remove `clear_failures`/`iter_all_instances` tests
- `tests/unit/core/test_overlay_runtime_state.py` — modify: update `ManifestStatus` references
- Integration and web API test files — modify: update snapshot/response shape assertions

**Schema/types:**
- `openapi.json` — modify: regenerated
- `ws-schema.json` — modify: regenerated

### Behavioral Invariants

- `get_running_apps()` returns only running instances (callers depend on this for shutdown/initialize iteration).
- `__contains__` and `app_keys()` report only app_keys with running instances.
- `all_apps()` returns only running `App` objects.
- `get(app_key, index)` returns `App | None` (not `InstanceEntry`) — callers expect the `App` object directly.
- `AppStatusResponse` wire format fields (`running: int`, `failed: int`, `apps: list`) are preserved — counts derived from filtered unified list.
- `overlay_runtime_state()` behavior unchanged — delegates to `build_manifest_info()` which inherits the status derivation change.

### Blast Radius

- **Web API consumers** — `AppManifestResponse.status` can now be `"degraded"`. Frontend handles it via the updated status maps. External API consumers (if any) would see a new status value.
- **CLI** — `hassette app` and `hassette status` output may show `"degraded"` status. No code change needed in the CLI — it displays whatever status the API returns.
- **seed_db.py** — existing scenarios don't exercise mixed running/failed state. A "degraded" scenario could be added as a follow-up.

## Open Questions

None — all resolved or accepted.
