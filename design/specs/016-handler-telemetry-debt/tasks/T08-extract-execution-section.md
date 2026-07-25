---
task_id: "T08"
title: "Extract ExecutionSection sub-component + tests"
status: "planned"
depends_on: []
implements: ["FR#5", "AC#2"]
---

## Summary

Extract the execution section of `HandlerDetailLayout` (heading, loading spinner, ExecutionTable) into a standalone `ExecutionSection` component with its own co-located CSS module and unit tests. The component derives `hasData` from `records !== undefined` internally.

## Target Files

- create: `frontend/src/components/app-detail/execution-section.tsx`
- create: `frontend/src/components/app-detail/execution-section.module.css`
- create: `frontend/src/components/app-detail/execution-section.test.tsx`
- read: `frontend/src/components/app-detail/handler-detail-layout.tsx`
- read: `frontend/src/components/app-detail/handler-detail-layout.module.css`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

Create `frontend/src/components/app-detail/execution-section.tsx` by extracting the execution section from `handler-detail-layout.tsx` (lines 123-138):

```tsx
interface ExecutionSectionProps {
  heading: string;
  records: ExecutionRecord[] | undefined;
  kind: "handler" | "job";
  tableId: string;
  loading: boolean;
  appKey?: string;
  handlerKind?: HandlerKind;
  handlerId?: number;
  instanceQs?: string;
}
```

The component renders:
- `<h3>` with the heading (`.panelHeading` style)
- Conditional: if `loading && records === undefined` → `<Spinner />`; else → `<ExecutionTable records={records ?? []} kind={kind} ...>`
- `records` is `undefined` when data hasn't loaded yet (shows spinner); an empty array means "loaded but empty" (shows empty table). The `?? []` coercion happens inside ExecutionSection, not at the call site — this preserves the loading spinner behavior that the current `executionHasData` prop provides.

Create `execution-section.module.css` with:
- `.executionsSection` (lines 46-50 of handler-detail-layout.module.css)
- `.panelHeading` (lines 59-65)

Create `execution-section.test.tsx`:
- Test: renders heading text
- Test: shows spinner when loading and records is undefined
- Test: shows ExecutionTable when records is an empty array (loaded but empty)
- Test: shows ExecutionTable when records exist (even if loading)
- Test: passes correct props to ExecutionTable

Do NOT modify `handler-detail-layout.tsx` yet — that happens in T10.

## Focus

- The `records` type is `ExecutionRecord[] | undefined` from `../shared/execution-table` — `undefined` means "not yet loaded" (spinner), empty array means "loaded but empty" (empty table). This distinction preserves the current behavior where `executionHasData={executions !== undefined}` is a separate prop.
- `HandlerKind` is from `../../utils/app-routes`.
- The `?? []` coercion to pass to `ExecutionTable` happens inside this component, not at the call site.

## Verify

- [ ] FR#5: `ExecutionSection` renders heading, loading/spinner, and ExecutionTable; derives hasData internally
- [ ] AC#2: `execution-section.tsx` exists as a standalone component with its own CSS module; `cd frontend && npm run build` passes
