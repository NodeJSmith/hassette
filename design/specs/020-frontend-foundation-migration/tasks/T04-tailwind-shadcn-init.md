---
task_id: "T04"
title: "Add Tailwind CSS v4 and initialize shadcn/ui"
status: "planned"
depends_on: ["T03"]
implements: ["FR#6", "FR#7", "AC#2", "AC#6", "AC#7", "AC#8"]
---

## Summary

Add Tailwind CSS v4 via the `@tailwindcss/vite` plugin and initialize shadcn/ui. This is additive — no existing CSS is modified. Tailwind is imported without Preflight to preserve the existing hand-rolled reset. shadcn is initialized with the New York style and an empty component directory. After this task, the full migration is complete and ready for spec 2's component-by-component replacement.

## Target Files

- modify: `frontend/package.json`
- modify: `frontend/vite.config.ts`
- modify: `frontend/src/global.css`
- create: `frontend/components.json`
- create: `frontend/src/components/ui/` (empty directory)
- read: `frontend/src/styles/reset.css`
- read: `frontend/src/tokens.css`
- modify: `CLAUDE.md`
- modify: `frontend/README.md` (if it exists)
- read: `design/specs/020-frontend-foundation-migration/design.md`

## Prompt

Add Tailwind CSS v4 and initialize shadcn/ui. This is purely additive — no existing CSS files are modified.

### 1. Install Tailwind

```bash
cd frontend
npm install tailwindcss @tailwindcss/vite
```

### 2. Configure Vite plugin

Add `tailwindcss()` to the Vite plugins array in `vite.config.ts`:
```typescript
import tailwindcss from "@tailwindcss/vite";
// ...
plugins: [react(), tailwindcss()],
```

### 3. Import Tailwind without Preflight

Add to `frontend/src/global.css` (at the top, before existing imports):
```css
@import "tailwindcss/theme.css" layer(theme);
@import "tailwindcss/utilities.css" layer(utilities);
```

Do NOT use `@import "tailwindcss"` — that ships Preflight, an unscoped global reset that collides with the existing `styles/reset.css`. Skipping `preflight.css` preserves the current visual appearance. No `tailwind.config.js` needed — Tailwind v4 uses CSS-based configuration via `@theme`.

### 4. Initialize shadcn/ui

```bash
cd frontend
npx shadcn@latest init
```

During init:
- Style: New York
- Base color: pick one that maps to the existing design token palette
- Configure `components.json` to use `@/components/ui` as the component directory
- The CLI generates theme CSS variables (`--background`, `--foreground`, `--primary`, etc.)

Token mapping (aliasing shadcn variables to existing design tokens) is deferred to spec 2. The generated theme file stays as-is for now.

### 5. Documentation updates

**`CLAUDE.md`:** Update the CSS Architecture section to note Tailwind + CSS Modules coexistence. Update the package dependencies description (React, Zustand, Tailwind replace Preact, signals). Note that `class=` is now `className=`.

**`frontend/README.md`** (if it exists): Update setup instructions for React + Tailwind.

### 6. Verify

Run the full test suite, build, and demo stack:
```bash
cd frontend && npm run test    # 0 failures
cd frontend && npm run build   # exit 0
mise run demo                  # all 7 pages render without visual regression
uv run nox -s e2e              # E2E suite passes
```

Also verify shadcn is functional:
```bash
cd frontend && npx shadcn@latest add button --dry-run
```

## Focus

- **Preflight collision:** The critical detail is importing Tailwind WITHOUT Preflight. `@import "tailwindcss"` ships Preflight by default — the selective import (`theme.css` + `utilities.css`) skips it. The existing `styles/reset.css` handles box-sizing, body margin, heading margin, form element resets. Preflight would override elements the existing reset doesn't target (anchors, `hr`, `fieldset`, list markers), causing visual regressions.
- **CSS layer ordering:** Tailwind v4's `@layer` system means unlayered CSS (the existing reset, which uses no `@layer`) wins over Tailwind's layered base styles for elements both target. The import order in `global.css` matters — place Tailwind imports at the top.
- **`@` path alias:** `vite.config.ts` already has `resolve.alias: { "@": path.resolve(__dirname, "./src") }`. shadcn's `components.json` uses `@/components/ui` — this resolves correctly via the existing alias.
- **Demo stack verification (AC#7):** Run `mise run demo` and visually check all 7 pages: apps, handlers, logs, config, diagnostics, app-detail, design. The `/design` page exercises design token rendering and is the most exposed to Tailwind/CSS-Modules coexistence issues.
- **E2E verification (AC#8):** Run `uv run nox -s e2e`. All selectors use `data-testid`, ARIA roles, and text content — zero CSS class selectors, so the framework swap should not affect them.

## Verify

- [ ] FR#6: `tailwindcss` and `@tailwindcss/vite` are installed. `vite.config.ts` includes the `tailwindcss()` plugin. `global.css` imports Tailwind theme and utilities without Preflight.
- [ ] FR#7: `components.json` exists with New York style and `@/components/ui` as the component directory.
- [ ] AC#2: `cd frontend && npm run test` reports 0 failures across all 104 test files.
- [ ] AC#6: `cd frontend && npx shadcn@latest add button --dry-run` succeeds.
- [ ] AC#7: The demo stack (`mise run demo`) renders all 7 pages (apps, handlers, logs, config, diagnostics, app-detail, design) without visual regression.
- [ ] AC#8: `uv run nox -s e2e` passes.
