---
task_id: "T01"
title: "Add useQueryParams hook, correctUrl utility, and effectiveTimePreset signal"
status: "planned"
depends_on: []
implements: ["FR#14", "FR#16", "FR#8", "FR#10", "AC#9", "AC#13", "AC#14"]
---

## Summary
Create the foundational utilities that all subsequent tasks depend on: a `useQueryParams` hook for reading/writing URL query parameters, a `correctUrl` function for centralized URL correction, and an `effectiveTimePreset` computed signal that bridges URL overrides with the existing localStorage-backed time preset. Also update `useScopedApi` to read from `effectiveTimePreset` instead of `timePreset`.

## Prompt
Create three new files and update two existing files:

1. **Create `frontend/src/hooks/use-query-params.ts`** — a thin hook wrapping wouter's `useSearch()` and `useLocation()`. See design doc section "Architecture > useQueryParams Hook" for the API contract:
   - `get(key)` returns the param value or null
   - `set(updates, options?)` updates multiple params at once; `push: false` (default) replaces history, `push: true` pushes a new entry
   - Setting a value to `null` or `""` removes the param
   - Values must be encoded via `encodeURIComponent` on write and decoded on read
   - When the resulting param set equals the current one, `set()` must no-op (no spurious navigation)

2. **Create `frontend/src/hooks/use-correct-url.ts`** — exports a `correctUrl(correctedUrl: string, reason: string)` function that calls `navigate(correctedUrl, { replace: true })`. The `reason` parameter is stored but not displayed (future toast hook point). Export the function and the stored reasons for testability.

3. **Update `frontend/src/state/create-app-state.ts`** — add a `urlWindowParam` signal (initially `null`) and an `effectiveTimePreset` computed signal: `effectiveTimePreset = computed(() => urlWindowParam.value ?? timePreset.value)`. Export both from the app state. The `urlWindowParam` signal is page-scoped — pages write to it; it does not persist to localStorage.

4. **Update `frontend/src/hooks/use-scoped-api.ts`** — change the hook to read `effectiveTimePreset` instead of `timePreset` from app state. The `resolveSince()` function and all downstream logic should use the effective value. Update the deps array accordingly.

5. **Write unit tests** for both hooks:
   - `frontend/src/hooks/use-query-params.test.ts` — test get/set, default omission, push vs replace, empty-value removal, no-op on same-value, encoding
   - `frontend/src/hooks/use-correct-url.test.ts` — test URL replacement and reason recording
   - Update `frontend/src/hooks/use-scoped-api.test.ts` — verify it reads `effectiveTimePreset` not `timePreset`

## Focus
- Follow the existing hook test patterns in `frontend/src/hooks/use-api.test.ts` and `use-scoped-api.test.ts` for test structure and mocking
- `useSearch()` from wouter returns the raw query string without the leading `?`
- `useLocation()` returns `[location, navigate]` — use the `navigate` function for URL updates
- The `no-op guard` in `set()` is critical — without it, same-value updates trigger spurious navigation and re-render cascades (challenge overflow finding OF-3)
- `useScopedApi` currently reads `timePreset` at `use-scoped-api.ts:62` — change to `effectiveTimePreset`
- `PRESET_WINDOW_SECONDS` is exported from `use-scoped-api.ts` and used by `apps.tsx:8` — this export must not change

## Verify
- [ ] FR#14: `useQueryParams.set()` omits params set to `null` or `""` from the URL
- [ ] FR#16: `correctUrl` replaces the URL and records the reason string; reason is accessible for future toast integration
- [ ] FR#8: `effectiveTimePreset` returns the `urlWindowParam` value when set, falls back to `timePreset` when null
- [ ] FR#10: Writing to `urlWindowParam` does not update localStorage
- [ ] AC#9: Setting all params to their defaults results in a clean URL with no query string
- [ ] AC#13: Confirm via unit test that default values produce empty query string
- [ ] AC#14: `correctUrl` can be called with a corrected URL and reason; URL is replaced
