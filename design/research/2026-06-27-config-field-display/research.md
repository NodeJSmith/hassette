---
topic: "read-only config field display — label/key/type/value/help density vs clarity"
date: 2026-06-27
status: Draft
---

# Prior Art: Read-Only Display of Dense Config Fields

## The Problem

We render a read-only config view from a JSON-schema + values pair. Each field carries five
roles — human label, machine (TOML) key, type, current value, help string. The current 2-column
`<table>` collapses three of those roles into indistinguishable monospace, allocates width
backwards (short values hog space; long labels/descriptions are cramped), shows verbose help
always-on, and stacks group/instance headings into a muddy pile. We want patterns from mature
read-only property/detail views before committing to a new shape.

## How We Do It Today

A 3-column `<table>` per section (label cell / value cell / right-aligned type cell), wrapped in
`Card variant="config"`, grouped under `<h2 class="ht-section-label">`, flipping to block layout at
768px. The app-detail tab nests this in a 2-col fields/raw grid with `Instance N` heading bars.
Available primitives to rebuild with: `Badge`, `Card`, `ht-detail-label`, tokens (spacing/type/ink),
CSS Modules + 768/480px breakpoints. The codebase already has horizontal label→value readouts (the
`FILE/CLASS/ENABLED` meta row, DetailPanel strips) using `ht-detail-label` (uppercase micro mono).

## Patterns Found

### Pattern 1: Two-tier typographic split — one register per role, mono reserved for the key
**Used by**: Innovaccer KeyValuePair (muted-gray key / near-black value), VS Code settings (bold
title, muted description, subordinate machine key), Cloudscape, ServiceNow.
**How it works**: Separate the three text roles by weight + color first, font-family second. The
human label is the sans anchor; the value is sans but distinguished by weight/color; the machine key
is the ONLY monospace element so it reads as "the literal string you type." VS Code makes the human
title dominant, description muted, machine key dim, and conveys type via the value's affordance.
**Strengths**: Cheapest fix for "no role distinction" — color/weight/font per role, not structural.
**Weaknesses**: Needs a real contrast delta; muted text must still pass contrast.
**Example**: https://design.innovaccer.com/components/keyValuePair/usage/

### Pattern 2: Description list (`<dl>` / CSS grid), label-side gets the width
**Used by**: PatternFly (horizontal + two-column), Polaris DescriptionList, Cloudscape.
**How it works**: Replace `<table>` with `<dl>`/CSS grid so YOU set the label/value proportions
instead of the table sizing the value column to the widest value across all rows. Since our values
are short and labels/descriptions long, flip the usual ratio: wide label/description column,
narrow content-sized value rail. PatternFly offers horizontal (wide) ↔ vertical (narrow) orientations.
**Strengths**: Correct semantics; kills the backwards column sizing AND the narrow-width overflow.
**Weaknesses**: A bare `<dl>` models two roles; label+key+type+value+help needs internal discipline.
**Example**: https://www.patternfly.org/components/description-list/html/horizontal-two-column/

### Pattern 3: Help off the row — demote inline or hide behind a quiet trigger
**Used by**: PatternFly (popover on a dotted-underlined label), VS Code (demoted muted description),
Primer/IxDF progressive disclosure.
**How it works**: The verbose description doesn't sit on the row at full strength. Either (a) demote
it to muted, smaller, lower-contrast text under the label (VS Code), or (b) hide it behind a
persistent trigger — PatternFly uses a dotted underline rather than a per-row icon/link "where a blue
link or icon would clutter." Trigger must be persistent/discoverable (not hover-only).
**Strengths**: Restores scannability without losing help.
**Weaknesses**: Hidden help is less discoverable; popovers are fiddly on touch.
**Example**: https://www.patternfly.org/components/description-list/design-guidelines/

### Pattern 4: Type as a muted chip — or implied by the value's affordance
**Used by**: VS Code (type implied by control), Material/Telerik badge guidance.
**How it works**: Either let the value's rendering carry the type (boolean→badge, enum→chip,
number→right-aligned, path→mono) and print no type word, or use a small low-saturation monochrome
chip where the type is genuinely ambiguous. Reserve saturated color for status, not type metadata.
**Strengths**: Adds the role without a column or stolen emphasis.
**Weaknesses**: A column of identical `string` chips is noise — prefer implicit typing where the
value already telegraphs the type.
**Example**: https://code.visualstudio.com/docs/getstarted/settings

