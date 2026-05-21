# Nitpick Audit: frontend/src/components/

Scope: all `.ts`, `.tsx`, `.css` files in `frontend/src/components/` (app-detail/, layout/, shared/, shared/log-table/).
Style and organisation only — correctness and security are out of scope.
CSS Modules `:global()` usage and `clsx` are intentional patterns; not flagged.

---

## 1. Magic Numbers and Strings

### Bare pixel/numeric values not using design tokens

**`frontend/src/components/app-detail/app-logs-panel.tsx:34`**
`scrollHeight="calc(100vh - 340px)"` — the `340px` offset is a hard-coded guess at header heights with no token or named constant.

**`frontend/src/components/app-detail/code-tab.tsx:108`**
String `"404"` as a magic status code in `if (err.status === "404" || err.message.includes("not found"))` — should be a named constant or checked against a numeric type.

**`frontend/src/components/app-detail/code-tab.module.css`**
- Line 36: `280px` in `calc()` (magic column width)
- Lines 76 and 82: `3px` box-shadow inset value repeated twice
- Line 89: `3ch` tab-size value
- Line 93: `line-height: 1.6` bare unitless ratio

**`frontend/src/components/app-detail/config-tab.module.css`**
- Lines 107 and 145: `10px` padding value repeated (not a token)
- Line 148: `9px` padding
- Line 190: `width: 320px`
- Line 200: `max-height: 200px`

**`frontend/src/components/app-detail/handler-health-card.module.css`**
- Line 3: `border-top: 2px solid ...` bare `2px`

**`frontend/src/components/app-detail/handlers-tab.module.css`**
- Line 6 (approx): `--master-max-height: 70vh` magic viewport fraction
- Lines with `280px`, `420px` in CSS custom properties — raw pixel values with no token backing

**`frontend/src/components/app-detail/job-detail.tsx:86`**
Inline style `style={{ marginBottom: "var(--sp-3)" }}` — valid token reference but should be a CSS class, not an inline style.

**`frontend/src/components/app-detail/overview-tab.tsx:62`**
`scrollHeight="400px"` duplicates the `--log-scroll-max-height: 400px` value defined in `overview-tab.module.css:15`. These are the same value with no shared source of truth.

**`frontend/src/components/app-detail/overview-tab.module.css`**
- Line 15: `--log-scroll-max-height: 400px` (duplicates overview-tab.tsx)
- Line 71: `max-width: 60ch` bare ch value
- Lines 74–75: `--health-card-min: 140px`, `--health-card-max: 280px` raw pixel values
- Line 85 (approx): `--health-grid-rows: 3` magic number that mirrors `SPOTLIGHT_LIMIT = 3` in `error-spotlight.tsx` with no shared reference

**`frontend/src/components/app-detail/unified-handler-row.module.css`**
- Line 41: `padding-top: 3px`
- Line 71: `font-size: 10px`
- Line 75: `padding: 1px var(--sp-1)` — bare `1px`

**`frontend/src/components/layout/command-palette.module.css`**
- Line 15: `max-height: 15vh`
- Line 17: `width: 620px`, `max-width: 90%`
- Line 19: `max-height: 70vh`
- Line 138: `max-height: 200px`
- Backdrop `blur(2px)` value

**`frontend/src/components/layout/sidebar.module.css`**
- Line 3: `width: 240px` sidebar width with no token
- Lines 151 and 242: `gap: 1px` repeated (same bare value in two rules)

**`frontend/src/components/layout/status-bar.module.css`**
- Animation duration `2.5s` with no token

**`frontend/src/components/shared/badge.module.css`**
Multiple bare `em` values throughout: `0.15em`, `0.55em`, `0.05em`, `0.4em`, `0.1em`, `0.45em`, `0.2em`, `0.65em`. None correspond to design tokens. Also: `font-size: 10px` at line 18.

**`frontend/src/components/shared/button.module.css`**
Multiple bare `em` values: `0.4em`, `0.85em`, `0.25em`, `0.6em`, `0.15em`, `0.45em`.

**`frontend/src/components/shared/chip.module.css`**
- Line 53: `letter-spacing: 0.5px`
- Line 58: `font-size: 10px`
- Line 59: `padding: 1px var(--sp-1)` — bare `1px`

**`frontend/src/components/shared/column-filter-popover/index.tsx:43`**
`offset(4)` and `shift({ padding: 8 })` — bare integer pixel values in the floating-ui middleware configuration. Should be named constants at the top of the file.

