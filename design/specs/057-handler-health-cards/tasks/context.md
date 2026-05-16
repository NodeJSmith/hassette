# Context: Handler Health Cards

## Problem & Motivation

The handler health section on the app detail overview tab uses a data table that distributes whitespace evenly across columns, creating large empty gaps that make the section feel sparse and hard to scan. The primary use case is a 5-second health check: glance, spot failing handlers, click in. The table layout works against this by forcing the eye across wide rows and making healthy and failing handlers visually equivalent. Cards are a better container because each handler is a self-contained unit with heterogeneous metadata, and cards let each unit own its vertical space with per-card error treatment.

## Visual Artifacts

None.

## Key Decisions

1. **Grid of compact cards** over stacked list cards or stat-forward cards — grid is denser for the quick-scan use case, each card is self-contained.
2. **Red 2px top border** for failing cards, not left-border accents (project convention) or background tint. Error type shown inline after the kind label; error message truncated to 1 line.
3. **CSS grid with `auto-fill`** and `minmax(280px, 1fr)` for natural 2-3 column responsiveness. Collapses to 1 column on mobile.
4. **Scroll container at ~3 rows** of cards. Cards grow the page until the threshold, then scroll.
5. **Extract `formatRate`** from `pages/handlers.tsx` to `utils/format.ts` — no duplication.
6. **Helper functions** (`isFailing`, `itemRunCount`, `itemKindChip`, `itemErrorType`, `itemErrorMessage`, `handlerPath`, `sortedByFailingFirst`) currently live in `overview-tab.tsx`. They must be accessible to both the new card component and the remaining overview-tab code (ErrorSpotlight uses several). Export or extract — do not duplicate.

## Constraints & Anti-Patterns

- **No left-border accents** — use top border for error state (project feedback memory).
- **No shadows** for card depth — borders only, per design context.
- **No border radius above `--r-md`** (6px), per design context.
- **All data values in monospace** (`--font-mono`), per design context.
- **Status colors are semantic only** — never decorative.
- **Token-only CSS** — every CSS value must reference a design token from `tokens.css`. No raw hex, no magic pixel values.
- **Do NOT touch** the error spotlight section, recent activity table, or logs section.
- **Do NOT add** sparklines, micro-animations, visualizations, or new data fields.

## Design Doc References

- `## Problem` — why tables fail for this data
- `## Architecture` — component decomposition, props interface, CSS grid layout, scroll container, formatRate extraction
- `## Key Constraints` — 6 explicit constraints
- `## Edge Cases` — 7 edge cases (single handler, zero runs, long names, long errors, 8+ handlers, all failing, error rate rounding)
- `## Convention Examples` — 5 code snippets showing clickable navigation, card surface styling, data helpers, chip usage, format utilities

## Convention Examples

### Clickable navigation with keyboard support

**Source:** `frontend/src/components/app-detail/overview-tab.tsx` (HealthGridRow)

```tsx
function HealthGridRow({ item, appKey, instanceQs }: HealthGridRowProps) {
  const [, navigate] = useLocation();
  const href = handlerPath(appKey, item, instanceQs);

  return (
    <tr
      class={clsx(styles.healthRow, isFailing(item) && styles.healthRowFailing)}
      data-testid={`overview-health-row-${item.kind}-${item.id}`}
      tabIndex={0}
      role="row"
      onClick={() => navigate(href)}
      onKeyDown={(e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigate(href);
        }
      }}
    >
      <td class={styles.healthRowName}>
        <Link href={href} class={styles.healthRowLink}
          onClick={(e: MouseEvent) => e.stopPropagation()}>
          {item.name}
        </Link>
      </td>
    </tr>
  );
}
```

Key pattern: whole-element `onClick` + `tabIndex={0}` + keyboard handler. Nested `Link` uses `e.stopPropagation()` to prevent double navigation. Use ARIA `role` appropriate to the element (will be `"link"` for cards, not `"row"`).

### Card surface styling with token-only values

**Source:** `frontend/src/components/shared/card.module.css`

```css
.card {
  background: var(--bg-surface);
  border: 1px solid var(--line-1);
  border-top: 1px solid var(--line-2);
  border-radius: var(--r-md);
  padding: var(--sp-5);
}

.compact {
  padding: var(--sp-3);
}
```

Key pattern: base class holds shared styles, variants are additive modifiers. Every value is a design token.

### Chip for metadata labels

**Source:** `frontend/src/components/app-detail/overview-tab.tsx`

```tsx
<Chip variant="muted" size="sm" aria-label={`kind: ${chipLabel}`}>
  {chipLabel}
</Chip>
```

Key pattern: `variant="muted"` for neutral metadata, `size="sm"` for compact contexts. Always include `aria-label`.

### Format utilities for stats display

**Source:** `frontend/src/utils/format.ts`

```tsx
export function formatDurationOrDash(ms: number | null | undefined): string {
  return ms !== null && ms !== undefined && ms > 0 ? formatDuration(ms) : "—";
}

export function pluralize(count: number, singular: string, plural?: string): string {
  const label = count === 1 ? singular : (plural ?? `${singular}s`);
  return `${count} ${label}`;
}
```

**Source:** `frontend/src/pages/handlers.tsx` (to be extracted to format.ts)

```tsx
function formatRate(failed: number, total: number): string {
  return total > 0 ? ((failed / total) * 100).toFixed(1) + "%" : "—";
}
```

Key pattern: format functions return "—" for missing/zero data.

### Component test pattern

**Source:** `frontend/src/components/app-detail/overview-tab.test.tsx`

```tsx
import { describe, expect, it, vi } from "vitest";
import { fireEvent, waitFor } from "@testing-library/preact";
import { renderWithAppState } from "../../test/render-helpers";

function renderOverviewTab({ listeners = [...], jobs = [...] } = {}) {
  return renderWithAppState(<OverviewTab {...props} />, {
    stateOverrides: { uptimeSeconds: signal<number | null>(120) },
  });
}

describe("OverviewTab — Error Spotlight", () => {
  it("is absent when no listeners or jobs are failing", () => {
    const { queryByTestId } = renderOverviewTab({ listeners: [...], jobs: [] });
    expect(queryByTestId("overview-error-spotlight")).toBeNull();
  });
});
```

Key pattern: `renderWithAppState` for components needing context, `data-testid` for queries, factory functions for test data.
