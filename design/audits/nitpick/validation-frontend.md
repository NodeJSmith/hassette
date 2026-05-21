# Nitpick Validation — Frontend Components, Pages, and Hooks

**Reports validated:** `frontend-components.md`, `frontend-pages-hooks.md`
**Validation date:** 2026-05-21

---

## frontend-components.md

### False Positives

#### `font-size: 10px` flagged as token bypass — PARTIALLY FALSE POSITIVE

The nitpicker frames this as "if `var(--fs-micro)` exists but isn't being used, these are token bypasses." This framing is wrong: `--fs-micro = 11px`, which is a different value. There is no 10px token in `tokens.css`. These are intentionally sub-micro sizes (e.g., badge `.xs` variant, chip `.sm` variant, mono labels) that sit below the smallest type-scale token.

The finding is still **valid as a missing token** — the value appears in 6+ files and should become `--fs-xs` or similar — but it is not a "token bypass," and the per-file flagging is redundant. Count as **1 confirmed finding** (missing token), not 6 separate violations.

Affected files: `badge.module.css:17`, `chip.module.css:58`, `detail-panel.module.css:10`, `execution-logs.module.css:6`, `unified-handler-row.module.css:71`, `config-tab.module.css:143`.

#### `outline-offset: 2px` flagged as token inconsistency — FALSE POSITIVE (runtime), CONFIRMED (source)

`--sp-0 = 2px`. At runtime these are identical. The finding is technically valid as a source-consistency issue (different spellings of the same value), but the nitpicker's implication that one is "wrong" is overstated. Confirmed as a **low-severity formatting inconsistency**, not a functional bug.

#### `em` values in `badge.module.css` and `button.module.css` — FALSE POSITIVE

`em`-based padding/sizing in badge and button variants is intentional design system technique: it makes these components scale relative to their own `font-size`. `0.15em`, `0.55em`, `0.4em` etc. are not "magic numbers" in this context — they are the standard way to write proportional padding on typographic UI elements. No token system defines `em` fractions at this granularity; they live in the component. Not violations.

#### "Dead CSS" in `detail-panel.module.css` (`.tracebackSection`, `.errorLine`, `.tracebackFrames`) — FALSE POSITIVE

The nitpicker calls these dead and says they "should live in `traceback-viewer.module.css`." However, `traceback-viewer.tsx` **does** import `detail-panel.module.css` and uses all three classes (lines 19, 23, 26). The cross-component style import is a **structural messiness** finding (confirmed separately in §7), but the classes are not dead.

#### "Dead CSS" `.configTableColType {}` and `.configTableColValue {}` — FALSE POSITIVE

The nitpicker lists these under dead code. Both are actively used in `config-tab.tsx` (lines 94-95, 108), serving as CSS Modules class hooks. `.configTableColType` also gets `display: none` at the mobile breakpoint (line 269). Empty base rules that exist solely for responsive overrides or as module hooks are not dead code.

#### `STORAGE_VERSION = 1` in `use-column-visibility.ts` — NOT A VIOLATION

The nitpicker notes this as "worth noting for migration awareness." This is a named constant at module level — exactly the right pattern. No action needed.

#### `static OPEN = 1` on `MockWebSocket` — FALSE POSITIVE

The report flagged `use-websocket.test.ts` here, but that file is in `hooks/`, covered by `frontend-pages-hooks.md`. No `MockWebSocket` exists in the components directory. This citation belongs to the other report (addressed there).

---

### Confirmed Findings — frontend-components.md

**1. Magic Numbers and Strings** — Confirmed: 9 distinct issues (collapsing the 6×`10px` into 1 missing-token finding)
- `scrollHeight="340px"` in `app-logs-panel.tsx:34` — unnamed layout offset
- `"404"` string status code in `code-tab.tsx:108`
- `280px`, `3px` box-shadow, `3ch` tab-size in `code-tab.module.css`
- `10px`/`9px` padding, `200px` max-height in `config-tab.module.css`
- `overview-tab.tsx:62` passes `"400px"` as a prop that is a separate literal from `--log-scroll-max-height: 400px` in the CSS — no shared source of truth
- `font-size: 10px` repeated 6+ times with no token — add `--fs-xs` or equivalent
- `letter-spacing: 0.5px` in `detail-panel.module.css`, `execution-logs.module.css`, `chip.module.css` — no token
- `--drawer-width: 400px` in `log-table.module.css` and bare `width: 400px` in `log-detail-drawer.module.css` with acknowledgment comment but no shared variable
- SVG dot `width: "5px"`, `height: "5px"` inline in `filter-icon.tsx`

