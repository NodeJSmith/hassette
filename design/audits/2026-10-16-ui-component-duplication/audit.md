# UI component duplication inventory (2026-10-16)

Snapshot of places where the frontend implements one UI concept several different ways, taken before the next redesign attempt. Each concept is classified:

- **Unify now** — a primitive any visual direction needs. Collapsing it to one implementation makes the later reskin a token/primitive edit instead of a hunt.
- **Wait for wireframe** — a page-level composite on Apps / App Detail whose shape the question→action map and wireframes will decide. Consolidating it now is likely wasted.

Line numbers are from before the Button work in item 2 and drift as files change; paths are relative to `frontend/src/`. Test files excluded.

## Unify now

### 1. Status color (cleanup only — values are already single-sourced)

On closer inspection the tone values live in one place: `--status-*` and `--destructive*` are aliases of the base `--ok`/`--warn`/`--err`/`--cancel`/`--mute` tokens in `global.css`, and no component hard-codes a color literal. A reskin already changes every status color in one place. What remains is reader-load cleanup with no reskin payoff:

- Components mix base names and alias names (`--status-warning` vs `--warn`, `--destructive` vs `--err`) for the same tone.
- About 35 inline color classes bypass `STATUS_TONE_CLASSES`: `text-destructive` ×16 (e.g. `apps-table-row.tsx:154`, `handlers-rows.tsx:107`, `unified-handler-row.tsx:127`), `text-[var(--status-warning)]` ×12, `text-[var(--status-cancel)]` ×2.
- Hand-written status→color maps outside `utils/status.ts`: `sidebar.tsx:158`, the per-count map in `handlers-rows.tsx`, `system-health.tsx:12` (dots instead of `StatusShape`), `log-table/constants.ts:33` (log levels — arguably its own domain).
- `StatusShape` size comes from ~7 per-file constants.

Target: one naming family at call sites, every status→tone decision in `utils/status.ts` (or `StatusShape`), a small set of named shape sizes.

### 2. Buttons — done in this branch

