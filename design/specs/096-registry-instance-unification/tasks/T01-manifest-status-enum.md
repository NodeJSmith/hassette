---
task_id: "T01"
title: "Create ManifestStatus StrEnum and characterization tests"
status: "done"
depends_on: []
implements: ["FR#6", "AC#7"]
---

## Summary

Create the `ManifestStatus` StrEnum in `types/enums.py` as the single source of truth for manifest status values, replacing the separate `Literal` in `web/models.py` and `MANIFEST_STATUS_KEYS` tuple in `app_snapshots.py`. Then write characterization tests pinning the current behavior of `get_snapshot()`, `get_full_snapshot()`, and `build_manifest_info()` — these tests must pass against the current code before any structural changes in T02.

## Target Files

- modify: `src/hassette/types/enums.py`
- modify: `src/hassette/schemas/app_snapshots.py`
- modify: `src/hassette/schemas/__init__.py`
- modify: `src/hassette/web/models.py`
- modify: `src/hassette/test_utils/web_manifest_helpers.py`
- modify: `tests/unit/test_model_types.py`
- modify: `tests/unit/core/test_app_registry.py`
- read: `src/hassette/core/app_registry.py`
- read: `design/specs/096-registry-instance-unification/design.md`

## Prompt

### Part 1: ManifestStatus StrEnum

Add a `ManifestStatus` StrEnum to `src/hassette/types/enums.py` (alongside `ResourceStatus`):

```python
class ManifestStatus(StrEnum):
    DISABLED = "disabled"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    RUNNING = "running"
    FAILED = "failed"
    STOPPED = "stopped"
```

In `src/hassette/schemas/app_snapshots.py`:
- Import `ManifestStatus` from `hassette.types.enums`
- Replace `MANIFEST_STATUS_KEYS = ("running", "failed", "stopped", "disabled", "blocked")` with `MANIFEST_STATUS_KEYS = tuple(ManifestStatus)`
- Update the inline comment on `AppManifestInfo.status` (line 74) to include `"degraded"`

In `src/hassette/web/models.py`:
- Remove the `ManifestStatus = Literal[...]` definition (line 25)
- Import `ManifestStatus` from `hassette.types.enums` instead
- All existing usages of `ManifestStatus` as a type annotation should work as-is since `StrEnum` is compatible with `str`

In `src/hassette/schemas/__init__.py`:
- Add `ManifestStatus` to the re-exports if not already present

In `src/hassette/test_utils/web_manifest_helpers.py`:
- Update `ManifestStatus` import to come from `hassette.types.enums`

In `tests/unit/test_model_types.py`:
- Update `TestManifestStatus` to validate the StrEnum values instead of the Literal type

### Part 2: Characterization tests

Add characterization tests to `tests/unit/core/test_app_registry.py` that pin the current output shapes of:
- `get_snapshot()` — register 2 running instances and record 1 failure, assert the snapshot has `.running` list with 2 entries and `.failed` list with 1 entry, with correct field values
- `get_full_snapshot()` — set up manifests + running + failed instances, assert the full snapshot has correct `running`/`failed`/`stopped` counts and manifest info
- `build_manifest_info()` — test each status derivation path: disabled, blocked, running, failed, stopped (the current 5 values — no degraded yet)

These tests MUST pass against the current code before T02 makes structural changes. They serve as the behavioral pin for the refactor.

## Focus

- `tally_manifest_statuses()` iterates `MANIFEST_STATUS_KEYS` to build its count dict. After the change, this tuple includes `"degraded"` which the current `build_manifest_info()` never produces. `tally_manifest_statuses` silently skips unknown keys, so existing behavior is preserved — `degraded` count will be 0 until T02 adds the derivation logic.
- `ManifestStatus` must be added to `types/enums.py`'s `__all__` list if the module uses one.
- The characterization tests should use the existing test factories (`make_mock_hassette`, helpers from `test_utils`) — check `tests/unit/core/CLAUDE.md` for directory-specific fixtures.
- `web/models.py` uses `ManifestStatus` as a Pydantic field type. `StrEnum` values serialize to their string values, so Pydantic compatibility is preserved.

## Verify

- [ ] FR#6: `ManifestStatus` is importable from `hassette.types.enums` as a `StrEnum` with 6 values (DISABLED, BLOCKED, DEGRADED, RUNNING, FAILED, STOPPED), and `tuple(ManifestStatus)` equals `MANIFEST_STATUS_KEYS`
- [ ] AC#7: `ManifestStatus` is importable from `hassette.types.enums` and `tuple(ManifestStatus)` matches `MANIFEST_STATUS_KEYS` — verified by running `prek -a`
