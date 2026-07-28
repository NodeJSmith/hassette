---
schema_version: 1
updated_at: 2026-07-28
---

# Hassette Design Context

This document defines the durable visual and interaction direction for Hassette's web UI. It is not a pixel specification or a catalog of every CSS value. The generated screenshots and the running frontend show the current baseline; this document explains what should remain recognizable as the interface improves.

## Users & Purpose

Hassette's primary user is a developer or homelab operator checking Home Assistant automations. They may be debugging at a desktop or checking system health from a phone. They usually arrive with a concrete question:

- Is the system connected and are my apps running?
- Which app, handler, or scheduled job failed?
- Did an automation run, skip, time out, or stop firing?
- What error, log line, source location, or configuration explains the result?

The interface is an operational and diagnostic tool. It should make a quick health check easy without hiding the evidence needed for deeper investigation.

## Visual Baseline

The generated `docs/_static/web_ui_*.png` images are the source of truth for the established direction. `docs/screenshots.yml` defines the standard capture set. Representative anchors include:

- `docs/_static/web_ui_apps.png`
- `docs/_static/web_ui_app_detail_overview.png`
- `docs/_static/web_ui_app_detail_handlers.png`
- `docs/_static/web_ui_logs.png`
- `docs/_static/web_ui_config.png`

Preserve their core structure and character while improving details incrementally. Do not redesign the product around a new concept unless that change is explicitly proposed and approved.

The baseline includes:

- Persistent desktop navigation with app health visible in the sidebar.
- A compact status bar and time-window controls.
- Serif page titles as an editorial accent within a technical interface.
- Dense tables, app-detail tabs, and master-detail inspection views.
- Light and dark themes with expressive operational colors.
- Direct access to logs, code, configuration, and execution history.

## Brand Personality

Hassette should feel calm, precise, trustworthy, and crafted. It is technical without pretending to be a terminal, and operational without resembling an enterprise control room.

The desired movement is **dense operational utility with editorial restraint**.

- **Dense**, because diagnosis depends on seeing related evidence together.
- **Operational**, because current state and recent outcomes matter more than decoration.
- **Editorial**, because hierarchy and typography should guide interpretation rather than merely contain data.
- **Restrained**, because exceptions need visual room to stand out.

The interface can use color confidently. Restraint means that color carries meaning, not that the product should become monochrome.

## Domain Language

The visual system should reflect Hassette's actual domain:

- Apps are registered runtime units with lifecycle and instance health.
- Handlers react to events; jobs run on schedules or triggers.
- Executions succeed, fail, skip, cancel, time out, or encounter backpressure.
- Health combines current state with recent behavior.
- Time windows change the evidence being inspected.
- Logs, source, configuration, and tracebacks explain outcomes.
- Disabled autostart and removed apps remain useful configuration or historical evidence.
- Home Assistant is a connected external system, not the visual model for this UI.

Use this vocabulary in labels and explanations. Prefer `app`, `handler`, `job`, `execution`, `listener`, and `instance` over organizational or infrastructure metaphors.

## Signature Pattern

Hassette's signature interaction is the **evidence trail**:

1. A health summary identifies an exception.
2. The exception leads to the relevant app, handler, or job.
3. The detail view shows the latest outcome and execution history.
4. The user can reach the error, log line, source registration, or configuration that explains it.

This trail should be visible in page structure and links, not only available through search. Error summaries should lead somewhere useful. Detail views should keep context while revealing evidence progressively.

## Design Principles

### Lead With Health

Connection state and app health should be understandable at a glance. Desktop navigation keeps app health visible. Mobile layouts may summarize or relocate it, but must not hide critical failures.

### Make Exceptions Louder

Healthy states should be calm. Failures, degraded states, timeouts, and blocked apps should interrupt that calm with clear status color and plain-language context. Do not make every healthy item compete for attention.

### Keep Evidence Connected

Place the explanation near the status it explains or provide an obvious next step. Preserve context when moving from an app to a handler, execution, log entry, source location, or configuration value.

### Be Dense, Not Tiny

Keep useful information together, but do not achieve density through unreadably small type or compressed controls. Create hierarchy with grouping, alignment, type weight, spacing, and selective disclosure.

### Improve In Place

Prefer small, reviewable improvements to the established screens. Reuse existing navigation and interaction models unless changing them solves a demonstrated problem.

## Layout & Information Architecture

- Preserve the desktop sidebar, top status bar, primary pages, app-detail tabs, and master-detail handler view.
- Keep app detail as the center of diagnostic work. Overview, handlers, code, logs, and config are complementary evidence surfaces.
- Use tables for comparable records and scanning. Use cards or grouped sections when relationships and explanation matter more than column comparison.
- Avoid wrapping every section in a card. Borders, spacing, and surface changes should establish hierarchy before additional containers are introduced.
- Keep primary page content left-aligned. Reserve centered layouts for narrow empty or loading states.
- Maintain readable line lengths for prose and errors. Code, tables, and tracebacks may use the available width.

## Responsive Behavior

Responsive design should adapt the task rather than shrink the desktop screen.

- At desktop widths, keep navigation and app health persistently visible.
- Below the sidebar breakpoint, use an accessible drawer with reliable focus management and dismissal.
- On mobile, prioritize connection state, current app health, recent failures, and the next useful action.
- Convert wide tables into priority-column or stacked-row presentations where horizontal scrolling would obscure meaning.
- In master-detail views, show the list and detail as separate steps on narrow screens, with a clear route back to the list.
- Do not remove critical actions or status information on mobile.
- Interactive targets should be at least 44px where touch input is expected.

## Typography

The established font roles are intentional:

