# WP03: Missing CSS classes + inline style extraction

**Lane:** todo
**Depends on:** WP02 (chevron button resets reference `.ht-item-row__chevron-inline`)

## Objective

Define missing utility classes and extract inline styles to CSS, using design tokens throughout.

## Tasks

### 1. Define missing utility classes

In `global.css`:

```css
/* After .ht-text-success (line ~688) */
.ht-text-warning { color: var(--ht-warning); }

/* After .ht-tag--job (line ~1286) */
.ht-tag--neutral {
  color: var(--ht-text-secondary);
  background: var(--ht-surface-recessed);
}

/* New utility for truncated tags */
.ht-tag--truncated {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
}
```

### 2. Extract inline styles

| Component | Inline style | CSS target |
|-----------|-------------|-----------|
| `manifest-row.tsx:24` | `cursor: pointer; marginRight: 4px` | Extend `.ht-item-row__chevron-inline` (cursor from `<button>`, add `margin-right: var(--ht-sp-1)`) |
| `manifest-row.tsx:45` | `marginLeft: 4px` | `.ht-badge.ht-badge--sm + .ht-badge { margin-left: var(--ht-sp-1); }` or utility |
| `manifest-row.tsx:61` | `paddingLeft: 2rem` | **Update existing rule** at `global.css:732`: change `.ht-instance-row td:first-child` from `var(--ht-sp-6)` to `var(--ht-sp-8)` (24px→32px to match inline 2rem). Do NOT create a duplicate rule |
| `error-feed.tsx:50` | `max-width:140px;overflow:hidden;...` | Use `.ht-tag--truncated` class alongside `.ht-tag` |
| `log-table.tsx:205` | `maxHeight: 600px; overflow: auto` | **Extend existing rule** at `global.css:1335`: add `max-height: var(--ht-log-scroll-height, 600px);` and update `overflow-y: auto` to `overflow: auto` (shorthand, both axes — matches inline style behavior). Do NOT create a duplicate rule |
| `log-table.tsx:207` | `position: sticky; top: 0; background: ...` | `.ht-table-log thead { position: sticky; top: 0; background: var(--ht-surface-sticky, var(--ht-bg)); /* --ht-surface-sticky must remain opaque */ }` |
| `log-table.tsx:209,214,220,226` | `width: 90/180/170/140px` | `.ht-col-level { width: 90px; }` etc. in `.ht-table-log` scope. Note: column widths and `.ht-tag--truncated` max-width are intentional raw-px exceptions — these are content-sizing constraints, not spacing values |
| `log-table.tsx:263` (Source cell) | Text overflows into Message column | **Bug fix:** Add `overflow: hidden; text-overflow: ellipsis;` to `.ht-col-source`. The cell already has `white-space: nowrap` via `.ht-text-mono` and `width: 140px` from `table-layout: fixed`, but no truncation — long `func_name:lineno` values bleed into the Message column. The existing `title` attribute on the `<td>` already provides the full text on hover |
| `log-table.tsx:237` | `textAlign: center` | Use existing `.ht-text-center` utility |
| `app-detail.tsx:80` | `display: inline-block` | `.ht-select--inline { display: inline-block; }` |
| `sidebar.tsx:32` | `height: 24px; width: auto` | `.ht-sidebar__logo { height: var(--ht-sp-6); width: auto; }` |
| `not-found.tsx:3` | `textAlign: center; padding: var(--ht-sp-10)` | `.ht-error-page { text-align: center; padding: var(--ht-sp-10); }` |
| `error-boundary.tsx:18` | `padding: var(--ht-sp-6); textAlign: center` | `.ht-error-card { padding: var(--ht-sp-6); text-align: center; }` |

### 3. Note: health-bar width stays inline

`health-bar.tsx:16` — `style={{ width: \`${successRate}%\` }}` is a dynamic value and cannot be a CSS class.

## Files

- `frontend/src/global.css`
- `frontend/src/components/apps/manifest-row.tsx`
- `frontend/src/components/dashboard/error-feed.tsx`
- `frontend/src/components/shared/log-table.tsx`
- `frontend/src/pages/app-detail.tsx`
- `frontend/src/components/layout/sidebar.tsx`
- `frontend/src/pages/not-found.tsx`
- `frontend/src/components/layout/error-boundary.tsx`

## Verification

- Visual comparison before/after on every affected page
- Verify `.ht-text-warning` renders in warning color on log-table live-paused indicator
- Verify `.ht-tag--neutral` renders with secondary text color on error-feed unknown kinds
- Verify log table sticky header still works (scroll content behind opaque header)
- Verify column widths unchanged after extraction
- Run unit tests