### Pattern 5: Container-query responsive collapse — grid → single stacked column
**Used by**: Cloudscape (container queries, collapsing columns), Innovaccer, PatternFly, ServiceNow.
**How it works**: Respond to the container's width, not the viewport — a config panel docked narrow
should stack even on a wide screen. Within-pair, flip horizontal (label-left/value-right) to stacked
(label-over-value) below a width threshold. Safe narrow state is a single stacked column.
**Strengths**: One layout serves dense desktop and narrow sidebar/mobile.
**Weaknesses**: Stacking multiplies vertical scroll; value-comparison alignment is lost when stacked.
**Example**: https://cloudscape.design/get-started/dev-guides/responsive-development/

### Pattern 6: Group into titled cards with a real hierarchy delta — not a flat stack
**Used by**: Polaris resource-details pattern, VS Code (collapsible categories), Cloudscape.
**How it works**: Each group/instance gets a bounded card with a typographically distinct header
(heavier weight, more space above than below, hairline/tint) so "new group" parses instantly.
Collapsibility folds an entire instance's config.
**Strengths**: Converts a muddy stack into scannable chunks.
**Weaknesses**: Over-segmentation fragments; headers need a real weight/spacing delta or they re-muddy.
**Example**: https://polaris-react.shopify.com/patterns/resource-details-layout

## Anti-Patterns

- **`<table>` for name→value pairs** — value column auto-sizes to the global widest value → exactly
  our "value hogs space" bug. Name-value data is 1D → `<dl>`/grid.
- **Monospace for everything** — key and value collide. Reserve mono for the key only.
- **Always-on verbose descriptions per row** — destroys scannability; move to popover/demote.
- **Multiple inline pairs per row at narrow widths** — value↔label mapping gets ambiguous; stack.
- **Hover-only help triggers** — excludes keyboard/touch; trigger must be persistent.
- **Repetitive type chips where the value already telegraphs the type** — prefer implicit typing.

## Emerging Trends

- **Container/element queries** over viewport media queries for embeddable panels (Cloudscape).
- **Noise suppression as a feature** — Terraform's `# (N unchanged attributes hidden)` /
  `(sensitive value)`: mature readouts hide defaults rather than render every field at full
  verbosity. Relevant — many of our fields sit at default/unset (`—`).

## Relevance to Us

- Our reported bugs are textbook: the **`<table>`** is the root of both "backwards width" and the
  360px overflow; **mono-for-everything** is the root of "key/value indistinguishable."
- We already own the right primitives (`Badge`, `Card`, `ht-detail-label`, tokens) and already have
  a partial Pattern 3 (the mobile info-toggle I built). Moving to a `<dl>`/CSS-grid field list
  (Pattern 2) + three-register typography (Pattern 1) is the smallest structural change that fixes
  the cluster, and it reuses existing house conventions.
- Pattern 6 fixes the `Instance N` + redundant `general` muddy stack; collapse `general` when it's
  the only group.
- Pattern 5's container-query nuance matters because the app-detail tab embeds this in a narrow grid
  column — viewport breakpoints alone mispredict the available width (that's why 360px overflowed).

## Recommendation

Adopt a blend: **Pattern 2 (dl/grid, label-side wide) as the skeleton**, **Pattern 1 (three
typographic registers, mono only for the key) for role distinction**, **Pattern 4 (muted/implicit
type) and Pattern 3 (demoted or toggle-revealed help) for density**, **Pattern 6 for grouping**.
Consider Pattern 5 (container width) and the Terraform default-suppression idea as follow-ups.
Mock 2 directions (horizontal label→value vs stacked-block) before implementing.

## Sources

### Reference implementations
- https://code.visualstudio.com/docs/getstarted/settings — VS Code settings (title/key/desc/value)
- https://developer.hashicorp.com/terraform/cli/commands/show — Terraform state readout, suppression

### Design-system components
- https://cloudscape.design/components/key-value-pairs/ — AWS read-only key-value primitive
- https://polaris-react.shopify.com/components/lists/description-list — Polaris DescriptionList
- https://polaris-react.shopify.com/patterns/resource-details-layout — Polaris grouping pattern
- https://www.patternfly.org/components/description-list/design-guidelines/ — PatternFly help-popover
- https://www.patternfly.org/components/description-list/html/horizontal-two-column/ — horizontal dl
- https://design.innovaccer.com/components/keyValuePair/usage/ — numeric space/typography recipe
- https://horizon.servicenow.com/workspace/components/now-label-value-inline — inline vs stacked

### Guidance & writeups
- https://benmyers.dev/blog/on-the-dl/ — name-value data is a description list
- https://medium.com/@libiros/dl-or-table-research-of-approaches-to-creating-an-html-of-key-value-pairs-7085df953b7e — dl vs table
- https://ixdf.org/literature/topics/progressive-disclosure — progressive disclosure
- https://primer.style/ui-patterns/progressive-disclosure — GitHub progressive disclosure
- https://www.setproduct.com/blog/badge-ui-design — badge/chip guidance
