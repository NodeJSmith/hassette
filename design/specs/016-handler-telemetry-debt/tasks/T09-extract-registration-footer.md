---
task_id: "T09"
title: "Extract RegistrationFooter sub-component + tests"
status: "planned"
depends_on: []
implements: ["FR#6", "AC#2"]
---

## Summary

Extract the registration footer section of `HandlerDetailLayout` (source location, view-in-code button, collapsible registration source) into a standalone `RegistrationFooter` component with its own co-located CSS module and unit tests. This component owns the `registrationExpanded` toggle state.

## Target Files

- create: `frontend/src/components/app-detail/registration-footer.tsx`
- create: `frontend/src/components/app-detail/registration-footer.module.css`
- create: `frontend/src/components/app-detail/registration-footer.test.tsx`
- read: `frontend/src/components/app-detail/handler-detail-layout.tsx`
- read: `frontend/src/components/app-detail/handler-detail-layout.module.css`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

Create `frontend/src/components/app-detail/registration-footer.tsx` by extracting the registration footer from `handler-detail-layout.tsx` (lines 140-189):

```tsx
interface RegistrationFooterProps {
  kind: "handler" | "job";
  testId: string;
  sourceLocation?: string | null;
  registrationSource?: string | null;
  onViewCode?: (line?: number) => void;
}
```

The component:
- Owns `const [registrationExpanded, setRegistrationExpanded] = useState(false)`
- Renders conditionally: only if `sourceLocation || registrationSource`
- Shows source location via `<SourceLocation>`
- Shows "view in code" button (when `onViewCode && sourceLocation`) with `parseSourceLocation` for the line number
- Shows "show call / hide call" toggle button (when `registrationSource`)
- Collapses/expands `<RegistrationSource>` panel based on toggle state
- Uses `kind` for `data-testid` prefixes (e.g., `${kind}-registration-toggle`)
- Uses `testId` for the panel and heading IDs (e.g., `${testId}-registration-source-panel`)

Create `registration-footer.module.css` with CSS classes from `handler-detail-layout.module.css`:
- `.footer` (lines 67-76)
- `.footerSummary` (lines 78-83)
- `.footerIdentity` (lines 85-90)
- `.footerLabel` (lines 92-100)
- `.footerIdentity :global(.ht-text-muted)` (lines 102-104)
- `.footerActions` (lines 106-112)
- `@media` query for `.footerSummary` and `.footerActions` (lines 114-124)

Create `registration-footer.test.tsx`:
- Test: renders nothing when no sourceLocation and no registrationSource
- Test: shows source location when provided
- Test: shows view-in-code button when onViewCode and sourceLocation are provided
- Test: toggles registration source visibility on button click
- Test: hides view-in-code button when onViewCode is not provided

Do NOT modify `handler-detail-layout.tsx` yet — that happens in T10.

## Focus

- Import `SourceLocation` from `../shared/source-location`, `RegistrationSource` from `../shared/registration-source`, `Button` from `../shared/button`.
- Import `IconArrowRight`, `IconChevron` from `../shared/icons`.
- Import `parseSourceLocation` from `../../utils/format`.
- The `testId` prop is used to construct `aria-controls` and `aria-labelledby` IDs — it comes from the parent's `testId` (e.g., `listener-detail-42`).

## Verify

- [ ] FR#6: `RegistrationFooter` owns toggle state and renders source location, view-in-code, and collapsible registration source
- [ ] AC#2: `registration-footer.tsx` exists as a standalone component with its own CSS module; `cd frontend && npm run build` passes
