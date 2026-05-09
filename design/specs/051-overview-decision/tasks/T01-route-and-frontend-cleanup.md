---
task_id: "T01"
title: "Redirect / to /apps and remove overview frontend code"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "AC#1", "AC#2", "AC#3", "AC#5"]
---

## Summary
Replace the overview page route with a redirect to `/apps`, remove the overview page component and all overview-only frontend code (CSS, API functions, sidebar nav link, command palette entry), and update incidental references ("Back to dashboard" copy, etc.). This makes the apps page the de facto landing page.

## Prompt
1. **Route change** in `frontend/src/app.tsx` (line 114): Replace `<Route path="/" component={DashboardPage} />` with `<Redirect to="/apps" />` from wouter. Remove the `DashboardPage` import (line 15).

2. **Delete overview page**: Delete `frontend/src/pages/dashboard.tsx` entirely. Also delete `frontend/src/pages/dashboard.test.tsx` if it exists.

3. **Remove sidebar nav link** in `frontend/src/components/layout/sidebar.tsx` (line 98): Remove the `{ path: "/", label: "overview", testId: "nav-overview" }` entry from the nav links array.

4. **Remove command palette entry** in `frontend/src/components/layout/command-palette.tsx` (line 28-30): Remove the `{ id: "page-overview", ... label: "Overview" }` entry. Update the command palette test file if it asserts on this entry.

5. **Remove overview-only API functions** from `frontend/src/api/endpoints.ts`: Delete `getDashboardKpis` (line ~70), `getDashboardErrors` (line ~84), and `getFrameworkSummary`. Keep `getDashboardAppGrid` (used by apps.tsx) and `getSystemStatus` (used by diagnostics.tsx).

6. **Remove overview CSS** from `frontend/src/global.css`: Delete all `.ht-overview-*` rule blocks (approximately lines 4501-4647, ~25 rules). Grep for `ht-overview` to find the exact range.

7. **Update not-found page** in `frontend/src/pages/not-found.tsx`: Change "Back to dashboard" to "Back to apps" and update the link href from `/` to `/apps`.

8. **Check `frontend/src/utils/app-data.ts`**: The `mergeManifestsAndGrid` and `compareAppRows` functions are used by `apps.tsx` — keep them. Remove any functions that are only imported by `dashboard.tsx` (check with grep).

9. **Regenerate schemas**: Run `uv run python scripts/export_schemas.py` and `cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts` to ensure the OpenAPI spec is fresh after removing any response model references.

10. **Build verification**: Run `npm run build` in the frontend directory to confirm no broken imports or type errors.

## Focus
- The wouter router uses `<Route>` and `<Redirect>` components — check `frontend/src/app.tsx` for the exact import pattern.
- The sidebar nav links are defined as an array of objects at line ~96-103 in `sidebar.tsx`. The "overview" entry is the first in the list — removing it makes "apps" the first nav item naturally.
- The command palette is at `frontend/src/components/layout/command-palette.tsx` (not `shared/`).
- The overview CSS block starts around line 4501 in global.css. Use grep to find the exact boundaries before deleting.
- `app-data.ts` exports are used by both `dashboard.tsx` and `apps.tsx` — after deleting `dashboard.tsx`, verify the remaining exports are still imported somewhere.

## Verify
- [ ] FR#1: Navigating to `/` in the browser redirects to `/apps`
- [ ] FR#2: The `/apps` route renders the apps page unchanged
- [ ] FR#3: The sidebar has no "overview" link; "apps" is the first nav item
- [ ] FR#4: No route matches `/` as a page render (it redirects)
- [ ] AC#1: Loading `/` results in the apps page being displayed
- [ ] AC#2: Sidebar shows "apps" as first nav item with no "overview" entry
- [ ] AC#3: No route renders the former overview page
- [ ] AC#5: No orphaned frontend API functions, CSS classes, or command palette entries remain from the overview
