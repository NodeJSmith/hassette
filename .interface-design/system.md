# Hassette Design System

## Intent

**Who:** A developer running Home Assistant automations — technical, comfortable with code, checking dashboards between tasks or debugging at midnight.

**Task:** Monitor app health, inspect event flow, review logs, manage scheduled jobs. Rapid scanning of status, not prolonged reading.

**Feel:** Like a well-lit control room. Cool and composed, with a single warm indicator light that draws the eye to what matters. Dense but never cluttered. The interface should feel like a tool you trust — quiet when things are fine, unmistakable when they're not.

## Direction

**Domain:** Home automation control plane — dashboards, status indicators, event streams, entity state, scheduled tasks.

**Color world:** Cool slate walls of a server room, warm amber of an indicator LED, green/red status lights on equipment racks.

**Signature:** The breathing pulse dot (`ht-pulse-dot`) — a slow amber inhale/exhale animation on live-connected panels. Static red when disconnected. It could only exist for a system that maintains a persistent WebSocket to a home automation hub.

**Rejecting:**
- Generic blue primary (every SaaS app) -> warm amber accent (`#D4915C`) for identity
- Drop shadows for depth (Bulma default) -> borders-only depth strategy
- System fonts (invisible) -> Space Grotesk headings (geometric, technical character)
- Standard body copy font -> JetBrains Mono for data/code (this is a developer tool)

---

## Foundation

**Palette:** Cool slate (`--ht-slate-50` through `--ht-slate-900`)
**Accent:** Warm amber `#D4915C`, hover `#c07e4a`, dim `rgba(212, 145, 92, 0.35)`
**Depth strategy:** Borders-only — `rgba(0, 0, 0, 0.08)` default, `0.15` strong, `0.04` subtle. No box-shadows.

### Surfaces

| Level | Token                   | Value                          | Use                        |
| ----- | ----------------------- | ------------------------------ | -------------------------- |
| L0    | `--ht-surface-canvas`   | slate-50 (`#f8fafc`)           | Page background            |
| L1    | `--ht-surface-card`     | `#ffffff`                      | Cards, panels              |
| L2    | `--ht-surface-dropdown` | `#ffffff` + strong border      | Dropdowns, popovers        |
| —     | `--ht-surface-sidebar`  | slate-900 (`#0f172a`)          | Dark sidebar               |
| —     | `--ht-surface-sticky`   | `white`                        | Sticky table headers       |
| —     | `--ht-surface-inset`    | `rgba(0, 0, 0, 0.05)`         | Alert items, nested panels |
| —     | `--ht-surface-code`     | `#1e1e2e`                      | Code blocks, tracebacks    |

### Semantic Colors

Each semantic color has three tokens: base, `-light` (background tint), `-text` (high-contrast label).

| Semantic | Base      | Light     | Text      |
| -------- | --------- | --------- | --------- |
| Success  | `#16a34a` | `#f0fdf4` | `#166534` |
| Danger   | `#dc2626` | `#fef2f2` | `#991b1b` |
| Warning  | `#ca8a04` | `#fefce8` | `#854d0e` |
| Info     | `#2563eb` | `#eff6ff` | `#1e40af` |
| Link     | `#7c3aed` | `#f5f3ff` | `#5b21b6` |
| Critical | `#991b1b` | —         | —         |

### Alert Tints

Translucent overlays for alert banners (warning/danger variants):

| Token                  | Value                        |
| ---------------------- | ---------------------------- |
| `--ht-warning-bg`      | `rgba(234, 179, 8, 0.1)`    |
| `--ht-warning-border`  | `rgba(234, 179, 8, 0.3)`    |
| `--ht-danger-bg`       | `rgba(239, 68, 68, 0.1)`    |
| `--ht-danger-border`   | `rgba(239, 68, 68, 0.3)`    |

---

## Typography

| Role        | Font              | Token               |
| ----------- | ----------------- | ------------------- |
| Headings    | Space Grotesk 600 | `--ht-font-heading` |
| Body        | system-ui stack   | `--ht-font-body`    |
| Data / code | JetBrains Mono    | `--ht-font-mono`    |

### Type Scale

| Token            | Size | Use                                      |
| ---------------- | ---- | ---------------------------------------- |
| `--ht-text-xs`   | 12px | Table data, timestamps, secondary labels |
| `--ht-text-sm`   | 13px | Compact UI, badge text                   |
| `--ht-text-base` | 14px | Body text, form inputs                   |
| `--ht-text-lg`   | 16px | Section headings, emphasis               |
| `--ht-text-xl`   | 20px | Page headings                            |
| `--ht-text-2xl`  | 24px | Dashboard hero numbers                   |

