---
task_id: "T07"
title: "Enable StrictMode, migrate clsx, clean up global.css"
status: "planned"
depends_on: ["T05"]
implements: ["FR#9", "FR#12", "FR#13", "AC#6", "AC#12"]
---

## Summary

Enable React StrictMode, migrate remaining `clsx` imports to `cn()`, remove `clsx` as a direct dependency, and clean up `global.css` to be well-organized after all the inlining and merging from previous tasks. This is the final code-change task before verification.

## Target Files

- modify: `frontend/src/main.tsx`
- modify: `frontend/package.json`
- modify: `frontend/src/global.css`
- modify: `frontend/src/components/shared/error-display.tsx`
- modify: `frontend/src/components/shared/detail-stats.tsx`
- modify: `frontend/src/components/shared/traceback-viewer.tsx`
- modify: `frontend/src/components/shared/stats-strip.tsx`
- modify: `frontend/src/components/shared/system-health.tsx`
- modify: `frontend/src/pages/app-detail.tsx`
- modify: `frontend/src/components/layout/alert-banner.tsx`
- modify: `frontend/src/components/app-detail/overview-tab.tsx`
- modify: `frontend/src/components/app-detail/error-spotlight.tsx`
- modify: `frontend/src/components/app-detail/recent-activity-section.tsx`
- read: `design/specs/089-css-module-tailwind-conversion/design.md`

## Prompt

**Step 1 — Enable React StrictMode:**

In `frontend/src/main.tsx`, wrap the render call in `<StrictMode>`:

```tsx
import { StrictMode } from "react";

createRoot(document.getElementById("app")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

Start the dev server (`cd frontend && npm run dev`) and check the browser console for StrictMode warnings. StrictMode causes effects to run twice in development — look for:
- Effects without cleanup functions (subscriptions, event listeners, timers)
- Unexpected console warnings about side effects in render

Fix any double-effect issues found. The most likely candidates are in layout components (`app.tsx` keyboard shortcuts, sidebar event listeners) and data-fetching hooks.

**Step 2 — Migrate remaining `clsx` imports to `cn()`:**

These 10 files still import `clsx`. In each file:
1. Remove `import clsx from "clsx"` (or `import { clsx } from "clsx"`)
2. Add `import { cn } from "@/lib/utils"` if not already present
3. Replace all `clsx(...)` calls with `cn(...)`

Files (some may have already been migrated in T02–T04 as part of the CSS Module conversion — check each before modifying):
- `frontend/src/components/shared/error-display.tsx`
- `frontend/src/components/shared/detail-stats.tsx`
- `frontend/src/components/shared/traceback-viewer.tsx`
- `frontend/src/components/shared/stats-strip.tsx`
- `frontend/src/components/shared/system-health.tsx`
- `frontend/src/pages/app-detail.tsx`
- `frontend/src/components/layout/alert-banner.tsx`
- `frontend/src/components/app-detail/overview-tab.tsx`
- `frontend/src/components/app-detail/error-spotlight.tsx`
- `frontend/src/components/app-detail/recent-activity-section.tsx`

**Step 3 — Remove `clsx` direct dependency:**

Run `npm uninstall clsx` in the `frontend/` directory. `clsx` will remain as a transitive dependency of `tailwind-merge` (which `cn()` wraps), so imports of `cn` from `@/lib/utils` continue working.

Verify: `grep '"clsx"' frontend/package.json` should show no direct dependency entry (it may still appear in `package-lock.json` as a transitive dep — that's correct).

**Step 4 — Clean up global.css:**

After T01 and T05, `global.css` has accumulated content from multiple phases. Reorganize it into a clean structure:

1. `@import "tailwindcss"` (Preflight + theme + utilities)
2. `@import "./styles/fonts.css"` (font-face declarations)
3. `@custom-variant dark (&:is([data-theme="dark"] *));`
4. `@theme inline { ... }` (colors, radii, custom breakpoints)
5. `:root { ... }` (all token values — surfaces, ink, lines, accent, status, spacing, sizing, shadows, opacity, motion, z-index — followed by shadcn aliases)
6. `[data-theme="dark"] { ... }` (dark theme overrides — token values followed by shadcn aliases)
7. `@layer base { ... }` (typography, focus indicator, reduced motion, any surviving element-level rules)
8. `@layer components { ... }` (any surviving shared patterns like table styling, if kept)

Remove all comments that reference "PR 2" or "tokens.css" since this is PR 2 and tokens.css no longer exists. Keep comments that explain the `--accent` collision resolution — that's still relevant.

## Focus

- `cn()` is defined in `frontend/src/lib/utils.ts` and wraps `twMerge(clsx(...))`. It accepts the same arguments as `clsx` — the migration is a 1:1 rename of the function call.
- Some of the 10 `clsx` files may have already been migrated during T02–T04 (the CSS Module conversion tasks instruct migrating `clsx` in affected files). Check each file before modifying to avoid a no-op edit.
- StrictMode in React 19 remounts components and replays effects in development. Effects that fetch data should be idempotent or use an abort signal. Check `useEffect` hooks in `app.tsx`, `sidebar.tsx`, and any WebSocket connection hooks.
- When removing `clsx` from `package.json`, use `npm uninstall` rather than manually editing the file — this updates `package-lock.json` correctly.

## Verify

- [ ] FR#9: `grep -rn 'from "clsx"' frontend/src/ | grep -v 'lib/utils.ts' | wc -l` returns 0 (only `lib/utils.ts` legitimately imports clsx as the internal implementation of `cn()`). `grep '"clsx"' frontend/package.json` returns no direct dependency.
- [ ] FR#12: `grep -n 'StrictMode' frontend/src/main.tsx` returns a match. The app runs in dev mode without StrictMode-related console errors.
- [ ] FR#13: `grep -rn 'from "clsx"' frontend/src/ | grep -v 'lib/utils.ts' | wc -l` returns 0. All className composition uses `cn()`.
- [ ] AC#6: Same as FR#9 — zero `clsx` imports outside `lib/utils.ts`.
- [ ] AC#12: Same as FR#12 — StrictMode present in main.tsx.
