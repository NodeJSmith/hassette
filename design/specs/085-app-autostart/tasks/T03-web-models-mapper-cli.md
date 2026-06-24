---
task_id: "T03"
title: "Expose autostart on the apps API response and CLI list"
status: "planned"
depends_on: ["T01"]
implements: ["FR#10", "AC#9"]
---

## Summary
Surface `autostart` through the web API and CLI. Add `autostart` to the `AppManifestResponse` model, map it from `AppManifestInfo` in the response mapper, and add an `Autostart` column to the `hassette app` CLI list table (which already shows `status` and `enabled`). Update the mapper/model tests so they assert the field carries through. This is the API half of AC#9; the frontend marker (T04) is the UI half.

## Target Files
- modify: `src/hassette/web/models.py`
- modify: `src/hassette/web/mappers.py`
- modify: `src/hassette/cli/commands/app.py`
- modify: `tests/unit/web/test_mappers.py`
- modify: `tests/unit/test_model_types.py`
- read: `src/hassette/test_utils/web_helpers.py`
- read: `src/hassette/schemas/app_snapshots.py`
- read: `design/specs/085-app-autostart/design.md`
- read: `design/specs/085-app-autostart/tasks/context.md`

## Prompt
Implement the design doc's `## Architecture` section 5 (web models + mappers + CLI).

1. **`src/hassette/web/models.py`** — Add `autostart: bool = True` to `AppManifestResponse` (after `enabled`, ~line 127), with a `Field(...)` description if the surrounding fields use one. The `= True` default keeps the existing direct constructions working (`test_utils/web_helpers.py:117`, `tests/unit/test_model_types.py:94,106`). Do **not** change the `ManifestStatus` literal.

2. **`src/hassette/web/mappers.py`** — In the manifest-response construction (~line 91, inside `app_manifest_list_response_from`), add `autostart=m.autostart` so the real value flows from `AppManifestInfo` to the response.

3. **`src/hassette/cli/commands/app.py`** — `APP_LIST_COLUMNS` (lines 13-19) already has `status`, `display_name`, ..., `enabled` columns. Add an `Autostart` column (e.g. `Column("autostart", "Autostart", max_width=9)`) so the CLI `hassette app` list shows it next to `enabled`. Match the existing `Column(...)` style.

4. **Tests:**
   - `tests/unit/web/test_mappers.py` — the local `make_manifest` helper (line 147) builds `AppManifestInfo` with explicit kwargs but omits `autostart` (so it gets the `True` default). Add an `autostart: bool = True` parameter to that helper and pass it through, then assert the mapped `AppManifestResponse` carries `autostart` through for both a `True` and a `False` manifest. (Without extending the helper, the `False` case can't be exercised.)
   - `tests/unit/test_model_types.py` — `TestManifestStatus` builds `AppManifestResponse` (lines 94, 106); add an assertion that `autostart` defaults to `True` when omitted and round-trips when set to `False`.

## Focus
- `AppManifestResponse` is constructed in three known places: the mapper (`mappers.py:91`, gets the real value here), `test_utils/web_helpers.py:117`, and `tests/unit/test_model_types.py:94,106`. The `= True` default is what keeps the latter two from breaking — do not make the field required. Leave `web_helpers.py`'s builders relying on the default (do **not** add `autostart=False` there — other suites build fixtures via those helpers and expect the autostart default).
- The `/api/apps/manifests` route enriches the mapped list with `recent_invocations_1h` via `model_copy(update={...})` (`web/routes/apps.py`) — `model_copy` preserves all other fields, so `autostart` flows through untouched. No route change needed.
- The CLI `client.py:198` use of `AppManifestListResponse` is only instance-name→index resolution (iterates `.instances`) — it does not render columns, so no change there. Only `commands/app.py`'s `APP_LIST_COLUMNS` renders the table.
- `render_table` reads attributes by the column key string, so the `Column` key must be `"autostart"` to match the model field name.
- Depends on T01 (`AppManifestInfo.autostart` must exist before the mapper can read `m.autostart`).
- Run: `uv run pytest -n 4 tests/unit/web/test_mappers.py tests/unit/test_model_types.py tests/unit/cli` and `uv run pyright`. Optionally exercise the CLI table against the demo stack.

## Verify
- [ ] FR#10: `AppManifestResponse` has an `autostart` field, and the mapper sets it from `AppManifestInfo.autostart` (mapper test asserts both `True` and `False` carry through).
- [ ] AC#9: The `/apps` manifest response includes `autostart` per app (mapper/model tests confirm), and the `hassette app` CLI list renders an `Autostart` column.