**`frontend/src/components/shared/column-filter-popover/index.module.css`**
- Line 9: `min-width: 200px`
- Line 10: `max-width: 280px`
- Line 11: `max-height: 60vh`

**`frontend/src/components/shared/confirm-dialog.module.css`**
- `min-width: 320px`, `max-width: 480px`
- `blur(2px)` backdrop filter

**`frontend/src/components/shared/detail-panel.module.css`**
- Line 11: `font-size: 10px`
- Line 12: `letter-spacing: 0.5px`

**`frontend/src/components/shared/empty-state.module.css`**
- `max-width: 320px`

**`frontend/src/components/shared/execution-logs.module.css`**
- Line 6: `font-size: 10px`
- Line 7: `letter-spacing: 0.5px`

**`frontend/src/components/shared/filter-icon.tsx:31–32`**
Inline SVG dot: `width: "5px"`, `height: "5px"` — bare pixel values in inline style with no token. The `top: 0, right: 0` positioning is also inline style (not in CSS).

**`frontend/src/components/shared/mini-sparkline.tsx`**
- Line 28: `stroke-width="1.5"` inline SVG attribute
- Line 30: `r="2.5"` circle radius

**`frontend/src/components/shared/sort-header.module.css:61`**
`outline-offset: 2px` — bare pixel in focus ring (most other focus rings use `var(--sp-0)`).

**`frontend/src/components/shared/spinner.module.css:4`**
`border: 3px solid ...` — bare pixel value.

**`frontend/src/components/shared/stats-strip.module.css:22`**
`letter-spacing: 0.08em` — bare em value.

**`frontend/src/components/shared/table-footer.module.css`**
- Line 45: `outline-offset: 2px` bare pixel
- Line 54: `min-width: 200px`
- Line 81: `outline-offset: 2px`

**`frontend/src/components/shared/log-table/log-detail-drawer.module.css`**
- Line 25: `.sidePanel { width: 400px }` — must match `--drawer-width: 400px` in `log-table.module.css` (comment says so, but they are separate literals with no shared variable)
- Line 36: `.bottomSheet { max-height: 70vh }`
- Line 73: `.iconBtn { width: 28px; height: 28px }`
- Line 141: `padding-top: 1px` in `.metaGrid dt`
- Line 209: `line-height: 1.5` bare ratio (also in `log-table-row.module.css:72`)
- Line 216: `max-height: 40%`
- Line 222: `border-left: 3px solid var(--err)` — bare `3px`

**`frontend/src/components/shared/log-table/log-table.module.css:3`**
`--drawer-width: 400px` — duplicates the `400px` that also appears in `log-detail-drawer.module.css:25`.

**`frontend/src/components/shared/log-table/use-column-visibility.ts:8`**
`STORAGE_VERSION = 1` — fine as a named constant, but worth noting for migration awareness.

---

## 2. Scattered Constants / Missing Named Constants

**Duplicate `STATUS_DOT_SIZE = 10` constant**
Both `frontend/src/components/app-detail/execution-table.tsx:13` and `frontend/src/components/app-detail/handler-health-card.tsx:31` define `STATUS_DOT_SIZE = 10` independently. These should be in one shared location.

**Bare `50` fetch limit repeated**
`frontend/src/components/app-detail/listener-detail.tsx:60` and `frontend/src/components/app-detail/job-detail.tsx:50` both pass the literal `50` as the fetch limit with no named constant. The log-table subdirectory already uses `REST_FETCH_LIMIT` for this pattern — a similar constant should cover the handler/job detail limit.

**Magic `2` and `8` in ID generation**
`frontend/src/components/shared/confirm-dialog.tsx`: `Math.random().toString(36).slice(2, 8)` — the slice indices `2` and `8` are unexplained.

**`"404"` status string in code-tab**
`frontend/src/components/app-detail/code-tab.tsx:108` — the string `"404"` and substring `"not found"` used to detect missing-file errors should be a named constant or a dedicated error-type check.

**`overview-tab.tsx:62` and `overview-tab.module.css:15` both say `400px`**
No shared source of truth; one or the other will drift.

**`log-detail-drawer.module.css:25` and `log-table.module.css:3` both say `400px`**
The comment on line 19 of `log-table.module.css` ("width must match `--drawer-width`") acknowledges the coupling, but the value is still duplicated with no shared variable.