---

## Spacing

4px grid. Tokens: `--ht-sp-{1,2,3,4,6,8,12}` = 4, 8, 12, 16, 24, 32, 48px.

---

## Radius

| Token              | Value  | Use                    |
| ------------------ | ------ | ---------------------- |
| `--ht-radius-sm`   | 3px    | Badges, small tags     |
| `--ht-radius-md`   | 5px    | Cards, buttons, inputs |
| `--ht-radius-lg`   | 8px    | Large panels, modals   |
| `--ht-radius-full` | 9999px | Pills, dots            |

---

## Component Patterns

### Card (`ht-card`)

```
border: 1px solid var(--ht-border)
border-radius: var(--ht-radius-md)     /* 5px */
padding: var(--ht-sp-4) var(--ht-sp-6) /* 16px 24px */
background: var(--ht-surface-card)
```

### Button (`ht-btn`)

```
height: auto (padding-driven)
padding: 0.4em 0.85em
border-radius: var(--ht-radius-md)     /* 5px */
font-size: var(--ht-text-sm)           /* 13px */
font-weight: 500
border: 1px solid
```

Small variant (`ht-btn--sm`): `padding: 0.25em 0.6em`, `font-size: var(--ht-text-xs)`.

Semantic variants: `--success`, `--danger`, `--warning`, `--info`, `--link`, `--primary` (amber).

### Badge (`ht-badge`)

```
padding: 0.3em 0.5em
border-radius: var(--ht-radius-sm)     /* 3px */
font-size: var(--ht-text-xs)           /* 12px */
font-weight: 500
```

Small variant (`ht-badge--sm`): `0.1em 0.45em`, `font-size: 0.6875rem (11px)`.
Medium variant (`ht-badge--md`): `0.2em 0.65em`.

Semantic variants match button patterns. Status-specific: `ht-status-stopped`, `ht-status-disabled`, `ht-status-blocked`.

### Table (`ht-table`)

```
width: 100%
border-bottom: 1px solid var(--ht-border)
th padding: 0.4em 0.85em
td padding: 0.4em 0.85em
```

Dense variant (`ht-table--dense`): `0.25em 0.5em` cell padding.
Striped variant (`ht-table--striped`): alternating `var(--ht-surface-canvas)` rows.

### Input / Select (`ht-input`, `ht-select`)

```
padding: 0.35em 0.6em
border: 1px solid var(--ht-border-strong)
border-radius: var(--ht-radius-md)
font-size: var(--ht-text-base)
```

Small variants: `font-size: var(--ht-text-xs)`, `padding: 0.25em 0.5em`.

### Sidebar

```
width: 220px (expanded), 56px (collapsed icon rail)
background: var(--ht-surface-sidebar)  /* slate-900 */
transition: width 0.2s ease
```

Nav link: `padding: 0.6rem 1.25rem`, active state uses `var(--ht-sidebar-active-bg)` + `var(--ht-sidebar-active-color)`.

Mobile: collapses to 56px icon rail by default, expands to 260px overlay with backdrop.

### Pulse Dot (Signature)

```css
.ht-pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ht-amber);
  animation: ht-breathe 3s ease-in-out infinite;  /* slow inhale/exhale */
}
.ht-pulse-dot--disconnected {
  background: var(--ht-danger);
  animation: none;
}
```

---

## Layout

### Grid (`ht-grid`)

CSS Grid, 12-column, `gap: var(--ht-sp-4)` (16px). Column classes: `ht-grid-col-{1..12}`.

### Level (`ht-level`)

Flexbox row, `justify-content: space-between`, `align-items: center`. Children: `ht-level-start`, `ht-level-end`, `ht-level-item`.

### Tabs (`ht-tabs`)

Flex row with bottom border. Active tab: amber bottom border + bold text.

---

## Breakpoints

| Breakpoint | Behavior                                                                                       |
| ---------- | ---------------------------------------------------------------------------------------------- |
| > 768px    | Desktop: sidebar open, 12-col grid                                                             |
| <= 768px   | Tablet/mobile: sidebar collapses to icon rail, grid becomes single column, status bar compacts |
| <= 480px   | Small phone: reduced padding                                                                   |

---

## Theming

All tokens live in `static/css/tokens.css` under `:root, [data-theme="default"]`. Components in `style.css` reference only token variables — no hardcoded colors.

To create a new theme: copy `tokens.css`, change the selector to `[data-theme="your-theme"]`, override values. Set `data-theme` attribute on `<html>` to activate.

---

## CSS Class Prefix

All classes use `ht-` prefix. The only non-prefixed class is `is-active` (retained for Alpine.js toggle compatibility on nav links and tabs).
