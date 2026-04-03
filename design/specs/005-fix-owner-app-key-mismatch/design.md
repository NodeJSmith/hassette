# Design: Fix owner_id/app_key mismatch in job and listener recording

**Date:** 2026-03-15
**Status:** archived
**Spec:** design/specs/005-fix-owner-app-key-mismatch/spec.md

## Problem

`Listener.owner` and `ScheduledJob.owner` store the resource's `owner_id` (unique_name, e.g., `"MyApp.MyApp.0"`), but `BusService.add_listener()` and `SchedulerService.add_job()` pass this value as `app_key` when creating DB registration records. The DB schema expects a configuration-level key (e.g., `"my_app"`), so `TelemetryQueryService` queries like `WHERE app_key = ? AND instance_index = ?` never match. Additionally, `instance_index` is hardcoded to `0` regardless of the actual App instance index.

This causes all job and listener filters in the web UI partials and the API endpoint to silently return empty results.

## Non-Goals

- Database migration for historical rows (UPSERT self-corrects on restart)
- Changes to session lifecycle or session recording
- Changes to TelemetryQueryService SQL queries (they're already correct)
- UI redesign of job or listener views
- Cleaning up `ListenerMetrics` (may be dead code, but out of scope)

## Architecture

### Core change: Add explicit identity fields to dataclasses

Add `app_key: str` and `instance_index: int` fields to both `Listener` (in `src/hassette/bus/listeners.py`) and `ScheduledJob` (in `src/hassette/scheduler/classes.py`). Rename the existing `owner` field to `owner_id` on both classes for clarity.

**Why two separate identity concepts?**
- `owner_id` (unique_name, e.g., `"MyApp.MyApp.0"`) — in-memory ownership key for Router/Queue operations (listener removal, job cancellation). Must be unique per instance. Used by `Router.owners`, `_ScheduledJobQueue.remove_owner()`.
- `app_key` + `instance_index` — DB identity for telemetry queries. Shared across restarts, matches hassette.toml config key. Used by `TelemetryQueryService` queries.

### Propagation path

```
App (has app_key, index)
  └─ Bus (reads parent.app_key, parent.index)
       └─ Listener.create(owner_id=self.owner_id, app_key=self.parent.app_key, instance_index=self.parent.index)
  └─ Scheduler (reads parent.app_key, parent.index)
       └─ ScheduledJob(owner_id=self.owner_id, app_key=self.parent.app_key, instance_index=self.parent.index)
```

`Bus` and `Scheduler` resolve `app_key` and `instance_index` from their parent `App` at listener/job creation time. Since both resources always have an `App` parent in normal operation, this is safe. For non-App parents (see below), registration is skipped.

### Registration fix

In `BusService.add_listener()` (`src/hassette/core/bus_service.py` line ~86):
```
ListenerRegistration(
    app_key=listener.app_key,           # was: listener.owner
    instance_index=listener.instance_index,  # was: 0
    ...
)
```

Same pattern in `SchedulerService.add_job()` (`src/hassette/core/scheduler_service.py` line ~171).

### Non-App owner guard

`RuntimeQueryService` creates its own `Bus` child whose parent is not an `App`. For these cases:
- `Bus` and `Scheduler` set `app_key=""` and `instance_index=0` when the parent is not an `App` (checked via `isinstance(self.parent, App)` or `hasattr(self.parent, 'app_key')`)
- `BusService.add_listener()` skips DB registration when `listener.app_key` is empty
- Same guard in `SchedulerService.add_job()`

This is correct because internal listeners are not useful telemetry — nobody queries for them.

### Web layer filter fix

**Partials** (`src/hassette/web/ui/partials.py`): The three broken filters (`scheduler_jobs_partial`, `app_detail_jobs_partial`, `instance_jobs_partial`) currently compare `j.owner == app_key`. These must adopt the pattern already used in `router.py`: resolve `owner_id` from `AppManifest.instances` and compare `j.owner_id == owner_id`.

However, the partials receive `app_key` as a query parameter and don't have direct access to AppManifest instances. Two sub-options:

1. **Look up owner_id from AppManifest** — partials accept a new `RuntimeDep` or `HassetteState` dependency to resolve `app_key` + `instance_index` → `owner_id`.
2. **Add app_key to ScheduledJob and filter on that** — since we're adding `app_key` to ScheduledJob, the partials can filter `j.app_key == app_key` directly.

**Option 2 is simpler and directly correct.** The partials filter on `j.app_key == app_key` (and optionally `j.instance_index == instance_index` for instance-level filtering). This avoids adding new dependencies to the partial routes.

**API route** (`src/hassette/web/routes/scheduler.py`): Same fix — filter on `j.app_key == app_key` instead of `j.owner == app_key`.

**Pages** (`src/hassette/web/ui/router.py` lines ~105, ~147): Already fixed in PR #334 using `owner_id`. Update `j.owner` to `j.owner_id` for the rename.

### Rename scope

| Class | Old field | New field |
|-------|-----------|-----------|
| `Listener` | `.owner` | `.owner_id` |
| `ScheduledJob` | `.owner` | `.owner_id` |
| `ListenerMetrics` | `.owner` | `.owner_id` |
| `ScheduledJobResponse` | `.owner` | `.owner_id` |
| `JobExecutionResponse` | `.owner` | `.owner_id` |

All references in production code, tests, and web templates must be updated.

## Alternatives Considered

### Option B: Resolve app_key at registration time in BusService/SchedulerService

Keep Listener/ScheduledJob dataclass shapes unchanged. At registration time, BusService looks up the App from the Hassette instance using the owner_id to find the matching app_key and index.

**Rejected because:** Requires a lookup mechanism that doesn't exist (parsing unique_name strings is fragile, and a reverse lookup registry adds complexity). The registration happens asynchronously, making correctness harder to verify. Non-App owners need special handling either way.

### Option C: Fix only the registration, skip the rename

Keep the field named `owner` and only fix the registration values and web filters.

**Rejected because:** The ambiguous field name is the root cause of the bug. Future developers will make the same mistake. The TODO comments in the codebase explicitly request the rename.

## Open Questions

None — all questions resolved during planning interrogation.

## Impact

### Files modified (production)

| File | Change |
|------|--------|
| `src/hassette/bus/listeners.py` | Rename `.owner` → `.owner_id`, add `app_key`, `instance_index` fields |
| `src/hassette/bus/bus.py` | Pass `app_key`, `instance_index` from parent App when creating Listener |
| `src/hassette/bus/metrics.py` | Rename `ListenerMetrics.owner` → `.owner_id` |
| `src/hassette/scheduler/classes.py` | Rename `.owner` → `.owner_id`, add `app_key`, `instance_index` fields |
| `src/hassette/scheduler/scheduler.py` | Pass `app_key`, `instance_index` from parent App when creating ScheduledJob |
| `src/hassette/core/bus_service.py` | Use `listener.app_key`/`.instance_index` in registration; skip if empty; rename `.owner` refs |
| `src/hassette/core/scheduler_service.py` | Use `job.app_key`/`.instance_index` in registration; skip if empty; rename `.owner` refs |
| `src/hassette/web/models.py` | Rename response model `.owner` → `.owner_id` |
| `src/hassette/web/ui/partials.py` | Fix 3 filters to use `j.app_key == app_key`; remove TODO comments |
| `src/hassette/web/ui/router.py` | Update `j.owner` → `j.owner_id` |
| `src/hassette/web/ui/context.py` | Update `job_to_dict()` to use `job.owner_id` |
| `src/hassette/web/routes/scheduler.py` | Fix filter to use `j.app_key == app_key` |

### Files modified (tests)

| File | Change |
|------|--------|
| `tests/integration/test_apps.py` | `owner=` → `owner_id=` |
| `tests/integration/test_listeners.py` | `owner=` → `owner_id=` |
| `tests/integration/test_scheduler.py` | `owner=` → `owner_id=` |
| `tests/unit/bus/test_metrics.py` | `owner=` → `owner_id=`, update dict key assertions |
| `tests/unit/test_scheduler_job_names.py` | `owner=` → `owner_id=` |

### Blast radius

Low. All changes are mechanical renames and field additions. No new abstractions, no behavioral changes beyond correcting the mismatch. The UPSERT mechanism means DB data self-corrects without migration.