**`SPOTLIGHT_LIMIT = 3` in `error-spotlight.tsx` and `--health-grid-rows: 3` in `overview-tab.module.css`**
Mirrors the same concept; if `SPOTLIGHT_LIMIT` changes, the CSS grid row count silently diverges.

---

## 3. Ternary Abuse / Complex Conditionals

**`frontend/src/components/app-detail/config-tab.tsx`**
Nested 2-level ternary in JSX (renders different cell content based on `isRedacted` then `isEmpty`). Extracting a helper function `renderConfigValue(field)` would eliminate the nesting.

**`frontend/src/components/app-detail/handler-list.tsx:45`**
`humanDescription` is built from a multi-branch ternary spanning the whole line. A small `buildDescription(item)` helper would be cleaner.

**`frontend/src/components/app-detail/job-detail.tsx:82`**
Inline ternary for `subtitle` prop that references multiple fields across two branches.

**`frontend/src/components/app-detail/recent-activity-section.tsx:122–126`**
Chained ternary (3 levels) in the JSX return to pick between empty-state, loading-state, and the activity list. An early return or a helper would make intent clearer.

**`frontend/src/components/app-detail/unified-handler-row.tsx:89–93`**
Two-level ternary for `subline` building across 5 lines in JSX.

---

## 4. CSS / Styling Sins

### `font-size: 10px` not using a token — repeated pattern

The bare `10px` font-size appears in at least six separate module CSS files rather than referencing `var(--fs-micro)` or a dedicated micro-label token:
- `frontend/src/components/shared/badge.module.css:18`
- `frontend/src/components/shared/chip.module.css:58`
- `frontend/src/components/shared/detail-panel.module.css:11`
- `frontend/src/components/shared/execution-logs.module.css:6`
- `frontend/src/components/app-detail/unified-handler-row.module.css:71`
- `frontend/src/components/app-detail/config-tab.module.css:148`

If the design token for micro text size exists but isn't being used here, these are token bypasses. If the value truly lacks a token, it should be added.

### `letter-spacing: 0.5px` repeated pattern

`detail-panel.module.css:12`, `execution-logs.module.css:7`, and `chip.module.css:53` all hardcode `letter-spacing: 0.5px`. Should be a shared token or utility class.

### `!important` without comment

**`frontend/src/components/app-detail/config-tab.module.css:148–149`**
Two `!important` declarations with no comment explaining why specificity override is needed. Other uses of `!important` in the codebase include a comment.

### Inconsistent `@media` query syntax

Some files include `screen and`, others do not:

With `screen and`:
- `handlers-tab.module.css`
- `sidebar.module.css` (one of its two breakpoints)
- `stats-strip.module.css`
- `button.module.css`
- `time-preset-selector.module.css`
- `log-table.module.css`

Without `screen and`:
- `command-palette.module.css`
- `sidebar.module.css` (its other breakpoint)

The inconsistency is cosmetic but signals different authors or copy-paste. All modern `@media` queries work fine without `screen and` — pick one style and apply it uniformly.

### Magic breakpoint values scattered across CSS

The breakpoints `768px`, `900px`, and `1024px` are hardcoded in individual CSS files. `768px` corresponds to `BREAKPOINT_MOBILE` in `use-media-query.ts`; `900px` is an unnamed breakpoint; `1024px` is `BREAKPOINT_TABLET`. CSS has no import mechanism for these values, but the pattern currently used (a `/* sync: BREAKPOINT_MOBILE */` comment in `handlers-tab.module.css`) should be applied everywhere these appear:

Files missing the sync comment for `768px`:
- `config-tab.module.css`
- `stats-strip.module.css`
- `sidebar.module.css`

Files missing the sync comment for `900px`:
- `sidebar.module.css`
- `button.module.css`
- `time-preset-selector.module.css`

### Duplicate border declarations in `card.module.css`

**`frontend/src/components/shared/card.module.css`**
Both `.card` and `.error` contain the identical two-line block:
```css
border: 1px solid var(--line-1);
border-top: 1px solid var(--line-2);
```
The `border-top` overrides the shorthand. The `.error` variant duplicates both lines verbatim (lines 27–28 duplicate lines 5–6). If this is intentional design, extracting the pair into a shared rule or custom property would eliminate the duplication.

### Empty CSS rule blocks

**`frontend/src/components/app-detail/execution-table.module.css:9`**
`.statusCell {}` — empty rule block is dead weight.

**`frontend/src/components/app-detail/config-tab.module.css`**
`.configTableColType {}` and `.configTableColValue {}` are both empty rule blocks.

