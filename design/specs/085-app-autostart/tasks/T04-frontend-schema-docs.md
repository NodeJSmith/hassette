---
task_id: "T04"
title: "Render autostart marker in UI, regenerate types, update docs"
status: "planned"
depends_on: ["T03"]
implements: ["FR#11", "AC#9"]
---

## Summary
Complete the user-facing surface: regenerate the OpenAPI/TS types so `autostart` reaches the frontend, thread it through the `AppRow` data model, render a "no autostart" marker on the apps table (and detail header) when `autostart === false`, and update the docs. The status filter set does **not** change (no new status). Carry visual evidence for the PR.

## Target Files
- modify: `frontend/src/utils/app-data.ts`
- modify: `frontend/src/pages/apps-table-row.tsx`
- modify: `frontend/src/components/app-detail/app-detail-header.tsx`
- modify: `frontend/src/pages/apps-table-row.test.tsx`
- modify: `frontend/src/pages/app-detail.test.tsx`
- modify: `frontend/src/test/factories.ts` (only if the regen'd type makes `autostart` required — see Focus)
- modify: `frontend/src/api/generated-types.ts` (regenerated — do not hand-edit)
- modify: `openapi.json` (regenerated)
- modify: `ws-schema.json` (regenerated)
- modify: `frontend/src/api/ws-types.ts` (regenerated)
- modify: `docs/pages/core-concepts/apps/configuration.md`
- modify: `docs/pages/web-ui/manage-apps.md`
- read: `frontend/src/pages/apps.tsx`
- read: `design/specs/085-app-autostart/design.md`
- read: `design/specs/085-app-autostart/tasks/context.md`

## Prompt
Implement the design doc's `## Architecture` section 6 (frontend) and `## Documentation Updates`.

0. **Worktree prep:** `cd frontend && npm install` (worktrees don't share `node_modules`).

1. **Regenerate types** (after T03's response change is in): from repo root run
   `uv run python scripts/export_schemas.py --types`
   This regenerates `openapi.json`, `ws-schema.json`, `frontend/src/api/generated-types.ts`, and `frontend/src/api/ws-types.ts`. `autostart` should now appear on the manifest response type. Do not hand-edit generated files.

2. **`frontend/src/utils/app-data.ts`** — `AppRow` (interface at line 5) and `mergeManifestsAndGrid` (line 33) are manually enumerated and do **not** pass through arbitrary manifest fields. Add `autostart: boolean` to the `AppRow` interface and `autostart: m.autostart` to the mapping in `mergeManifestsAndGrid` (alongside `enabled: m.enabled` / `auto_loaded: m.auto_loaded` at lines 44-45).

3. **`frontend/src/pages/apps-table-row.tsx`** — when a row's `autostart === false`, render a small marker near the status (e.g. a `Chip`/`Badge` reading "no autostart" or similar). Reuse the shared `Badge`/`Chip` components (`components/shared/`) rather than raw class strings. Do **not** add a new status or touch `FILTER_OPTIONS`/`FILTER_TONES`/the stats strip in `apps.tsx`.

4. **`frontend/src/components/app-detail/app-detail-header.tsx`** — this header renders the app's status badge from the `AppManifestResponse`-typed `manifest` prop (`autostart` is available after regen). Add the same "no autostart" marker next to the status badge for consistency.

5. **Frontend tests** — `apps-table-row.test.tsx` and `app-detail.test.tsx` may assert row/header structure; update them to account for the marker (assert it renders when `autostart === false` and is absent when `true`).

6. **Docs:**
   - `docs/pages/core-concepts/apps/configuration.md` (line 15 area + the registration-fields callout ~line 46): document `autostart` alongside `enabled` — `enabled` is the hard on/off switch; `autostart` controls whether the app starts when Hassette starts. Note that `enabled = true, autostart = false` registers the app but leaves it idle until started on demand. Follow the docs voice guide (system-as-subject for concept pages).
   - `docs/pages/web-ui/manage-apps.md` "Understand App States" table (lines 60-68): clarify the `STOPPED` row to note it also covers an enabled app with `autostart = false` that has not been started, and mention the "no autostart" marker. Leave the `DISABLED` row as-is.

7. **Verify the build:** `cd frontend && npm run build` and `npm test`.

8. **Visual evidence:** capture a screenshot of the apps dashboard showing the marker on an `autostart=false` app (use the demo stack — see project memory "demo script for UI visual QA"). This is required for the PR per `design-completeness.md` / `tools/frontend/check_pr_screenshots.py`.

## Focus
- Schema-freshness is enforced: the pre-push hook (`tools/check_schemas_fresh.py`) checks `ws-schema.json`/`openapi.json`; CI additionally git-diffs `ws-types.ts` and `generated-types.ts`. Regenerate via the one command above and commit all four generated files together — a stale generated file fails CI.
- CSS: use the shared `Badge`/`Chip` components per the project CSS architecture (CLAUDE.md). Do not add raw `ht-*` class strings; do not add raw hex/px (use tokens).
- The status filter set is intentionally unchanged — an autostart=false app filters under `stopped`. Only the inline marker is new.
- Docs prose: run the `doc-persona-review` and `doc-accuracy-review` on the two touched pages before shipping (per `.claude/rules/doc-rules.md`) — scope to `core-concepts/apps/configuration` and `web-ui/manage-apps`.
- `frontend/src/test/factories.ts` has a `createManifest()` factory (line 43) using `satisfies AppManifestResponse`. Because T03 gives the response field a `= True` default, the regen'd type should render `autostart?: boolean` (optional) and `createManifest` keeps compiling. **Verify this** by running `npm run build` (tsc) after regen — if the type comes out required, add `autostart: false` (or `true`) to the `createManifest` defaults. Either way, add an `autostart` override path so `app-detail.test.tsx` / `apps-table-row.test.tsx` can build a manifest with `autostart: false` to test the marker.
- Depends on T03 (the `autostart` response field must exist before regeneration picks it up).
- Run: `cd frontend && npm install && npm run build && npm test`; regen with `uv run python scripts/export_schemas.py --types`.

## Verify
- [ ] FR#11: The apps table renders a visible "no autostart" marker on rows where `autostart === false`, and no marker when `autostart === true` (frontend test asserts both).
- [ ] AC#9: `generated-types.ts` includes `autostart` on the manifest type, `AppRow` carries it, and the UI marker renders for autostart=false apps; a screenshot of the marker is captured for the PR.
