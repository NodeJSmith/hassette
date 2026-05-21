# Nitpick Report — frontend/src/pages, hooks, api, utils, state

**Scope:** All `.ts`, `.tsx`, `.css` files in `frontend/src/pages/`, `hooks/`, `api/`, `utils/`, `state/`
**Exclusion:** `api/generated-types.ts` (auto-generated)

---

## 1. Magic Numbers and Strings

**`use-websocket.ts:9`** — `10_000` (handshake timeout) is a named constant at the module level (`HANDSHAKE_TIMEOUT_MS`), but the literal `"INFO"` at line 10 is also named (`DEFAULT_LOG_LEVEL`). Both are fine. *(No violation here — noted for confirmation.)*

**`use-telemetry-health.test.ts:27`** — Inline literal object `{ degraded: false, dropped_overflow: 0, dropped_exhausted: 0, dropped_no_session: 0, dropped_shutdown: 0, error_handler_failures: 0 }` repeated verbatim at lines 27, 91, 153 (×2), 154, 187, 188. This is an inlined default response shape duplicated six times with no shared factory.

**`use-telemetry-health.test.ts:30`** — `30_000` appears as a bare literal argument to `vi.advanceTimersByTime` at lines 56, 116, 125, 209 without referencing the exported `BASE_INTERVAL_MS` constant from the file under test.

**`use-telemetry-health.test.ts:60`** — `60_000` appears as a bare literal argument at lines 134, 166, 169, 179, 247 without referencing `BASE_INTERVAL_MS * 2` (the first-failure backoff).

**`use-filtered-signal-refetch.test.ts:29,44,68,87`** — `500` and `1500` as bare literals passed to `useFilteredSignalRefetch` throughout the test file rather than using the already-exported `WS_DEBOUNCE_DELAY_MS` and `WS_DEBOUNCE_MAX_WAIT_MS` constants. Violated at lines 29, 44, 68, 87, 113, 153, 175.

**`apps.tsx:249`** — `"35%"`, `"12%"`, `"22%"`, `"10%"`, `"11%"`, `"10%"` are inline `col` width percentages with no named constant or comment explaining the layout intent.

**`handlers.tsx:171–180`** — Same pattern: `"7%"`, `"13%"`, `"20%"`, `"13%"`, `"7%"`, `"7%"`, `"9%"`, `"9%"`, `"8%"`, `"7%"` as inline col widths.

**`config.tsx:120`** — `"—"` as a string literal compared inline: `row.value === "—"`. The em-dash sentinel should be a named constant given its use in both `formatValue` and the render branch.

**`apps.module.css:100`** — `calc(var(--sp-4) + var(--sp-0))` used as a magic layout offset with no comment explaining why this specific combination positions `instanceCorner`.

**`apps.module.css:113`** — Hard-coded `200px` for `.errorCell max-width`.

**`app-detail.module.css:59`** — `280px` as a magic `minmax` floor in the instance grid: `minmax(280px, 1fr)`.

**`app-detail.module.css:165`** — `140px` as the `instanceSwitcherLabel` max-width.

**`logs.module.css:26`** — `2px` as a bare pixel value for `outline-offset` rather than using `var(--sp-0)` (the pattern used everywhere else in the same codebase).

**`config.module.css:38`** — `320px` and `200px` as bare pixel values for `.configTableKey` width and `min-width`.

**`diagnostics.module.css:35`** — `1px` for `padding` in `.staleBadge`: `padding: 1px var(--sp-2)`. Every other padding in the file uses spacing tokens.

**`diagnostics.module.css:190`** — `3ch` for `.dropValue min-width`. Magic unit; no token or comment.

**`use-scoped-api.ts:29`** — The `PRESET_WINDOW_SECONDS` values `3600`, `86400`, `604800` duplicate the named constants `SECONDS_PER_HOUR`, `SECONDS_PER_DAY` already in `utils/format.ts`. Two separate places encode the same time-conversion constants.