### Inline styles that should be CSS classes

**`frontend/src/components/app-detail/job-detail.tsx:86`**
`style={{ marginBottom: "var(--sp-3)" }}` — the token reference is correct, but inline styles bypass the module CSS. It should be a `.wrapper` or similar class in the co-located CSS file.

**`frontend/src/components/shared/filter-icon.tsx:8–35`**
The outer `<span>` uses an inline style for `position: relative; display: inline-flex; alignItems: center`. The active-state dot uses a full inline style block with 6 properties including `width: "5px"`, `height: "5px"`. This is a case that warrants a small CSS module file.

**`frontend/src/components/shared/table-card.tsx:33–37`**
The search bar slot uses an inline style object for `display`, `justifyContent`, `padding`, and `borderBottom`. These should be CSS classes.

---

## 5. Dead Code

### Dead CSS classes in `config-tab.module.css`

A large block of field-by-field layout classes that are not referenced in `config-tab.tsx` or any other file in the repo:
`.divider`, `.colAction`, `.redacted`, `.empty`, `.configFields`, `.configField`, `.configFieldHeader`, `.configFieldName`, `.configFieldType`, `.configFieldRequired`, `.configFieldValue`, `.configFieldValueMissing`, `.configFieldNote`

These appear to be leftovers from a previous table layout that was replaced. Total: ~14 dead class definitions.

### Dead CSS classes in `detail-panel.module.css`

`frontend/src/components/shared/detail-panel.module.css` defines:
- `.tracebackSection`
- `.errorLine`
- `.errorLine pre`
- `.tracebackFrames`

These classes are not used in `detail-panel.tsx`; they are used in `traceback-viewer.tsx`, which imports from `detail-panel.module.css` (`import styles from "./detail-panel.module.css"`). This is cross-component style sharing — not technically dead, but structurally wrong: `traceback-viewer.tsx` reaches into another component's module CSS. The classes should live in `traceback-viewer.module.css`.

### Unused import in `unified-handler-row.test.tsx`

**`frontend/src/components/app-detail/unified-handler-row.test.tsx:4`**
`import { h } from "preact"` — `h` is not referenced anywhere in the test file. This is a stale import.

### `sectionLabel.withRule::after` dead CSS

**`frontend/src/components/shared/log-table/log-detail-drawer.module.css:194`**
`.sectionLabel.withRule::after` — the compound selector requires both `sectionLabel` and `withRule` classes applied together, but no element in `log-detail-drawer.tsx` applies the `withRule` class. The rule is unreachable.

---

## 6. Naming Inconsistencies

### Single-letter variable names `l` and `j`

**`frontend/src/components/app-detail/handler-list.tsx`**
- Line 32: `const l` for a listener object
- Line 41: `const j` for a job object

**`frontend/src/components/app-detail/unified-handler-row.tsx`**
- Similar `const l`, `const j` abbreviations in map callbacks

These are the same concept as `listener` and `job`; the full names are not long enough to justify truncation.

### `isFailing` name collision

**`frontend/src/components/app-detail/unified-handler-row.tsx`**
A `let isFailing: boolean` local variable is declared while `isFailing` is also an exported function from `overview-tab-helpers.ts` that is imported in scope. Different concepts (boolean result vs. the function itself), but the same identifier in the same file creates confusion.

### `failed` / `failing` in `handler-health-card.tsx`

`const failed = item.data.failed` (the raw count) and `const failing = isFailing(item)` (the predicate result) sit next to each other. The pair reads ambiguously — `failed` looks like it could be the predicate result at a glance.

### `config-tab.tsx` duplicate `data-testid`

**`frontend/src/components/app-detail/config-tab.tsx`**
Two separate `<table>` elements share `data-testid="config-values-table"`. Test selectors must be unique to be useful; a test that queries by this ID will match whichever element appears first.

---

## 7. Structural Messiness

### Two-component files

**`frontend/src/components/layout/alert-banner.tsx`**
`AlertBanner` and `TelemetryDegradedBanner` are both defined in the same file. `TelemetryDegradedBanner` is a distinct semantic component and could live in its own file for discoverability, though the current grouping is low risk.

### Cross-component style imports

Two places where a component reaches into another component's module CSS:

1. **`frontend/src/components/shared/traceback-viewer.tsx:1`**
   `import styles from "./detail-panel.module.css"` — uses classes `.tracebackSection`, `.errorLine`, `.tracebackFrames` that logically belong to `traceback-viewer`. These classes should be moved to a `traceback-viewer.module.css`.