32 raw `<button>`s rolled their own chrome: ~9 icon-button sizes, ~8 one-off text-button styles, and a bare-button reset (#2167) with no shared home. 21 of them now use `Button`, which gained `subtle` (bordered neutral), `link-muted` (secondary text action), an `inline` size and a `touch` option; `ghost` became the neutral borderless control. The remaining 11 raw `<button>`s are the structural surfaces listed in `design/context.md` → Buttons — the tab/pill groups among them are item 3.

### 3. Toggle groups, pills, tabs

Five implementations, no `Tabs`/`ToggleGroup` primitive, inconsistent ARIA (`role="tab"`+`aria-selected` vs `aria-pressed`) and accent tokens (`--accent-soft` vs `--primary-bg`).

- Filter pills: `apps.tsx:172` and `use-log-table.tsx:192` — verbatim duplicate class string.
- Segmented: `time-preset-selector.tsx:81`.
- Tabs: `app-detail.tsx:73` (Link tabs with custom roving keys), `multi-instance.tsx:36` (button tabs, no roving).

Target: `ToggleGroup` and `Tabs` primitives. App Detail tabs (#764, mobile overflow) will be re-laid out by the wireframe, but on the shared primitive.

### 4. Disclosure (expand/collapse)

Seven hand-rolled toggles in three styles, no `<details>` and no shared primitive. Two of them are the same "show traceback/stack" idea with different styling (`error-banner.tsx` `link-muted` in the banner tone vs `stack-frames.tsx` `link`). Others: `config-schema-view.tsx:255/412`, `service-row.tsx:69`, `sidebar.tsx:143`, `apps-table-row.tsx:74`, `registration-footer.tsx:78`. Three different chevrons (`SidebarChevron`, `IconChevron`, glyph).

Target: one `Disclosure` with one chevron and one label convention.

### 5. Text links

`AppLink` is used in 6 places; ~8 router `Link`s carry their own text-link class (`not-found.tsx:15`, `error-spotlight.tsx:42`, `breadcrumbs.tsx:62`, `execution-id-link.tsx:19`, `blocking-findings.tsx:93`, `log-detail-drawer.tsx:250`, `apps-table-row.tsx:25`, `execution-logs.tsx:39` unstyled).

Target: one link style (AppLink stays mono for app keys; a plain text-link variant for the rest).

### 6. Headings and labels

About 12 heading styles for three roles.

- **Page title**: `PAGE_HEADER_CLASS`/`PAGE_TITLE_CLASS` copy-pasted in `apps.tsx:89`, `handlers.tsx:39`, `logs.tsx:14`, `config.tsx:12`; inline copy in `diagnostics.tsx:124` (different border token, no mobile padding); `full-page-card.ts`; bare h1s in `not-found.tsx`, `design.tsx`. Three h1 sizes in use.
- **Section label**: `SECTION_LABEL_CLASS` (5 uses) vs `execution-section.tsx:32`, `execution-detail.tsx:146`, `config-tab.tsx:139`, `CONFIG_SECTION_TITLE_CLASS`, `PANEL_HEADING_CLASS`, `registration-footer.tsx:46`.
- **Field label**: `FIELD_LABEL_CLASS` vs `DETAIL_LABEL_CLASS` (`code-tab.tsx:38`), stats-strip/detail-stats labels, `CONFIG_LABEL_CLASS`, `sidebar.tsx:156`; four tracking variables plus a literal `0.05em`.

Target: `PageHeader` component plus three named text roles. Values will change with the direction; the point is that there are three places to change.

### 7. Alerts and error states

Five routes for showing an error: `ErrorAlert` and `ErrorBanner` (both thin wrappers over `AlertShell`), `layout/alert-banner.tsx:28` (hand-rolled, different border token), error-in-a-`Card` (`code-tab.tsx:128`, `config-tab.tsx:225`), and `EmptyState` for a fetch failure (`execution-detail.tsx:224`). `recent-activity-section.tsx:131` renders its load error as a red `<p>`.

Target: everything on `AlertShell`; one fetch-failure component.

### 8. Code / preformatted blocks

Eight `<pre>` styles: `traceback-viewer.tsx:72`, `error-banner.tsx:46`, `stack-frames.tsx` (`STACK_PRE_CLASS`), `registration-source.tsx:10`, `service-row.tsx:80`, `log-detail-drawer.tsx:220/237`, `config-schema-view.tsx:68`, plus Shiki blocks in `config-tab.tsx:31` and `code-tab.tsx:148` with duplicated theme setup.

Target: one `CodeBlock` (plain / traceback / highlighted) and one Shiki theme module.

### 9. Table styling

`ui/table` is used by 2 of 6+ table sites. Four pages each define a local `DATA_TABLE_CLASS` with their own `[&_th]` selectors (`apps.tsx:103`, `handlers.tsx:44`, `recent-activity-section.tsx:21`, `config-tab.tsx:20`); `execution-table.tsx:44` has its own `HEAD_CLASS`/`CELL_CLASS`.

Target: one table style (on `ui/table`). Which records are tables vs rows vs cards stays a wireframe decision.

### 10. Card primitive

About 9 container styles with mixed radius (`sm`/`md`), border token (`border-border`/`--border-strong`/`--border-subtle`), shadow (none/`sm`/`md`/`--shadow-2`) and padding (p-3…p-6). Only about half go through `Card`. `login.tsx:17` hand-composes `cardVariants` while `session-expired.tsx` uses `<Card>`.

Target: the shared shells (`Panel`, `TableCard`, `StatsStrip` frame, login/session-expired, `HandlerDetailLayout`) on `Card` variants. The App Detail ad-hoc cards are under "wait".

### 11. Small fixes found along the way

- Relative times that never refresh (no `useRelativeTime`/tick): `recent-activity-section.tsx:97`, `execution-table.tsx:146`, `loop-stalls-panel.tsx:24`. A bug regardless of redesign.
- Local duration formatter `config-schema-view.tsx:187`; hand-built rate `apps.tsx:146`.
- Empty-state copy casing/periods inconsistent (`handler-health-grid.tsx:29`, palette in `app.tsx:402`); ad-hoc empty text in `execution-logs.tsx:32`, `sidebar.tsx:312`.
- Mobile nav drawer hand-rolled in `app.tsx:215` (own Escape/focus handling) while `ui/Drawer` exists.
- Badge variant overlap: `destructive`/`danger`, `neutral`/`muted` (21 variants total).

### 12. Information only in `title=` tooltips (#1010) — needs a decision first

About 28 `title=` attributes; most duplicate visible text, but these carry information shown nowhere else and are unreachable on touch/keyboard: absolute timestamps behind relative labels (`apps-table-row.tsx:180`, `loop-stalls-panel.tsx:23`, `unified-handler-row.tsx:135`, `execution-table.tsx:144`), the drop breakdown and handler-failure hints in `system-health.tsx:131/145`, "Total calls" in `unified-handler-row.tsx:125`. `ui/tooltip` is used in one place (`handler-health-card.tsx`) and does not open on touch.

Decision needed before unifying: hint mechanism for touch (tap-to-open popover vs always-visible secondary text vs tooltip-on-desktop-only).

## Wait for wireframe

- **Stat displays** — `StatsStrip`, `DetailStats` (duplicate cell type, different styles), inline label+number rows in `handler-health-card`, `unified-handler-row`, `handlers-rows`, `apps-table-row`, sidebar count boxes, prose stat lines. "Data shown visually / big numbers" will reshape these.
- **Row- and card-as-button surfaces** — `unified-handler-row.tsx:69`, `handler-health-card.tsx:89` (`div role="button"`), `multi-instance.tsx:72`, `error-spotlight.tsx:71`, mobile `HandlerMobileRow`. Handler list vs health grid is a structural question (#2018).
- **Detail headers** — `AppDetailHeader` (status shape and status badge both shown, #1127 label competition), `DetailHeader`, `multi-instance.tsx:118`, `execution-detail.tsx:125`.
- **Status as shape vs badge** — which one a given surface uses is a design call; only the variant overlap above is mechanical.
- **Overview section composition** — `OVERVIEW_SECTION_CLASS` sections, finding cards, error spotlight.
- **Run-history strips / sparklines** — only `MiniSparkline` exists (one use); the redesign adds rather than unifies.