**`handlers-rows.tsx:50`** — `Date.now() / MS_PER_SECOND` is inlined — `MS_PER_SECOND` is imported but the division is also inlined on the same line without naming the result (e.g. `const nowSeconds = ...`), making `isOverdue` a two-expression one-liner that is harder to read than necessary.

---

## 2. Scattered Constants

**`use-document-title.ts:3` vs `use-document-title.ts:8`** — `"Hassette"` appears as a string literal in both the suffix constant `SUFFIX = " - Hassette"` (line 3) and the cleanup function `document.title = "Hassette"` (line 8). The bare `"Hassette"` in the cleanup is inconsistent — it should reference a named constant rather than repeating the brand name.

**`use-websocket.test.ts` (multiple)** — `"INFO"` (the default log level) appears as an inline string literal in test assertions at lines 254, 295 rather than referencing the `DEFAULT_LOG_LEVEL` constant exported from the module under test (which is unexported — a separate issue, but the test inlines it regardless).

**`create-app-state.ts:248`** — `RELATIVE_TIME_TICK_MS = 30_000` is defined at the bottom of the file (after the main export), separated from the other constants. It should be at the top with imports.

**`apps.tsx:29`** — `FILTER_OPTIONS` and `VALID_SORT_KEYS` are module-level constants but placed after the import block, inside what visually reads as the component file body with no section separation. Fine as placement, but `VALID_SORT_KEYS` at line 41 is only used once to validate URL params and could more clearly live near the sort-state construction logic.

**`handler-rows.ts:57`** — `NO_NEXT_RUN = Number.MAX_SAFE_INTEGER` is defined as a module-level constant inside `handler-rows.ts`. This is the correct pattern, but it is unnamed at the usage site in a way that makes the sentinel intent opaque to readers of `compareHandlerRows` who don't know `NO_NEXT_RUN` was defined specifically for this purpose.

---

## 3. Ternary Abuse

**`apps.tsx:139–140`** — Ternary with a 60+ character condition:
```ts
const filter: FilterId = rawFilter !== null && (FILTER_OPTIONS as readonly string[]).includes(rawFilter)
  ? rawFilter as FilterId : "all";
```
The condition alone is ~75 characters. This should be extracted into a helper or guard.

**`apps.tsx:167–169`** — Three-way chained logic expressed as a single ternary spanning multiple expressions on one line:
```ts
const windowSeconds = uptimeSeconds.value !== null && uptimeSeconds.value !== undefined
  ? (effectiveTimePreset.value === "since-restart" ? uptimeSeconds.value : PRESET_WINDOW_SECONDS[effectiveTimePreset.value])
  : null;
```
Nested ternary inside a long-condition ternary — both the outer condition and the inner ternary should be extracted.

**`app-detail.tsx:109–110`** — Multi-expression ternary chain for `liveStatus`:
```ts
const liveStatus = showParentOverview
  ? manifest?.status ?? "unknown"
  : wsStatus ?? currentInstance?.status ?? manifest?.status ?? "unknown";
```
Four levels of `??` chaining in one branch is readable enough alone, but the whole expression is long enough (>60 chars per branch) that it benefits from extraction.

**`apps-table-row.tsx:42`** — Long ternary inside a JSX attribute:
```tsx
aria-label={`${isExpanded ? "Collapse" : "Expand"} ${app.app_key}`}
```
Fine by itself — this is a common inline pattern and under the threshold.

**`config.tsx:120–122`** — Ternary used to assign a className based on a string sentinel:
```tsx
const valueClass = row.value === "—"
  ? `${styles.configTableValue} ${styles.configTableValueEmpty}`
  : styles.configTableValue;
```
Not abusive per se, but the string-template class concatenation `${styles.x} ${styles.y}` should use `clsx` (which is already imported as a dependency of the project, just not imported in this file).

**`diagnostics.tsx:197–198`** — Ternary inside JSX attribute that combines a type coercion:
```tsx
const kind = issue.severity === "err" ? "err" : "warn";
```
Only two possible values with no `"info"` handling despite `SEVERITY_ORDER` including it — a silent fallback to `"warn"` for `severity === "info"` boot issues. Structural issue aside, the ternary itself is short enough to be acceptable.