**2. Scattered Constants** — Confirmed: 4
- `STATUS_DOT_SIZE = 10` defined independently in `execution-table.tsx:13` and `handler-health-card.tsx:31`
- Bare `50` fetch limit in `listener-detail.tsx:60` and `job-detail.tsx:50` (vs `REST_FETCH_LIMIT` already in use elsewhere)
- `overview-tab.tsx:62` / `overview-tab.module.css:15` 400px duplication
- `SPOTLIGHT_LIMIT = 3` in `error-spotlight.tsx` mirrors `--health-grid-rows: 3` in `overview-tab.module.css` with no shared reference

**3. Ternary Abuse** — Confirmed: 4 (the `recent-activity-section` 3-level chain, `config-tab` nested ternary, `handler-list` multi-branch ternary, `unified-handler-row` two-level ternary). The `job-detail.tsx:82` two-branch ternary is borderline and low priority.

**4. CSS / Styling Sins** — Confirmed: 6
- `font-size: 10px` repeated (missing token — see §1)
- `letter-spacing: 0.5px` repeated (missing token)
- `!important` without comment in `config-tab.module.css:148-149`
- Inconsistent `@media screen and` vs `@media (max-width: …)` across files
- Breakpoints `768px`, `900px`, `1024px` missing sync comments where `handlers-tab.module.css` already sets the pattern
- `transition: all var(--t-fast)` in `log-detail-drawer.module.css:78` — performance anti-pattern; all other transitions target specific properties

**5. Dead Code** — Confirmed: 3
- 11 dead CSS classes in `config-tab.module.css` (`.colAction`, `.configFields`, `.configField`, `.configFieldHeader`, `.configFieldName`, `.configFieldType`, `.configFieldRequired`, `.configFieldValue`, `.configFieldValueMissing`, `.configFieldNote`, `.redacted`). Note: `.divider` and `.empty` are also unused but have display:none and padding styling respectively that may be intentional stubs.
- `execution-table.module.css:9` — `.statusCell {}` empty rule block; the class IS used in TSX but the CSS rule has no declarations (could be removed or the `statusCellInner` wrapper handles all styling)
- `.sectionLabel.withRule::after` in `log-detail-drawer.module.css:194` — `withRule` class is never applied in `log-detail-drawer.tsx`
- Stale `import { h } from "preact"` in `unified-handler-row.test.tsx:4` — `h` IS used (line 12: `h(AppStateContext.Provider, ...)`), so this is a **FALSE POSITIVE** — not a stale import

**6. Naming Inconsistencies** — Confirmed: 4
- Single-letter `l` and `j` in `handler-list.tsx` and `unified-handler-row.tsx`
- `isFailing` local boolean shadowing imported `isFailing` function from `overview-tab-helpers.ts`
- `failed` (count) / `failing` (predicate) adjacent naming confusion in `handler-health-card.tsx`
- Duplicate `data-testid="config-values-table"` on two `<table>` elements in `config-tab.tsx`

**7. Structural Messiness** — Confirmed: 5
- Cross-component style import: `traceback-viewer.tsx` imports from `detail-panel.module.css` — classes should move to `traceback-viewer.module.css`
- Cross-component style import: `handler-health-grid.tsx` imports from `overview-tab.module.css`
- `overview-tab.test.tsx` (559 lines) and `handlers-tab.test.tsx` (508 lines) exceed the 400-line guideline
- Duplicate test cases in `unified-handler-row.test.tsx:145-167` — Enter and Space tests are structurally identical (same `fireEvent.click` call, same assertion, no behavioral difference tested)
- `key={idx}` anti-pattern in `config-tab.tsx`

The two-component `alert-banner.tsx` finding is low risk and confirmed as a minor concern only.

**8. Import Hygiene** — Confirmed: 1
- `import { h } from "preact"` in `unified-handler-row.test.tsx` — h IS used (see §5 correction above), so this is a **FALSE POSITIVE**

