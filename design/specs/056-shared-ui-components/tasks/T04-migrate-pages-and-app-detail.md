---
task_id: "T04"
title: "Migrate pages and app-detail components to shared components"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#13", "FR#14"]
---

## Summary
Migrate all page-level and app-detail TSX files to use the Button, Badge, Chip, and Card components instead of raw `ht-*` class strings. This covers 16 consumer files. Also restyle the not-found.tsx link as a standard link. Update `apps.module.css` to target `[data-variant="muted"]` instead of `:global(.ht-chip--auto)`. The three `<section>` elements in diagnostics.tsx retain raw card classes per AC#1 exemption.

## Prompt
Migrate the following files. For each file, replace raw `ht-btn`, `ht-badge`, `ht-chip`, and `ht-card` class strings with the corresponding component import and props. Use the existing variant helper functions (`statusToVariant()`, `executionStatusVariant()`) directly as Badge `variant` prop values.

### App detail components (frontend/src/components/app-detail/)

**handlers-tab.tsx** — 3 components to migrate:
- Lines 51-54: `<span class="ht-chip ht-chip--modifier">` → `<Chip variant="modifier">`
- Lines 69-71: `<span class="ht-chip ht-chip--schedule">` → `<Chip variant="schedule">`
- Lines 174-177: `<span class="ht-chip ht-chip--kind ht-chip--kind-${listenerKind}">` → `<Chip variant="kind" kind={listenerKind} aria-label={...}>` with StatusShape as child
- Line 180: `<span class="ht-badge ht-badge--danger ht-badge--sm">` → `<Badge variant="danger" size="sm">`
- Lines 226-234, 362-370: `<button class="ht-btn ht-btn--ghost ht-btn--sm">` → `<Button variant="ghost" size="sm">`
- Lines 297-299: Job kind chip (same as listener kind chip pattern)
- Lines 480-488: Back button `<button class="ht-btn ht-btn--ghost ht-btn--sm ht-mb-3">` → `<Button variant="ghost" size="sm" class="ht-mb-3">` (keep the utility class via `class` prop)

**handler-invocations.tsx** — Line 77: `<span class="ht-chip ht-chip--origin">` → `<Chip variant="origin">`

**job-executions.tsx** — Line 53: `<span class="ht-badge ht-badge--sm ht-badge--${executionStatusVariant(ex.status)}">` → `<Badge variant={executionStatusVariant(ex.status)} size="sm">`. Add `data-testid="execution-status-badge"` so that `job-executions.test.tsx` can be updated in T03.

**unified-handler-row.tsx** — Line 104: `<span class="ht-badge ht-badge--danger ht-badge--xs">` → `<Badge variant="danger" size="xs">`

**overview-tab.tsx** — Line 171: `<span class="ht-chip ht-chip--muted ht-chip--sm">` → `<Chip variant="muted" size="sm">`

**code-tab.tsx**:
- Lines 139: `<div class="... ht-card">` → `<Card data-testid="code-tab-error">`. Remove the `styles.error` padding override class — the default Card padding (`--sp-5`) is close enough (was `--sp-6`; 4px difference accepted).
- Lines 168-176: `<button class="ht-btn ht-btn--ghost ht-btn--sm">` → `<Button variant="ghost" size="sm">`

**config-tab.tsx**:
- Line 186: `<div class="ht-card ...">` → `<Card data-testid="config-tab-error">`. Remove the `styles.configTabError` padding override — same rationale as code-tab.
- Lines 213: Badge with ternary variant → `<Badge variant={cfg.enabled ? "success" : "neutral"}>`
- Lines 223, 252: `<div class="ht-card ht-card--config">` → `<Card variant="config">`

**error-cell.tsx** — Lines 21-29: `<button class="ht-btn ht-btn--xs ht-btn--ghost ...">` → `<Button variant="ghost" size="xs" class={styles.tracebackToggle}>`

### Pages (frontend/src/pages/)

**apps.tsx**:
- Line 144: `<span class="ht-chip ht-chip--auto">` → `<Chip variant="muted">auto</Chip>` (auto merged to muted)
- Line 148: Badge with `statusToVariant()` → `<Badge variant={statusToVariant(status)} size="sm">`
- Line 196: Instance row badge → `<Badge variant={statusToVariant(instStatus)} size="sm">`
- Line 323: Clear filters button → `<Button variant="ghost" size="sm">`

**app-detail.tsx**:
- Line 83: Instance card status badge → `<Badge variant={statusToVariant(instance.status)} size="sm" class={styles.instanceCardStatusBadge}>`
- Line 113: Instance count badge → `<Badge variant="neutral">`
- Line 317: Status badge with StatusShape icon → `<Badge variant={statusToVariant(liveStatus)} size="sm">` with StatusShape as child
- Line 335: Auto chip → `<Chip variant="muted">`
- Line 404: `<div class="ht-card">` → `<Card>`

**not-found.tsx** — Line 10: Remove `ht-btn ht-btn--ghost` from the `<a>` element. Restyle as a standard link. Add a simple link class to `not-found.module.css` (e.g., `.backLink { color: var(--accent); text-decoration: none; } .backLink:hover { text-decoration: underline; }`).

**handlers.tsx** — Line 153: `<span class="ht-chip ht-chip--muted ht-chip--sm">` → `<Chip variant="muted" size="sm">`

**logs.tsx** — Line 16: `<div class="ht-card ht-card--compact ...">` → `<Card variant="compact" class={styles.cardFull}>`

**diagnostics.tsx** — Lines 144, 186, 277: These three `<section class="ht-card ...">` elements are **EXEMPT from migration** per AC#1. Leave them as raw class strings to preserve `<section>` semantic HTML landmarks. Do NOT wrap in `<Card>`.

**config.tsx** — Line 110: `<div class="ht-card ht-card--config">` → `<Card variant="config">`

### CSS updates
- `frontend/src/pages/apps.module.css:199`: Replace `:global(.ht-chip--auto)` with `[data-variant="muted"]`

### Layout component
**sidebar.tsx** — Line 138: `<span class="ht-chip ht-chip--auto">` → `<Chip variant="muted" title="Auto-loaded">`

### Test updates
`frontend/src/components/app-detail/job-executions.test.tsx`: Replace `container.querySelector(".ht-badge--success")` and `.ht-badge--danger` with `data-testid` queries (e.g., `container.querySelector("[data-testid='execution-status-badge']")`). The `data-testid` attribute is added to `job-executions.tsx` in this same task.

## Focus
- `statusToVariant()` and `executionStatusVariant()` return `StatusVariant` which is a subset of Badge's `StatusVariant | "info"` — these pass type-checking directly
- `apps.tsx` line 148 uses template literal for dynamic variant — converts to `variant={statusToVariant(status)}`
- `app-detail.tsx:83` combines module CSS class with badge → use `class` prop
- `app-detail.tsx:317` badge has StatusShape icon child — Badge handles mixed children
- `handlers-tab.tsx` has two identical "view in code" buttons (listener and job) — migrate both
- `handlers-tab.tsx:480` back button has `ht-mb-3` utility class — pass via `class` prop
- `diagnostics.tsx` three `<section>` elements — DO NOT migrate (AC#1 exemption)
- `apps.module.css:199` — the `:global(.ht-chip--auto)` becomes `[data-variant="muted"]`
- `not-found.tsx` — the `<a>` stays as `<a>`, just remove button classes and add simple link styling

## Verify
- [ ] FR#13: All 16 consumer files use Button/Badge/Chip/Card components (except diagnostics.tsx exempted sections)
- [ ] FR#14: not-found.tsx `<a>` element uses standard link styling, not `ht-btn` classes