---

## 4. CSS and Styling Sins

**`apps.module.css:163`** — Breakpoint `900px` defined as a magic number in `@media screen and (max-width: 900px)`. This value does not correspond to any of the three named breakpoint constants in `use-media-query.ts` (`768`, `480`, `1024`). It is a fourth breakpoint with no named constant and no TS-side counterpart.

**`app-detail.module.css:210`** — Same issue: `@media screen and (max-width: 900px)` — unregistered breakpoint, no constant.

**`apps.module.css:180`** and **`app-detail.module.css:217`** — `@media (max-width: 768px)` — correct breakpoint value, but uses `(max-width: ...)` without the `screen` prefix while the 900px breakpoint above it uses `@media screen and (max-width: 900px)`. Inconsistent media query syntax within the same files.

**`handlers.module.css:73`** — Same inconsistency: `@media (max-width: 768px)` missing `screen and`.

**`config.module.css:51`** — Same: `@media screen and (max-width: 768px)` — this one has `screen and`, so within `config.module.css` it's consistent, but cross-file the pattern is inconsistent.

**`app-detail.module.css:204–215`** — The `@media screen and (max-width: 900px)` block sets `.tabBtn` styles (min-height, padding), and the `@media screen and (max-width: 768px)` block at lines 217–231 also sets `.tabBtn` styles (same properties, same values). The two rules for `.tabBtn` are duplicated across both breakpoints — the 768px rule repeats the 900px rule verbatim for `min-height` and `padding`.

**`diagnostics.module.css:35`** — `1px` padding in `.staleBadge` is a bare pixel value while the rest of the file uses spacing tokens exclusively. See §1 above.

**`logs.module.css:26`** — `outline-offset: 2px` is a bare pixel value; the rest of the codebase uses `var(--sp-0)` for this.

**`apps.module.css:163`** — `@media screen and (max-width: 900px)` block contains two rules: one for `.expand` and one for column hiding. These are semantically different concerns (tap target vs. column visibility) bundled under one breakpoint.

---

## 5. Dead Code

**`diagnostics.tsx:20–22`** — Section divider comments using Unicode box-drawing characters (`──────────...`) throughout the file (lines 20, 72, 134, 171, 229, 332). These are "No Section Divider Comments" violations per `coding-style.md`. Six instances.

**`use-api.test.ts:58`** — The `await new Promise((r) => setTimeout(r, 50))` pattern appears 10 times across the test file (lines 58, 77, 92, 108, 129, 136, 161, 188, 232, 259). Identical boilerplate not extracted into a named helper (e.g., `const tick = () => new Promise<void>((r) => setTimeout(r, 50))`). Same pattern appears in `use-scoped-api.test.ts` (lines 41, 58, 264, 398, 422), `use-filtered-signal-refetch.test.ts` (implicit via `vi.advanceTimersByTime`), and `use-telemetry-health.test.ts`.

**`use-websocket.test.ts:9`** — `static OPEN = 1` on `MockWebSocket` (line 9) is defined but then `readyState = 1` at line 15 is set directly as a literal — the constant is not used to set the default value.

**`use-websocket.test.ts:27`** — `this.readyState = 3` in `close()` — uses the literal `3` (CLOSED) instead of a named constant, while `OPEN = 1` was defined above for exactly this kind of purpose.

