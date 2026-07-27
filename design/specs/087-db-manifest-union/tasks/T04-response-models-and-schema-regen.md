---
task_id: "T04"
title: "Extend response models and regenerate types"
status: "planned"
depends_on: ["T01"]
implements: ["FR#9", "AC#8"]
---

## Summary

Extend `DashboardAppGridEntry` with manifest metadata fields so the apps page can consume a single endpoint. Add `in_current_config` to both `DashboardAppGridEntry` and `AppManifestResponse`. Regenerate OpenAPI schema and TypeScript types. Update test factories for the new fields. This task modifies the response shape; T03 populates the new fields.

## Target Files

- modify: `src/hassette/web/models.py`
- modify: `src/hassette/schemas/app_snapshots.py`
- modify: `scripts/export_schemas.py`
- modify: `src/hassette/test_utils/web_response_helpers.py`
- modify: `src/hassette/test_utils/web_manifest_helpers.py`
- modify: `src/hassette/test_utils/web_mocks.py`
- modify: `tests/unit/test_model_types.py`
- read: `frontend/src/utils/app-data.ts` (AppRow fields to match)

## Prompt

### Extend `DashboardAppGridEntry` in `models.py`

Add these fields to `DashboardAppGridEntry` (currently at `web/models.py:355-382`):
- `class_name: str = ""`
- `filename: str = ""`
- `enabled: bool = True`
- `auto_loaded: bool = False`
- `autostart: bool = True`
- `block_reason: str | None = None`
- `instances: list[AppInstanceResponse] = Field(default_factory=list)`
- `error_message: str | None = None`
- `error_traceback: str | None = None`
- `in_current_config: bool = True`

These fields have defaults so the extension is backward-compatible for existing consumers.

### Add `in_current_config` to `AppManifestResponse`

Add `in_current_config: bool = True` to `AppManifestResponse` (at `models.py:127-147`).

### Update `AppManifestInfo` if needed

Check if `AppManifestInfo` in `schemas/app_snapshots.py` needs `in_current_config: bool = True` added. The overlay function in T02 produces this field — the dataclass must carry it.

### Regenerate schemas and types

Run `uv run python scripts/export_schemas.py --types` to regenerate `openapi.json`, `ws-schema.json`, `generated-types.ts`, and `ws-types.ts`.

### Update test factories

- `web_response_helpers.py`: Update `make_dashboard_app_grid_entry()` to include defaults for new fields.
- `web_manifest_helpers.py`: Update `make_app_manifest_info()`, `make_app_manifest_response()` etc. with `in_current_config` default.
- `web_mocks.py`: Update any mock fixtures if `AppManifestInfo` structure changed.
- `tests/unit/test_model_types.py`: Add/update tests for the extended `DashboardAppGridEntry` and `AppManifestResponse` with new fields.

## Focus

- The field defaults on `DashboardAppGridEntry` must be backward-compatible — existing test code that constructs entries without the new fields must not break.
- `AppInstanceResponse` is already defined in `models.py` — reuse it for the `instances` field.
- After schema regeneration, run `cd frontend && npm run build` to verify the frontend compiles with the new types.
- The `ManifestStatus` literal type (check `models.py`) may need to be referenced by the grid entry's `status` field if it isn't already.
- `test_model_types.py` at `tests/unit/test_model_types.py:17-18,93,105,118,136,148,234,278` tests `AppManifestResponse` and `DashboardAppGridEntry` — update these for the new fields.

## Verify

- [ ] FR#9: `DashboardAppGridEntry` includes `class_name`, `filename`, `enabled`, `autostart`, `auto_loaded`, `block_reason`, `instances`, `in_current_config` fields with correct types and defaults.
- [ ] AC#8: The grid response model has all fields needed for the apps page — verified by comparing the field set against the current `AppRow` type in `frontend/src/utils/app-data.ts`.
