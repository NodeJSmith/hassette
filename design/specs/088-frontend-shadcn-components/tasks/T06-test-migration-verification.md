---
task_id: "T06"
title: "Switch to userEvent, update CLAUDE.md, verify E2E + demo"
status: "planned"
depends_on: ["T04", "T05"]
implements: ["FR#17", "AC#1", "AC#2", "AC#3", "AC#9", "AC#10"]
---

## Summary

Add `@testing-library/user-event` to dev dependencies. Switch tests for all replaced components from `fireEvent` to `userEvent` for richer interaction testing. Update CLAUDE.md's CSS Architecture section to reflect the new shadcn component locations and token alias layer. Run the full vitest suite, E2E suite, and demo stack to verify visual parity.

## Target Files

- modify: `frontend/package.json`
- modify: `frontend/src/components/shared/button.test.tsx` (or its new location)
- modify: `frontend/src/components/shared/badge.test.tsx`
- modify: `frontend/src/components/shared/card.test.tsx`
- modify: `frontend/src/components/shared/tooltip.test.tsx`
- modify: `frontend/src/components/shared/confirm-dialog.test.tsx`
- modify: `frontend/src/components/shared/info-popover.test.tsx`
- modify: `frontend/src/components/layout/command-palette.test.tsx`
- modify: `frontend/src/components/layout/time-preset-selector.test.tsx`
- modify: `frontend/src/components/layout/sidebar.test.tsx`
- modify: `frontend/src/components/shared/execution-table.test.tsx`
- modify: `CLAUDE.md`
- read: `frontend/src/test/render-helpers.tsx`
- read: `frontend/src/test-setup.ts`

## Prompt

**Install userEvent:**
`npm install --save-dev @testing-library/user-event`

**Switch test interaction patterns:**
For all test files listed in Target Files, replace `fireEvent.click()` with `const user = userEvent.setup(); await user.click()`, `fireEvent.change()` with `await user.type()` or `await user.selectOptions()`, etc. The `userEvent.setup()` call should be at the top of each test (not shared across tests -- userEvent instances maintain internal state).

Note: earlier tasks (T02-T05) already rewrote test assertions for new component APIs. This task focuses specifically on the `fireEvent` -> `userEvent` migration and any test cleanup that was deferred.

**Update CLAUDE.md:**
In the CSS Architecture section, update:
- "Shared components" guidance: `Button`, `Badge`, `Chip`, `Card` are now shadcn components in `components/ui/`, not shared components in `components/shared/`. Reference the shadcn component imports.
- Add a note about the token alias layer: shadcn-named tokens (`--background`, `--primary`, etc.) are aliases in `global.css` pointing at the original token values in `tokens.css`. New code should use the shadcn-named tokens.
- Remove references to `@floating-ui/dom` manual usage (now handled by Radix internally).

**Verification (the real test):**
1. Run the full vitest suite: `cd frontend && npm run test` -- all tests must pass.
2. Run E2E: `uv run nox -s e2e` -- behavioral parity with pre-migration state.
3. Run demo stack: `mise run demo` -- visually verify all 7 pages (apps, handlers, logs, config, diagnostics, app-detail, design) render correctly.

The E2E suite runs against a real backend and confirms end-to-end behavior. The demo stack is the visual parity check -- unit tests verify component logic, visual QA verifies rendered appearance.

## Focus

- The `userEvent` migration is a test-quality improvement, not a behavior change. If a test was passing with `fireEvent`, it should still pass with `userEvent` -- but `userEvent` may reveal real bugs that `fireEvent` masked (e.g., disabled buttons that `fireEvent.click` fires anyway but `userEvent.click` respects).
- `test-setup.ts` already polyfills `requestAnimationFrame` and `ResizeObserver` for jsdom -- `userEvent` may need these polyfills, so verify they're still working.
- `render-helpers.tsx`'s `renderWithAppState` wraps in `QueryClientProvider` and seeds Zustand -- this is unchanged; `userEvent` is a testing-library concern, not a provider concern.
- The demo stack requires Docker. If Docker is unavailable, note that AC#10 cannot be locally verified and will be confirmed in CI.
- For E2E tests, selectors may need updates if `data-testid` attributes changed on replaced components. Run the e2e suite and fix any selector failures.

## Verify

- [ ] FR#17: Tests for replaced components use `userEvent.setup()` + `await user.click()`/`user.type()` instead of `fireEvent.click()`/`fireEvent.change()`
- [ ] AC#1: `cd frontend && npm run build` exits 0 (full tree after all tasks merged)
- [ ] AC#2: `cd frontend && npm run test` reports 0 failures
- [ ] AC#3: `cd frontend && npm run typecheck` exits 0 (full tree after all tasks merged)
- [ ] AC#9: `uv run nox -s e2e` passes
- [ ] AC#10: Demo stack (`mise run demo`) renders all 7 pages without visual regression