**`use-scoped-api.test.ts:17`** — `function nowSeconds(): number { return Date.now() / 1000; }` — `1000` should reference `MS_PER_SECOND` imported from `utils/format` (which is not imported in the test file, though it's used in the implementation).

---

## 6. Naming Inconsistencies

**`diagnostics.tsx:348`** — `const { data: systemStatus, loading, error: loadError }` — the rename `error: loadError` is inconsistent with `loading` (not renamed) and `data: systemStatus` (renamed). The asymmetry adds cognitive load — either rename all or none.

**`handlers.tsx:87–88`** — Function `onSort` defined inline in the component body (not as an arrow constant). All other handlers in the same file (`clearFilters`, `buildEmptyTitle`) are arrow functions or arrow constants. Mixed definition styles.

**`handlers.tsx:141`** — `buildEmptyTitle` is a `function` declaration inside a component, returns a string — named `build*` implying construction but essentially a `get*` or computed value. Inconsistent with other helpers named as nouns (`emptyStateTitle`, `footer`, `searchInput`).

**`app-detail.tsx:91–96`** — `staleListeners`/`staleJobs` — names contain "stale" but the pattern is actually "hold last good data during reload" (stale-while-revalidate). The names are accurate but not consistent with any other naming in the codebase.

**`use-api.ts:61–62`** — `requestIdRef` and then `hasFetchedRef` at line 63, `lazyRef` at line 64, `enabledRef` at line 65 — four ref variables named `*Ref` in sequence. Then `refetch` at line 67 is also a ref but named without the `Ref` suffix. The ref-naming convention is inconsistently applied.

**`handlers-rows.tsx:46`** — `useHandlerRowData` — the function is a custom hook (uses `useRelativeTime`) but its name prefix `use*` is appropriate. However the return object uses `errorRate`, `avgDur` (abbreviated), `isOverdue` (boolean with `is` prefix — good), `nextRunDisplay` (noun phrase). Mixing full words (`errorRate`) with abbreviations (`avgDur`) in the same return object.

**`create-app-state.ts:73`** — `let _updateLogSubscription` — uses underscore prefix for a private variable. Per project style rules, underscore prefixes are not appropriate here; this is a closure-private variable that could just be named `updateLogSubscription`.

---

## 7. Structural Messiness

**`apps.tsx`** — File is 291 lines. Below the 400-line limit but contains: a filter type + constant block, a stats-strip helper function, a filter-content component, and the main page component — four distinct structural responsibilities. The `StatusFilterContent` component (lines 76–108) and `buildAppsCells` (lines 45–72) could be extracted to co-located helper files.

**`app-detail.tsx`** — 229 lines. Contains both the `Tab` subcomponent (lines 29–52) and the `AppDetailPage` component. The `Tab` component is not exported and is small enough to stay inline, but `AppDetailPage` itself has 12+ useEffect/useScopedApi/useFilteredSignalRefetch calls — it's approaching god-component territory.

**`diagnostics.tsx`** — 391 lines. Contains five separate component definitions (`DiagServiceRow`, `ServicesPanel`, `BootIssuesPanel`, `DropCounterRow`, `TelemetryPanel`, `DiagnosticsPage`). This exceeds the 400-line soft ceiling and clearly warrants splitting into at least two files.

**`apps-table-row.tsx:42`** — The expand button inline JSX spans one very long line:
```tsx
<button type="button" class={styles.expand} onClick={onToggle} aria-expanded={isExpanded} aria-label={`${isExpanded ? "Collapse" : "Expand"} ${app.app_key}`} data-testid="app-row-expand">
```
~160 characters on a single line; well over any reasonable line length.

**`apps-table-row.tsx:100–122`** — Instance row rendering inside the same `AppTableRow` return — the `{isMulti && isExpanded && app.instances?.map(...)}` block at line 97 renders a secondary `<tr>` with a full cell structure. This embedded table-row logic inside a component that already renders one table-row makes the component render two different things depending on state.

**`use-api.ts:98–114`** — Render-phase signal writes with comment explaining the reasoning. This is unusual and not obvious — the comment is necessary but the pattern itself is surprising. The block from line 98–114 is 17 lines of conditional logic that executes during render, which is non-standard and hard to audit.

**`use-websocket.ts:59–147`** — The `switch` statement inside `socket.onmessage` is 90 lines. Each case is a direct state write, which is appropriate, but `case "connected"` alone (lines 61–95) is 35 lines and contains multiple distinct operations (backoff reset, signal writes, reconnect logic, log subscription). This case could be extracted to a named function.

---

## 8. Import Hygiene

**`diagnostics.tsx:8–9`** — Two separate imports from `"../api/endpoints"` on consecutive lines:
```ts
import { getSystemStatus } from "../api/endpoints";
import type { BootIssue } from "../api/endpoints";
```
These should be merged into a single import statement.

**`diagnostics.tsx:10`** — `import type { components } from "../api/generated-types"` — imports from the generated types file directly. The project convention (established in `api/endpoints.ts`) is to re-export all generated types through `endpoints.ts` type aliases. This import bypasses that convention.

**`use-api.test.ts:3`** — `import { h } from "preact"` — imported but only used in the `createWrapper` helper to call `h(AppStateContext.Provider, ...)`. The equivalent JSX `<AppStateContext.Provider value={state}>{children}</AppStateContext.Provider>` would be cleaner and not require the explicit `h` import.

**`use-relative-time.test.ts:3`** — Same pattern: `import { h } from "preact"` used only for the wrapper factory.

**`use-scoped-api.test.ts:3`** — Same: `import { h } from "preact"` for wrapper factory only.

**`apps.tsx:10`** — `import { type StatusKind } from "../utils/status"` — type-only import not using the `import type` form. It uses `{ type X }` inline syntax. Fine technically, but inconsistent — other files in the codebase use `import type { X }` at the statement level. Lines 13, 22 in the same file do use `{ type X }` inline as well — internally consistent within the file, but the style differs from some other files.

---

## 9. Hard-Coded Environment Values

**`use-websocket.ts:38`** — `"/api/ws"` is a hard-coded path literal. Other endpoint paths live in `api/endpoints.ts`, but the WebSocket URL is constructed inline with no shared constant:
```ts
const socket = new WebSocket(`${proto}//${location.host}/api/ws`);
```

**`api/client.ts:3`** — `const BASE_URL = "/api"` — this is a module-level constant (correct), but it is defined in `client.ts` and not re-exported, so there is no single place to change the API base path if it ever changes. The WebSocket hook in `use-websocket.ts` duplicates the `/api` prefix implicitly.

---

## 10. Formatting Inconsistencies

**`apps.module.css:163` vs `apps.module.css:180`** — Inconsistent `@media` syntax within the same file: `@media screen and (max-width: 900px)` at line 163 vs `@media (max-width: 768px)` at line 180. See §4.

**`app-detail.module.css:210` vs `app-detail.module.css:217`** — Same within-file inconsistency: `@media screen and (...)` then `@media (...)` two rules later.

**`handlers.tsx:87`** — `function onSort(...)` is a `function` declaration inside a component, while all other handlers are arrow functions. Mixed function definition styles within one file.

**`use-api.ts:67–88`** — `refetch` is assigned as `useRef(async () => { ... }).current` — an unusual inline-IIFE-into-ref pattern. The closing `}).current` on line 88 is visually disconnected from the opening on line 67, making the structure hard to parse at a glance.

**`use-telemetry-health.test.ts:27`** — The mock return value object is written on one very long line (~130 chars) without line breaks. Same at lines 91, 153, 154, 187, 188.

**`apps-table-row.tsx:66–68`** — Spread attributes and ternary-assigned event handlers across three lines inside a `<td>` using `{...(condition ? { ... } : {})}` — the empty-object fallback spread is a verbose pattern that could instead use optional props or conditional rendering.

---

## Summary

| Category | Findings |
|---|---|
| Magic Numbers and Strings | 16 |
| Scattered Constants | 5 |
| Ternary Abuse | 5 |
| CSS and Styling Sins | 10 |
| Dead Code | 5 |
| Naming Inconsistencies | 7 |
| Structural Messiness | 7 |
| Import Hygiene | 6 |
| Hard-Coded Environment Values | 2 |
| Formatting Inconsistencies | 6 |
| **Total** | **69** |

**Highest-impact cleanup:** Extracting the duplicated `{ degraded: false, dropped_*: 0, ... }` mock response object in `use-telemetry-health.test.ts` into a shared factory, and replacing all the bare `500`/`1500` literals in `use-filtered-signal-refetch.test.ts` with the already-exported `WS_DEBOUNCE_DELAY_MS`/`WS_DEBOUNCE_MAX_WAIT_MS` constants — these two test files together account for 20+ of the magic-number violations and are trivial to fix.