**9. Hard-Coded Environment Values** — Confirmed: 1
- `navigator.platform` (deprecated) in `sidebar.tsx:17` with hard-coded UA substrings

**10. Formatting Inconsistencies** — Confirmed: 3
- `@media` qualifier inconsistency (duplicates §4)
- `outline-offset: 2px` vs `var(--sp-0)` (same runtime value, source inconsistency)
- `line-height: 1.5` on code/mono blocks in two files — no shared token

---

### Summary — frontend-components.md

| Category | Nitpicker count | False Positives | Confirmed |
|---|---|---|---|
| Magic Numbers | ~30 sub-findings | 6 (em values in badge/button; `outline-offset`=2px runtime equivalence) | ~15 |
| Scattered Constants | 6 | 1 (STORAGE_VERSION note) | 4 real duplications |
| Ternary Abuse | 5 | 0 | 4 confirmed, 1 low |
| CSS Styling Sins | 8 | 1 (10px as "token bypass" framing) | 6 |
| Dead Code | 5 | 2 (`h` import in test; traceback CSS framed as dead) | 3 |
| Naming | 4 | 0 | 4 |
| Structural | 6 | 0 | 5 |
| Import Hygiene | 1 | 1 (`h` is used) | 0 |
| Env Values | 2 | 0 | 1 (platform) |
| Formatting | 3 | 0 | 3 |

---

## frontend-pages-hooks.md

### False Positives

#### `use-telemetry-health.test.ts` — `30_000` / `60_000` bare literals — FALSE POSITIVE

The nitpicker claims tests should reference `BASE_INTERVAL_MS` from the module under test. However, `BASE_INTERVAL_MS` is **not exported** from `use-telemetry-health.ts` (it is a `const`, no `export`). Tests cannot reference it. The finding would require either exporting the constant (an API surface change) or accepting the literals. The duplication observation is valid, but the suggested fix is impossible without a code change to the implementation. Reclassify as: **valid concern, fix requires exporting `BASE_INTERVAL_MS`**.

#### `use-scoped-api.ts:29` — `3600`, `86400`, `604800` duplicate `SECONDS_PER_` constants — FALSE POSITIVE

`SECONDS_PER_HOUR` and `SECONDS_PER_DAY` in `utils/format.ts` are **not exported** (bare `const`, no `export` keyword). `use-scoped-api.ts` cannot import them. The values in `PRESET_WINDOW_SECONDS` are semantically different anyway — they express preset window sizes in seconds, not generic time conversion factors. This is not a real duplication.

#### `use-websocket.test.ts:9` — `static OPEN = 1` unused — FALSE POSITIVE

`MockWebSocket` has `static OPEN = 1` and sets `readyState = 1` directly. The nitpicker says the constant is unused. However, `static OPEN = 1` on a WebSocket mock is implementing the WebSocket interface (`WebSocket.OPEN === 1`), not just a local constant — it's the standard mock pattern for satisfying WebSocket type checks. The `readyState = 1` literal in `close()` is a separate issue (should use `MockWebSocket.OPEN`) but the constant itself is not dead.

#### `handlers.tsx:141` — `buildEmptyTitle` naming — DISPUTED

The nitpicker says `build*` implies construction while `get*` or a noun would be better. `buildEmptyTitle` constructs a string conditionally — `build*` is an established TypeScript/JS convention for functions that assemble a value. This is a matter of taste, not a clear violation.

#### `apps.tsx:10` — `{ type StatusKind }` inline vs `import type { StatusKind }` — FALSE POSITIVE

Both forms are valid TypeScript. The file is internally consistent (lines 10, 13, 22 all use inline `{ type X }`). Cross-file style variation is a minor concern but not a violation when the file is internally consistent.

#### `diagnostics.tsx` section dividers — MISCATEGORIZED, NOT DEAD CODE

The nitpicker places these under "Dead Code." Section divider comments are not dead code — they're a coding-style violation (per `coding-style.md`). The finding is **confirmed**, but belongs under Formatting/Style, not Dead Code. Six instances in `diagnostics.tsx`.

---

### Confirmed Findings — frontend-pages-hooks.md

