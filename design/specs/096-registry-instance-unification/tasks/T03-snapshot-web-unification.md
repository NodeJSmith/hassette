---
task_id: "T03"
title: "Unify snapshot and web response models"
status: "done"
depends_on: ["T02"]
implements: ["FR#7", "FR#15", "AC#5"]
---

## Summary

Collapse `AppStatusSnapshot`'s separate `.running`/`.failed` lists into a single `.instances` list. Replace individual count fields on `AppFullSnapshot` and `AppManifestListResponse` with a single `status_counts: dict[str, int]` field. Update mappers, the CLI client, and regenerate schemas/types. `overlay_runtime_state()` inherits the changes via `build_manifest_info()` and needs no direct modification.

## Target Files

- modify: `src/hassette/schemas/app_snapshots.py`
- modify: `src/hassette/web/models.py`
- modify: `src/hassette/web/mappers.py`
- modify: `src/hassette/web/routes/apps.py`
- modify: `src/hassette/core/app_registry.py`
- modify: `src/hassette/cli/client.py`
- modify: `src/hassette/cli/commands/app.py`
- modify: `src/hassette/test_utils/web_manifest_helpers.py`
- modify: `src/hassette/test_utils/web_mocks.py`
- modify: `tests/unit/web/test_mappers.py`
- modify: `tests/unit/core/test_runtime_query_service.py`
- modify: `tests/integration/web_api/test_ws_endpoint.py`
- modify: `tests/integration/web_api/conftest.py`
- modify: `tests/integration/test_app_factory_lifecycle.py`
- modify: `tests/unit/cli/test_commands_app.py`
- modify: `tests/system/test_cli_smoke.py`
- modify: `frontend/src/api/generated-types.ts`
- modify: `frontend/src/api/ws-types.ts`
- modify: `openapi.json`
- modify: `ws-schema.json`
- read: `design/specs/096-registry-instance-unification/design.md`

## Prompt

### AppStatusSnapshot collapse

In `src/hassette/schemas/app_snapshots.py`, replace:

```python
running: list[AppInstanceInfo] = field(default_factory=list)
failed: list[AppInstanceInfo] = field(default_factory=list)
```

with:

```python
instances: list[AppInstanceInfo] = field(default_factory=list)
```

Preserve the computed count properties but filter `.instances` by `error is None` (running) vs `error is not None` (failed):

```python
@property
def running_count(self) -> int:
    return sum(1 for i in self.instances if i.error is None)

@property
def failed_count(self) -> int:
    return sum(1 for i in self.instances if i.error is not None)

@property
def running_apps(self) -> set[str]:
    return {i.app_key for i in self.instances if i.error is None}

@property
def failed_apps(self) -> set[str]:
    return {i.app_key for i in self.instances if i.error is not None}

@property
def total_count(self) -> int:
    return len(self.instances)
```

### AppFullSnapshot status_counts

Replace individual count fields (`running: int`, `failed: int`, `stopped: int`, `disabled: int`, `blocked: int`) with:

```python
status_counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(ManifestStatus, 0))
```

`tally_manifest_statuses()` already returns a `dict[str, int]` — the call site in `app_registry.py:get_full_snapshot()` changes from `**tally_manifest_statuses(manifests)` to `status_counts=tally_manifest_statuses(manifests)`.

### AppManifestListResponse status_counts

In `src/hassette/web/models.py`, replace the individual count fields on `AppManifestListResponse` (lines 172-176) with:

```python
status_counts: dict[str, int] = Field(default_factory=dict)
```

### Web mappers

In `src/hassette/web/mappers.py`:

- `app_status_response_from()`: read `snapshot.instances` directly instead of merging `snapshot.running + snapshot.failed`. Derive `running`/`failed` counts from the snapshot's computed properties.
- `app_manifest_list_response_from()`: replace field enumeration (`running=full.running, failed=full.failed, ...`) with `status_counts=full.status_counts`.

### app_registry.py get_snapshot

Update `get_snapshot()` in `app_registry.py` to build a single `instances` list instead of separate `running`/`failed` lists. The method now iterates `_instances[app_key].items()` and builds `AppInstanceInfo` entries for both running and failed instances.

### CLI

Check `src/hassette/cli/client.py` and `src/hassette/cli/commands/app.py` — they deserialize `AppManifestListResponse`. Update any access to the old individual count fields to use `status_counts`.

### Schema regeneration

After all model changes:

```bash
uv run python scripts/export_schemas.py --types
```

This regenerates `openapi.json`, `ws-schema.json`, `generated-types.ts`, and `ws-types.ts`.

### Test updates

Update all test files that construct `AppStatusSnapshot` with `.running`/`.failed` fields — switch to `.instances`. Update all test files that construct `AppFullSnapshot` or `AppManifestListResponse` with individual count fields — switch to `status_counts`. See the gap check list for affected files.

## Focus

- `AppStatusResponse` in `web/models.py` has its own `running: int` and `failed: int` fields — this is the per-instance status endpoint, separate from `AppManifestListResponse`. The design says to preserve `AppStatusResponse` wire format (Behavioral Invariant). These counts are derived from the snapshot's computed properties, so they still work.
- `web/routes/apps.py:106` does `**tally_manifest_statuses(manifest_infos)` to unpack counts into the response. This needs to change to `status_counts=tally_manifest_statuses(manifest_infos)`.
- The `overlay_runtime_state()` function in `app_registry.py` delegates to `build_manifest_info()` — it inherits the changes without direct modification.
- `AppStatusSnapshot` count properties filter on `error is None` (not on `status == RUNNING`) to match current list-membership semantics — a STARTING instance is "running" (has an App), not failed.
- Gap check found `tests/integration/web_api/conftest.py`, `tests/integration/web_api/test_ws_endpoint.py`, `tests/unit/web/test_mappers.py`, `tests/unit/core/test_runtime_query_service.py`, `tests/integration/test_app_factory_lifecycle.py`, `tests/unit/cli/test_commands_app.py`, `tests/system/test_cli_smoke.py` — all construct snapshots or responses with the old field shapes.
- Frontend test files `frontend/src/test/factories.ts`, `frontend/src/test/handlers.ts`, `frontend/src/hooks/use-manifests.test.ts` construct responses with individual count fields — update to `status_counts`.

## Verify

- [ ] FR#7: `AppStatusSnapshot` has `.instances` (no `.running`/`.failed` attributes); `.running_count` and `.failed_count` return correct filtered counts
- [ ] FR#15: `AppFullSnapshot` and `AppManifestListResponse` use `status_counts: dict[str, int]` — no individual count fields
- [ ] AC#5: `AppStatusSnapshot` has no `.running` or `.failed` attributes; `.instances` contains all entries; counts are correct
