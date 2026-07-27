---
task_id: "T03"
title: "Swap Preact runtime for React 19"
status: "planned"
depends_on: ["T02"]
implements: ["FR#1", "FR#2", "FR#8", "FR#10", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Summary

Replace the Preact runtime with React 19. With all signal consumers already on Zustand (T02), this is a purely mechanical change — no state layer dependencies on Preact remain. Swap packages, convert imports across ~68 files, codemod `class=` to `className=`, update vite/vitest/tsconfig configs, rewrite the entry point for `createRoot`, replace the error boundary with `react-error-boundary`, convert `useSignal()` to `useState()` in ~16 files, and update all test imports from `@testing-library/preact` to `@testing-library/react`.

## Target Files

- modify: `frontend/package.json`
- modify: `frontend/vite.config.ts`
- modify: `frontend/vitest.config.ts`
- modify: `frontend/tsconfig.json`
- modify: `frontend/src/main.tsx`
- modify: `frontend/src/components/layout/error-boundary.tsx`
- modify: `frontend/src/test-setup.ts`
- modify: `frontend/src/test/render-helpers.tsx`
- modify: `frontend/src/components/app-detail/app-logs-panel.tsx`
- modify: `frontend/src/components/shared/execution-table.tsx`
- modify: `frontend/src/components/shared/action-buttons.tsx`
- modify: `frontend/src/components/shared/sort-header.tsx`
- modify: `frontend/src/components/shared/table-footer.tsx`
- modify: `frontend/src/components/shared/log-table/use-log-filters.ts`
- modify: `frontend/src/components/shared/log-table/log-detail-drawer.tsx`
- modify: `frontend/src/components/shared/log-table/column-picker.tsx`
- modify: `frontend/src/components/layout/command-palette.tsx`
- modify: `frontend/src/components/app-detail/handlers-tab.tsx`
- modify: `frontend/src/components/app-detail/execution-detail.tsx`
- modify: `frontend/src/components/app-detail/code-tab.tsx`
- modify: `frontend/src/components/app-detail/config-tab.tsx`
- modify: `frontend/src/components/app-detail/overview-tab.tsx`
- modify: `frontend/src/pages/logs.tsx`
- modify: `frontend/src/hooks/use-async-action.ts`
- delete: `frontend/src/hooks/use-signal.ts`
- read: `design/specs/020-frontend-foundation-migration/design.md`

Note: ~68 files total need import changes (`preact` → `react`, `preact/hooks` → `react`). The above lists the files with structural changes (useSignal→useState, error boundary, configs). All 74 `.test.tsx` files and many `.tsx` source files need the mechanical import swap — list every file individually in the actual implementation.

## Prompt

Swap the Preact runtime for React 19. Work in this order:

### 1. Package swap

```bash
cd frontend
npm uninstall preact @preact/preset-vite @tanstack/preact-query @testing-library/preact vite-css-modules
npm install react react-dom @vitejs/plugin-react @tanstack/react-query @testing-library/react react-error-boundary
npm install -D @types/react @types/react-dom
```

### 2. Config files

**`vite.config.ts`:** Replace `@preact/preset-vite` with `@vitejs/plugin-react`. Remove `vite-css-modules` plugin (Vite handles CSS Modules natively). Keep the `@` path alias.

**`vitest.config.ts`:** Same plugin swap. Keep jsdom, coverage thresholds, and all other settings.

**`tsconfig.json`:** Change `"jsxImportSource": "preact"` to `"jsx": "react-jsx"`. Update `compilerOptions` as needed for React types.

### 3. Import conversion (all files in `frontend/src/`)

Mechanical find-and-replace across ~68 files:
- `from "preact"` → `from "react"` (types: `ComponentChildren` → `ReactNode`, `JSX` → `React.JSX`, `RefObject` stays or use `React.RefObject`)
- `from "preact/hooks"` → `from "react"`
- `from "@tanstack/preact-query"` → `from "@tanstack/react-query"`
- `from "@testing-library/preact"` → `from "@testing-library/react"`

### 4. JSX attribute codemod

`class=` → `className=` across all TSX files. This includes:
- Static strings: `class="foo"` → `className="foo"`
- Template literals: `` class={`...`} `` → `` className={`...`} ``
- clsx calls: `class={clsx(...)}` → `className={clsx(...)}`

Use a codemod or targeted sed. Verify with: `grep -rn ' class=' frontend/src/ --include='*.tsx' | grep -v className | grep -v test`

### 5. Entry point

**`src/main.tsx`:** Replace `render(<App />, el)` with `createRoot(el).render(<App />)`. Import `createRoot` from `react-dom/client`.

### 6. Error boundary

**`src/components/layout/error-boundary.tsx`:** Replace `useErrorBoundary` (Preact-only) with `react-error-boundary`'s `ErrorBoundary` component. Preserve the existing fallback's visual treatment (`Card`, heading, `Button`, `data-testid="error-card"`) and `instanceof Error` guard. Add `role="alert"` for accessibility. See Convention Examples in context.md for the exact target pattern.

### 7. Local signal migration (useSignal → useState)

~16 files use `useSignal(init)` for local component state. Replace with React's `useState(init)`:
- `useSignal(initialValue)` → `useState(initialValue)`
- `.value` reads → state variable
- `.value = newValue` writes → setter function

These are local UI state (sort order, drawer open/close, filter values) — they must NOT go into the global Zustand store. Delete `src/hooks/use-signal.ts` after all consumers are converted.

Known files: `app-logs-panel.tsx`, `execution-table.tsx`, `action-buttons.tsx`, `logs.tsx`, `use-async-action.ts`, `overview-tab.tsx`, `handlers-tab.tsx`, `execution-detail.tsx`, `code-tab.tsx`, `sort-header.tsx`, `config-tab.tsx`, `table-footer.tsx`, `use-log-filters.ts` (3 calls), `command-palette.tsx` (2 calls), `log-detail-drawer.tsx`, `column-picker.tsx`.

### 8. Test setup

**`src/test-setup.ts`:** Keep all existing polyfills (rAF, ResizeObserver, matchMedia) and MSW setup. The rAF polyfill is used by application code (`command-palette.tsx:55`), not just Preact internals.

### 9. Run tests and build

```bash
cd frontend && npm run test    # 0 failures
cd frontend && npm run build   # exit 0
```

## Focus

- **`ComponentChildren` → `ReactNode`:** Preact's `ComponentChildren` type is equivalent to React's `ReactNode`. Check all 34 files that import from `"preact"` for this type usage.
- **`class=` codemod scope:** Only `.tsx` files. Do NOT change `.ts` files (they don't have JSX). Do NOT change test files' assertion strings that check for `class` attributes in rendered HTML.
- **`eslint-plugin-react-hooks-configurable`:** This devDependency may need replacing with the standard `eslint-plugin-react-hooks` now that we're on React. Check if the "configurable" variant is still needed.
- **`vite-css-modules` removal:** This plugin only generates `.d.ts` files for CSS modules. Vite handles CSS module imports natively — the `.d.ts` generation is dropped. TypeScript may need `*.module.css` declaration files; check if `src/vite-env.d.ts` or a global `.d.ts` handles this.
- **`use-signal.ts` deletion order:** Convert all 16 consumer files FIRST, then delete the hook file. If any consumer is missed, the import will fail.

## Verify

- [ ] FR#1: `frontend/package.json` lists `react`, `react-dom`, `@vitejs/plugin-react` as dependencies. No `preact` package remains.
- [ ] FR#2: `grep -rn ' class=' frontend/src/ --include='*.tsx' | grep -v className | grep -v test` returns no results.
- [ ] FR#8: All query hooks import from `@tanstack/react-query`. No `@tanstack/preact-query` imports remain.
- [ ] FR#10: `error-boundary.tsx` uses `ErrorBoundary` from `react-error-boundary` with `role="alert"`, `data-testid="error-card"`, and `instanceof Error` guard.
- [ ] AC#1: `cd frontend && npm run build` exits 0.
- [ ] AC#2: `cd frontend && npm run test` reports 0 failures across all 104 test files.
- [ ] AC#3: `grep -rn ' class=' frontend/src/ --include='*.tsx' | grep -v className | grep -v test` returns no results.
- [ ] AC#4: `grep -rn 'from.*preact' frontend/src/ --include='*.ts' --include='*.tsx'` returns no results.
