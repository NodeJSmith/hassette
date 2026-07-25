---
task_id: "T07"
title: "Extract DetailHeader sub-component + tests"
status: "planned"
depends_on: []
implements: ["FR#4", "AC#2"]
---

## Summary

Extract the header section of `HandlerDetailLayout` (name, status badge, kind chip, subtitle, header actions) into a standalone `DetailHeader` component with its own co-located CSS module and unit tests.

## Target Files

- create: `frontend/src/components/app-detail/detail-header.tsx`
- create: `frontend/src/components/app-detail/detail-header.module.css`
- create: `frontend/src/components/app-detail/detail-header.test.tsx`
- read: `frontend/src/components/app-detail/handler-detail-layout.tsx`
- read: `frontend/src/components/app-detail/handler-detail-layout.module.css`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

Create `frontend/src/components/app-detail/detail-header.tsx` by extracting the header section from `handler-detail-layout.tsx` (lines 87-106):

```tsx
interface DetailHeaderProps {
  name: string;
  kindLabel: string;
  statusKind: ChipKind;
  kind: "handler" | "job";
  subtitle?: string | null;
  headerActions?: ComponentChildren;
}
```

The component renders:
- `<h2>` with the handler name (`.handlerName` style)
- Conditional `<Badge variant="danger" size="sm">failing</Badge>` when `statusKind === "err"`
- Header actions slot (wrapped in `.headerActions` div)
- Subtitle row: `<Chip variant="kind">` with `<StatusShape>` + subtitle text

Create `detail-header.module.css` with the CSS classes moved from `handler-detail-layout.module.css`:
- `.header` (lines 14-19)
- `.headerActions` (lines 21-27)
- `.handlerName` (lines 29-34)
- `.subtitle` (lines 36-44)

Create `detail-header.test.tsx`:
- Test: renders handler name in heading
- Test: shows failing badge when `statusKind === "err"`
- Test: hides failing badge when status is ok
- Test: renders kind chip with correct label
- Test: renders subtitle when provided
- Test: renders header actions slot

Do NOT modify `handler-detail-layout.tsx` yet — that happens in T10 when the callers are rewritten.

## Focus

- The `.subtitle` class is also used by `job-detail.tsx` for the predicate description (`layoutStyles.subtitle`). After this extraction, `job-detail.tsx` will need to import from `detail-header.module.css` instead. This is handled in T10.
- Import `Badge` from `../shared/badge`, `Chip`/`ChipKind` from `../shared/chip`, `StatusShape` from `../shared/status-shape`.
- The `kind` prop is used for the `data-testid` prefix pattern (e.g., `${kind}-human-description`).

## Verify

- [ ] FR#4: `DetailHeader` renders name, status badge, kind chip, subtitle, and header actions
- [ ] AC#2: `detail-header.tsx` exists as a standalone component with its own CSS module; `cd frontend && npm run build` passes