**1. Magic Numbers and Strings** — Confirmed: 9
- `use-filtered-signal-refetch.test.ts` — bare `500` and `1500` literals passed to the hook throughout, while `WS_DEBOUNCE_DELAY_MS` and `WS_DEBOUNCE_MAX_WAIT_MS` are **exported** from the module under test and available to use
- `use-telemetry-health.test.ts` — inline default-response object `{ degraded: false, dropped_*: 0 }` duplicated 6 times; extract a factory
- `apps.tsx:249` — 6 inline `col` width percentages with no comment explaining the layout
- `handlers.tsx:171-180` — 10 inline `col` width percentages
- `config.tsx:120` — `"—"` em-dash sentinel compared inline; should be a named constant (used in both `formatValue` and the render branch in the same file)
- `apps.module.css:113` — `200px` max-width on `.errorCell`
- `app-detail.module.css:59` — `280px` minmax floor
- `logs.module.css:26` — `outline-offset: 2px` vs `var(--sp-0)` (confirmed source inconsistency)
- `diagnostics.module.css:35` — `1px` padding while rest of file uses spacing tokens

**2. Scattered Constants** — Confirmed: 3
- `use-document-title.ts:8` — bare `"Hassette"` in cleanup vs the `SUFFIX` constant on line 3; should derive from a base brand constant
- `create-app-state.ts:248` — `RELATIVE_TIME_TICK_MS` defined at the bottom of the file, separated from other constants at the top
- `_updateLogSubscription` underscore prefix in `create-app-state.ts:73` — per project style, no underscore prefixes; rename to `updateLogSubscription`

**3. Ternary Abuse** — Confirmed: 2
- `apps.tsx:167-169` — nested ternary inside a long-condition ternary; extract both
- `apps.tsx:139-140` — 75-character condition ternary; extract to guard/helper

The `app-detail.tsx:109-110` four-`??` chain and `config.tsx:120` ternary are on the borderline — confirmed as low priority.

