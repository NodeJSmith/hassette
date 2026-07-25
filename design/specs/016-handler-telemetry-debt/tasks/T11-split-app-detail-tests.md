---
task_id: "T11"
title: "Split app-detail.test.tsx"
status: "done"
depends_on: ["T10"]
implements: ["FR#11", "AC#3"]
---

## Summary

Split `frontend/src/pages/app-detail.test.tsx` (694 lines) into 3 topic-grouped test files + a shared helper file. Migrate from the local `createWrapper` to `renderWithAppState` + `stateOverrides`. Delete the original file.

## Target Files

- create: `frontend/src/pages/app-detail.header.test.tsx`
- create: `frontend/src/pages/app-detail.tabs.test.tsx`
- create: `frontend/src/pages/app-detail.instances.test.tsx`
- create: `frontend/src/pages/app-detail.test-helpers.ts`
- delete: `frontend/src/pages/app-detail.test.tsx`
- read: `frontend/src/test/render-helpers.tsx`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

Read `frontend/src/pages/app-detail.test.tsx` fully. Split the tests into topic-grouped files:

**`app-detail.test-helpers.ts`** (shared, not a test file — `.ts` not `.test.ts`):
- `setupApi(manifest, listeners, jobs)` helper
- `setupMultiInstanceParent()` helper (if extracted)
- Shared `vi.mock()` declarations for all child-component stubs
- Export any shared constants or captured variables (e.g., `capturedOnSwitchToCode`)

**`app-detail.header.test.tsx`** — header, subtitles, badges:
- Tests for app_key rendering, display name, action buttons
- Badge tests (auto-loaded, no-autostart)
- Subtitle meta rendering

**`app-detail.tabs.test.tsx`** — tab rendering and selection:
- Tab strip rendering, default tab selection
- Tab link generation, aria-selected states
- Tab content rendering (handlers, code, config, overview, logs)

**`app-detail.instances.test.tsx`** — instance management:
- Instance switcher rendering
- Invalid instance param correction (out-of-range, malformed, negative)
- Multi-instance parent view, instance grid, redirect logic
- Line deep-link preservation

**Migration from createWrapper to renderWithAppState:**
- Replace `createWrapper(state)` with `renderWithAppState` from `../test/render-helpers`
- Pass `{ uptimeSeconds: signal(120) }` (or equivalent) as `stateOverrides`
- Remove the local `createWrapper` function entirely
- Verify each test individually — if any test breaks, the mutable-state assumption was real and needs investigation

Each split file imports from `./app-detail.test-helpers` and sets up its own `beforeEach`.

Delete the original `app-detail.test.tsx` after all tests are distributed.

## Focus

- Count tests before splitting: `cd frontend && npx vitest run src/pages/app-detail.test.tsx --reporter=verbose 2>&1 | grep -c "✓"`. Do the same across split files after.
- The `createWrapper` migration is the riskiest part. If a test fails after switching to `renderWithAppState`, investigate whether it actually mutates state between renders — the design doc says none do, but verify.
- `vi.mock()` calls must be at module scope in each test file — they can't be imported from the helper file. Either duplicate them or use Vitest's setup file pattern.

## Verify

- [ ] FR#11: `app-detail.test.tsx` no longer exists; 3 test files + shared helper exist
- [ ] AC#3: `cd frontend && npm test` passes with the same test count as before the split