2. **`frontend/src/components/app-detail/handler-health-grid.tsx`**
   Imports from `overview-tab.module.css` (noted in a comment). The cross-file import couples the two components; the relevant classes should be either extracted to a shared file or duplicated with the correct module.

### Test file line count

Two test files exceed the 400-line guideline:
- **`frontend/src/components/app-detail/overview-tab.test.tsx`**: 559 lines
- **`frontend/src/components/app-detail/handlers-tab.test.tsx`**: 508 lines

Both could be split into multiple focused test files (e.g., by tab section or functional area).

### Duplicate test cases in `unified-handler-row.test.tsx`

**`frontend/src/components/app-detail/unified-handler-row.test.tsx:145–167`**
Lines 145–155 and 157–167 are structurally identical: both test click navigation using `fireEvent.click` with the same assertions. If they are testing the same code path, one can be removed. If they are testing different scenarios, they should be named differently and given distinct setup.

### Bare `key={idx}` anti-pattern

**`frontend/src/components/app-detail/config-tab.tsx`**
`key={idx}` used in at least one `map()` call — using array index as key is fragile when the list can reorder. A stable field from the config entry would be better.

### Section divider comments

**`frontend/src/components/app-detail/handler-health-card.test.tsx`** and **`frontend/src/components/layout/alert-banner.module.css`**
Use `// ─────────────────` or similar decorated comment blocks to separate sections. Per the project coding style, these section dividers are a pattern to avoid.

---

## 8. Import Hygiene

**`frontend/src/components/app-detail/unified-handler-row.test.tsx:4`**
`import { h } from "preact"` — unused. The `h` JSX factory is not referenced in this test file; it is a stale import left over from before the JSX transform was configured.

No other unused imports were identified during this audit. The codebase generally imports only what is used.

---

## 9. Hard-Coded Environment / Configuration Values

**`frontend/src/components/layout/palette-items.ts`**
`const DOCS_URL = "https://hassette.readthedocs.io"` — a hard-coded absolute URL for the documentation site. If the docs URL changes (e.g., custom domain, versioned URL), this requires a code change. Consider moving it to a config constant in a shared location (e.g., `frontend/src/config.ts`) alongside any other environment-specific values.

**`frontend/src/components/layout/sidebar.tsx:17`**
```ts
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform);
```
`navigator.platform` is deprecated in favour of `navigator.userAgentData.platform`. The string literals `"Mac"`, `"iPhone"`, `"iPad"` are hard-coded UA substrings. If this check is used for keyboard shortcut display (⌘ vs Ctrl), a dedicated utility function in `utils/` would be more appropriate than inline UA sniffing in a layout component.

---

## 10. Formatting Inconsistencies

### `@media` qualifier inconsistency

As noted in section 4: some files use `@media screen and (max-width: …)`, others use `@media (max-width: …)`. Pick one. The bare form is the modern standard.

### `outline-offset` inconsistency

Most focus-visible rules use `outline-offset: var(--sp-0)`. However:
- `sort-header.module.css:61`: `outline-offset: 2px`
- `table-footer.module.css:45, 81`: `outline-offset: 2px`
- `log-detail-drawer.module.css:82`: `outline-offset: 2px`
- `column-filter-popover/index.module.css` (implied by pattern)

The token `var(--sp-0)` and the literal `2px` may be equal at runtime, but using both forms breaks visual consistency in the CSS source.

### Letter-spacing values

Multiple files use bare `letter-spacing` values (`0.5px`, `0.08em`, `0.03em`) without a token. The `0.03em` value appears identically in at least three files (`log-detail-drawer.module.css`, `table-footer.module.css`, `column-filter-popover/index.module.css`). A `--ls-caps` or `--ls-label` token would unify these.

### `line-height: 1.5` repeated

`log-table-row.module.css:72` and `log-detail-drawer.module.css:209` both set `line-height: 1.5` on code/mono blocks. Should reference `var(--lh-small)` or a shared token if one exists for this value.

### `transition: all var(--t-fast)` anti-pattern

**`frontend/src/components/shared/log-table/log-detail-drawer.module.css:78`**
`.iconBtn { transition: all var(--t-fast) }` — `transition: all` is a known performance anti-pattern that animates properties that should not be animated (e.g., `width`, `height`, `display`). All other transition declarations in the codebase correctly target specific properties (e.g., `color var(--t-fast)`, `background var(--t-fast)`). This one instance should be narrowed.
