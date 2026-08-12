# Context: Unify AppRegistry Instance Tracking

## Problem & Motivation

`AppRegistry` tracks running and failed app instances in two separate dicts (`_apps` and `_failed_apps`). A multi-instance app where one instance fails at startup shows `status: "running"` at the manifest level — the failure is hidden. This blocks the live config editing feature (another branch) which needs instance-level visibility. Secondary issues include: `register_app()` coarsely clearing all failures for an app_key when re-registering any index, `record_failure()` accumulating duplicates, `info_from_failure()` synthesizing instance names instead of using the real configured name, dead code (`clear_failures`, `iter_all_instances`), and `ManifestStatus` being defined in two places that can drift.

## Visual Artifacts

None.

## Key Decisions

1. **Unified `_instances` dict** — replace `_apps` + `_failed_apps` with `dict[str, dict[int, InstanceEntry]]`. `InstanceEntry` is a frozen dataclass with `app`, `status`, `error`, `error_message`, `error_traceback` fields and an `instance_name` property delegating to `self.app`. No `index` field — the dict key is the single source of truth.
2. **`ManifestStatus` as `StrEnum`** — move from `Literal` in `web/models.py` to `StrEnum` in `types/enums.py`. `MANIFEST_STATUS_KEYS = tuple(ManifestStatus)` — single source of truth.
3. **`"degraded"` status** — a new `ManifestStatus.DEGRADED` for apps with both running and failed instances. Priority: `disabled > blocked > degraded > running > failed > stopped`.
4. **`AppStatusSnapshot` collapse** — merge `.running`/`.failed` lists into single `.instances`. Count properties filter on `error is None` vs `error is not None`.
5. **`status_counts` dict** — replace individual count fields on `AppFullSnapshot` and `AppManifestListResponse` with `status_counts: dict[str, int]`.
6. **`unregister_app` clears all entries** — pops running + failed, returns only running `App` objects for shutdown. After stop, app shows "stopped" not "failed".
7. **`get_apps_by_key` → `get_running_apps`** — rename for clarity. New `get_instances()` returns all entries.
8. **`stop_app` lock fix** — wrap in per-app-key lock via internal unlocked methods to avoid deadlock in `reload_app`.
9. **Instance name from manifest config** — use `AppFactory.normalize_configs()` to bridge `dict|list[dict]` shape, look up `instance_name` for failed entries.
10. **Failure history lost on stop (accepted risk)** — cleared entries are in telemetry DB; surfacing them alongside "stopped" is a follow-up.

## Constraints & Anti-Patterns

- `InstanceEntry` must NOT store `index` or `instance_name` as fields — functional dependency on dict key / app reference.
- `get_running_apps()` must NOT return failed entries — callers (`shutdown_all`, `start_app`) call shutdown/initialize on the `App` objects.
- `__contains__` and `app_keys()` must NOT include app_keys with only failed entries — callers (`should_auto_reconcile`, `_fold_unblocked_apps_into_changes`) check if app is running.
- `reload_app` must NOT call `stop_app()`/`start_app()` directly — both acquire the lock, causing deadlock. Use `_stop_app_unlocked`/`_start_app_unlocked`.
- Non-goals: per-instance lifecycle (#796), frontend instance action buttons, `_blocked_apps` changes.

## Design Doc References

- `## Architecture` — InstanceEntry shape, registry storage, ManifestStatus enum, status derivation, snapshot collapse, lock fix pattern, status_counts
- `## Functional Requirements` — FR#1-FR#16 covering all behaviors
- `## Edge Cases` — all-failed, single-instance, re-registration, unregister clears all, failed-only stop, reload under lock
- `## Replacement Targets` — 13 items being replaced/deleted/renamed
- `## Test Strategy` — characterization tests, unit, integration, frontend unit; system/E2E not required
- `## Key Constraints` — 4 explicit prohibitions
- `## Dependencies and Assumptions` — InstanceEntry.status vs App.status semantics, asyncio.Lock reentrancy, failure history accepted risk

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