**4. CSS and Styling Sins** — Confirmed: 5
- `apps.module.css:163` and `app-detail.module.css:210` — `900px` breakpoint with no named constant anywhere in the codebase (not in `use-media-query.ts`); this is a genuine orphan breakpoint
- Within-file `@media` inconsistency in `apps.module.css` (900px uses `screen and`, 768px doesn't) and `app-detail.module.css` (same pattern)
- `app-detail.module.css:204-215` — `.tabBtn` styles duplicated verbatim across the 900px and 768px breakpoints
- `handlers.module.css:73` — `@media (max-width: 768px)` missing `screen and` (cross-file inconsistency)

**5. Dead Code** — Confirmed: 2 (after recategorizing the section dividers)
- `use-api.test.ts` — `await new Promise((r) => setTimeout(r, 50))` boilerplate repeated 10 times; extract to `const tick = () => new Promise<void>((r) => setTimeout(r, 50))`
- `use-websocket.test.ts:27` — `this.readyState = 3` uses bare literal instead of a named constant; `static OPEN = 1` was defined exactly for this purpose; a corresponding `static CLOSED = 3` and `static RECONNECTING = ...` would complete the mock

Section divider comments in `diagnostics.tsx` — 6 instances, confirmed coding-style violation (recategorized from Dead Code).

**6. Naming Inconsistencies** — Confirmed: 4
- `diagnostics.tsx:348` — asymmetric destructuring renames (`data: systemStatus` renamed, `loading` not, `error: loadError` renamed)
- `handlers.tsx:87` — `function onSort()` declaration while all other handlers are arrow constants
- `use-api.ts:67` — `refetch` is a ref but named without the `Ref` suffix, while `requestIdRef`, `hasFetchedRef`, `lazyRef`, `enabledRef` all have the suffix
- `handlers-rows.tsx` — `avgDur` abbreviation mixed with full words in the same return object

**7. Structural Messiness** — Confirmed: 4
- `diagnostics.tsx` — 391 lines, 6 component definitions; should be split (borderline on line count, clear on responsibility count)
- `use-websocket.ts:59-147` — 90-line `switch` in `onmessage`; `case "connected"` alone is 35 lines with multiple operations; extract to a named function
- `apps-table-row.tsx:42` — 160-character single JSX line
- `use-api.ts:98-114` — render-phase signal writes with necessary but surprising pattern; the 17-line conditional block during render warrants a comment explaining why (one exists, but the pattern itself is unusual)

**8. Import Hygiene** — Confirmed: 2
- `diagnostics.tsx:8-9` — two separate imports from `"../api/endpoints"` should be merged
- `diagnostics.tsx:10` — `import type { components } from "../api/generated-types"` bypasses the convention of re-exporting generated types through `endpoints.ts`

The `h` imports in `use-api.test.ts`, `use-relative-time.test.ts`, and `use-scoped-api.test.ts` are all **NOT false positives** — `h` is genuinely used in each file's `createWrapper` helper (`h(AppStateContext.Provider, ...)`). These are confirmed valid imports, so the nitpicker's suggestion to replace with JSX syntax is a style preference (valid) but the imports are not stale.

**9. Hard-Coded Environment Values** — Confirmed: 1
- `use-websocket.ts:38` — `/api/ws` path constructed inline while `api/client.ts` has `BASE_URL = "/api"`; the WebSocket path duplicates the `/api` prefix with no shared constant

**10. Formatting Inconsistencies** — Confirmed: 3
- `apps.module.css` and `app-detail.module.css` within-file `@media` syntax inconsistency (duplicates §4)
- `use-api.ts:67-88` — `useRef(async () => { ... }).current` with closing `}).current` visually disconnected from opening on line 67
- `use-telemetry-health.test.ts` — long inline mock objects (~130 chars) without line breaks (consistent pattern, could use a factory)

---

### Summary — frontend-pages-hooks.md

| Category | Nitpicker count | False Positives | Confirmed |
|---|---|---|---|
| Magic Numbers | 16 | 2 (SECONDS_PER_ unexported; BASE_INTERVAL_MS unexported) | 9 (with caveats) |
| Scattered Constants | 5 | 0 | 3 |
| Ternary Abuse | 5 | 1 (buildEmptyTitle naming is taste) | 2 confirmed, 2 low |
| CSS Styling Sins | 10 | 0 | 5 |
| Dead Code | 5 | 1 (section dividers miscategorized) | 2 + recategorized |
| Naming | 7 | 1 (inline type import style) | 4 |
| Structural | 7 | 0 | 4 |
| Import Hygiene | 6 | 3 (h imports are used) | 2 |
| Env Values | 2 | 0 | 1 |
| Formatting | 6 | 0 | 3 |

---

## Cross-Report Summary

| Report | Total nitpicker findings | False Positives | Confirmed |
|---|---|---|---|
| frontend-components.md | ~70 sub-items | ~11 | ~46 |
| frontend-pages-hooks.md | 69 | ~8 | ~35 |
| **Combined** | **~139** | **~19 (14%)** | **~81 (58%)** |

(Remaining ~27 are borderline/taste/low-priority that are technically valid but not worth fixing immediately.)

### Highest-confidence false positives to discard

1. **`em` padding values in `badge.module.css` and `button.module.css`** — idiomatic proportional sizing, not magic numbers
2. **`detail-panel.module.css` traceback classes as "dead code"** — actively used by `traceback-viewer.tsx`
3. **`configTableColType {}` / `configTableColValue {}` as "dead code"** — used in TSX; `ColType` has media-query override
4. **`h` import as stale in test files** — used in `createWrapper` helpers in all three cited test files
5. **`SECONDS_PER_` constants as available for `use-scoped-api.ts`** — not exported; cannot be referenced
6. **`BASE_INTERVAL_MS` available for test use** — not exported; tests cannot reference it
7. **`static OPEN = 1` on MockWebSocket as dead** — implements WebSocket interface contract

### Highest-impact confirmed findings to fix first

1. **`WS_DEBOUNCE_DELAY_MS`/`WS_DEBOUNCE_MAX_WAIT_MS` not used in tests** — exported, available, just not imported (easy fix)
2. **Inline `{ degraded: false, dropped_*: 0 }` duplicated 6× in `use-telemetry-health.test.ts`** — extract factory
3. **11 dead CSS classes in `config-tab.module.css`** — straightforward deletion
4. **`STATUS_DOT_SIZE = 10` defined twice** — move to shared constants file
5. **`transition: all` in `log-detail-drawer.module.css:78`** — narrow to specific properties
6. **`!important` without comment in `config-tab.module.css:148-149`** — add comment
7. **Orphan breakpoint `900px`** — not registered anywhere; needs a named constant or documentation
8. **Cross-component style imports** (traceback-viewer → detail-panel, handler-health-grid → overview-tab) — structural fix