| Role | Family | Use |
|---|---|---|
| Display | Newsreader | Product wordmark and primary page titles |
| Interface | Geist | Navigation, controls, labels, explanations, and body text |
| Data | Geist Mono | Code, paths, IDs, timestamps, durations, and compact numeric data |

Use monospace because the content benefits from fixed-width scanning, not as a generic signal that the product is technical.

### Hierarchy

- Page titles should be clearly larger than section titles.
- App and handler names should remain prominent even when they contain underscores or long identifiers.
- Core content and controls should be 13px or larger.
- Reserve 12px text for short, nonessential labels, badges, and metadata. Never put an error explanation, primary action, or required navigation at that size.
- Use uppercase and letter spacing sparingly for short table headers and category labels.
- Prefer weight and spacing over adding many near-identical font sizes.

Adjust the type scale incrementally and validate representative dense screens before changing it globally.

## Color

Hassette uses a paper-and-graphite neutral foundation with expressive semantic color.

| Role | Token family | Meaning |
|---|---|---|
| Page and chrome | `--background`, `--sidebar`, `--muted` | Quiet structure and orientation |
| Primary | `--primary` | Navigation, focus, links, and selected state |
| Success | `--status-success` | Running, healthy, and successful |
| Warning | `--status-warning` | Degraded, blocked, or attention needed |
| Destructive | `--destructive` | Failed, crashed, and error evidence |
| Cancelled | `--status-cancel` | Cancelled outcomes |
| Inactive | `--status-muted` | Stopped, disabled, unknown, or idle |
| Job | `--handler-job` | Scheduled-job category coding |
| Listener | `--handler-listener` | Event-listener category coding |

Concrete palette values may evolve, but these semantic roles should remain stable.

### Color Rules

- Use status color consistently across shapes, badges, summaries, rows, and details.
- Pair color with text or shape; color alone must not carry status.
- Use vivid status variants for charts or small marks that need stronger contrast, not large surfaces.
- Use tinted backgrounds for selected, warning, and error regions when they improve grouping.
- Keep the primary brand/action color distinct from status colors.
- Keep brand/action emphasis and subtle highlighted backgrounds as separate visual roles.
- Preserve separate job and listener colors when category distinction helps scanning.
- Avoid decorative gradients, neon glow, and low-contrast gray-on-color combinations.

## Spacing, Shape & Depth

### Spacing

- Use a 4px spacing rhythm, with 2px and half-step values only for compact or optical adjustments.
- Keep related label/value pairs tight and separate major sections generously.
- Prefer `gap` for component layout instead of ad hoc sibling margins.
- Do not reduce padding solely to fit more information if readability suffers.

### Shape

- Small controls and dense rows should use compact radii.
- Standard panels, popovers, and cards may use medium radii.
- Large rounded containers should be rare; the product should not feel soft or toy-like.
- Pills are appropriate for statuses and compact categorical badges, not general containers.

### Depth

Use surface tint, borders, and restrained shadows in that order. Shadows should separate major layers or interactive surfaces, not make every section float.

The current depth system is:

- Subtle borders for rows and internal grouping.
- Stronger borders for table shells and important panels.
- Small shadows for raised cards and controls.
- Larger shadows only for overlays, drawers, and transient layers.

## Motion & Interaction

- Use motion to explain state changes, opening, closing, and selection.
- Keep routine transitions between 120ms and 200ms with a non-bouncy easing curve.
- Animate opacity and transforms where practical; avoid decorative movement.
- Respect `prefers-reduced-motion`.
- Every interactive control needs visible hover, focus, active, disabled, and loading behavior where applicable.
- Keyboard navigation and focus order must remain usable in dense tables, tabs, drawers, menus, and master-detail views.
- Prefer progressive disclosure over showing every technical detail in the first row or card.

## Component Language

- Standard controls, overlays, badges, tables, and cards should share consistent structure and states.
- Visual differences should represent semantic differences such as status, category, selection, or emphasis.
- Reuse established components before introducing a one-off visual treatment.
- Keep interaction behavior consistent across pages: the same control should look and act like the same control.
- Responsive changes should follow shared layout thresholds rather than isolated component guesses.

Implementation mechanics and current frontend conventions belong in `CLAUDE.md` and the frontend source, not here.

## Accessibility

- Meet WCAG AA contrast for text, status labels, controls, and focus indicators.
- Never rely on color alone for health or outcome.
- Use semantic headings, tables, tabs, lists, buttons, and links.
- Preserve visible keyboard focus and logical reading order.
- Drawers and dialogs must trap or manage focus correctly, hide inactive content from assistive technology, and restore focus when closed.
- Truncation must preserve access to the full value through layout, title text, or a detail view.
- Loading, empty, disconnected, stale, and error states must explain what happened and what the user can do next.

## Avoid

- Generic SaaS dashboards made from interchangeable metric cards.
- Enterprise control-room language or styling.
- Home Assistant visual mimicry.
- Terminal cosplay, dark neon palettes, and excessive monospace.
- Faint grid backgrounds and decorative data visualization.
- Tiny supporting text used to manufacture density.
- Over-soft rounded containers and indiscriminate shadows.
- Dense handler layouts that expose every implementation detail before selection.
- Hiding app health or critical failures to create a cleaner composition.
- Redesigning multiple navigation or interaction models during a polish task.

## Evolving This Context

This document should change when an incremental improvement becomes an established convention, not for every one-off visual adjustment.

When changing the design:

1. Compare the result with the visual baseline and state why the deviation improves the user's task.
2. Test desktop and mobile behavior with realistic healthy, empty, degraded, and failing data.
3. Prefer a small implementation slice that can be reviewed independently.
4. Update this document only when the change establishes a reusable rule or replaces a baseline decision.
5. Refresh the affected visual baseline after the implementation is stable.
