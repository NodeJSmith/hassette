---
task_id: "T08"
title: "Verify build, tests, and update CLAUDE.md"
status: "planned"
depends_on: ["T05", "T06", "T07"]
implements: ["AC#3", "AC#4", "AC#5", "AC#10", "AC#11"]
---

## Summary

Run the full verification suite — frontend build, vitest, typecheck, E2E tests, and demo stack visual QA — to confirm the migration preserved visual and behavioral parity. Update the CLAUDE.md CSS Architecture section to reflect the Tailwind-only approach. This is the final task.

## Target Files

- modify: `CLAUDE.md`
- read: `frontend/src/global.css`
- read: `design/specs/089-css-module-tailwind-conversion/design.md`

## Prompt

**Step 1 — Frontend build:**

```bash
cd frontend && npm run build
```

Must exit 0. If it fails, investigate the error — it's likely a missing Tailwind class or a broken `cn()` import.

**Step 2 — Vitest:**

```bash
cd frontend && npm run test
```

Must report 0 failures. If tests fail, check whether they reference removed CSS Module imports, `ht-*` classes, or `clsx` — these should have been fixed in T05 (test updates) and T07 (clsx migration).

**Step 3 — TypeScript type check:**

```bash
cd frontend && npm run typecheck
```

Must exit 0. The most likely type errors are missing `.module.css` type declarations (which should now be gone) or incorrect `cn()` import paths.

**Step 4 — E2E tests:**

```bash
uv run nox -s e2e
```

Must pass. If E2E tests fail, check:
- Selector changes — any `ht-*` class selectors in E2E tests should have been updated in T05
- Visual regressions — Preflight or Tailwind utility differences that changed element rendering
- Behavioral regressions — unlikely since this is styling-only

**Step 5 — Demo stack visual QA:**

Start the demo stack:
```bash
mise run demo
```

Navigate all pages and verify:
- Dashboard / overview renders correctly
- App detail pages (all tabs) render correctly
- Log table with drawer renders correctly
- Handler list renders correctly
- Config page renders correctly
- Diagnostics page renders correctly
- Dark mode toggle works on all pages
- Mobile responsive layout (resize browser) works correctly
- Sidebar collapse/expand works
- Command palette (Cmd+K) works

Take screenshots if Playwright MCP is available.

**Step 6 — Update CLAUDE.md CSS Architecture section:**

Rewrite the `## CSS Architecture` section and its subsections. Replace all CSS Module references with the Tailwind-only approach. The new content should cover:

- Tailwind v4 via `@tailwindcss/vite` with Preflight enabled
- `global.css` as the single CSS entry point (all token definitions, `@theme`, `@layer base`, `@layer components`)
- `styles/fonts.css` as the only other CSS file (`@font-face` declarations)
- `cn()` from `@/lib/utils` for all className composition
- shadcn/ui components in `components/ui/` (from spec 088)
- The `--accent` collision resolution (still relevant)
- No CSS Modules, no `ht-*` global classes, no `clsx`
- Custom Tailwind screens for non-standard breakpoints

Remove the "Module pattern" subsection (no modules). Remove the "When to use styles/ vs a module vs a shared component" subsection. Remove the "Referencing global classes from module CSS" subsection. Remove the "CI guards" subsection references to removed tools (keep `check_dead_tokens`, `check_breakpoint_drift` if they survived). Remove the "Adding a new shared class" subsection.

Update the `### CI guards` subsection to reflect only the surviving lint tools.

## Focus

- The E2E tests (`nox -s e2e`) run in CI too — don't skip them here. They are the primary safety net for behavioral parity.
- The demo stack uses a real HA container + Hassette + Vite dev server. It takes 60-90s to start. The `mise run demo-verify` command does a non-interactive health check.
- CLAUDE.md changes must be accurate against the actual codebase state after all previous tasks. Read `global.css` to confirm the actual structure before writing the CLAUDE.md update.
- The CLAUDE.md update is documentation, not code — it should describe the current state, not the migration process.

## Verify

- [ ] AC#3: `cd frontend && npm run build` exits 0.
- [ ] AC#4: `cd frontend && npm run test` reports 0 failures.
- [ ] AC#5: `cd frontend && npm run typecheck` exits 0.
- [ ] AC#10: `uv run nox -s e2e` passes.
- [ ] AC#11: Demo stack renders all pages without visual regression.
