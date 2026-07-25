---
task_id: "T10"
title: "Rewrite callers to compositor pattern"
status: "planned"
depends_on: ["T06", "T07", "T08", "T09"]
implements: ["FR#3", "AC#2"]
---

## Summary

Reduce `HandlerDetailLayout` to a thin layout shell (`testId` + `children`) and rewrite both callers (`ListenerDetail`, `JobDetail`) to compose the extracted sub-components directly. Update `handler-detail-layout.module.css` to keep only `.wrapper`, `.content`, and `.runNow`. This is the integration task that ties together the stat-cell builder (T06) and the three sub-components (T07-T09).

## Target Files

- modify: `frontend/src/components/app-detail/handler-detail-layout.tsx`
- modify: `frontend/src/components/app-detail/handler-detail-layout.module.css`
- modify: `frontend/src/components/app-detail/listener-detail.tsx`
- modify: `frontend/src/components/app-detail/job-detail.tsx`
- read: `frontend/src/components/app-detail/detail-header.tsx`
- read: `frontend/src/components/app-detail/execution-section.tsx`
- read: `frontend/src/components/app-detail/registration-footer.tsx`
- read: `frontend/src/components/app-detail/stat-cell-builders.ts`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

**Reduce HandlerDetailLayout** to a thin layout shell:

```tsx
interface Props {
  testId: string;
  children: ComponentChildren;
}

export function HandlerDetailLayout({ testId, children }: Props) {
  return (
    <div class={styles.wrapper} data-testid={testId}>
      <div class={styles.content}>{children}</div>
    </div>
  );
}
```

Remove all other props, rendering logic, and state. The old `ErrorInfo` interface can be removed from this file (the callers construct error props inline for `ErrorBanner`).

**Update handler-detail-layout.module.css**: remove all classes except `.wrapper`, `.content`, and `.runNow`. The moved classes now live in the sub-component CSS modules (T07-T09).

**Rewrite ListenerDetail** (`listener-detail.tsx`) to compose sub-components:

```tsx
<HandlerDetailLayout testId={`listener-detail-${listener.listener_id}`}>
  <DetailHeader name={lastDotSegment(listener.handler_method)} statusKind={listenerKind} kindLabel={kindLabel} kind="handler" subtitle={listener.human_description} />
  <ModifierChips listener={listener} />
  {listenerKind === "err" && (
    <ErrorBanner errorType={...} errorMessage={...} traceback={...} data-testid="handler-error-banner" />
  )}
  <DetailStats cells={buildCommonStatCells({...}).concat(listenerSpecificCells)} data-testid="handler-stats-row" />
  <ExecutionSection heading="invocations" records={executions} kind="handler" tableId={...} loading={loading} appKey={appKey} handlerKind="listener" handlerId={listener.listener_id} instanceQs={instanceQs} />
  <RegistrationFooter kind="handler" testId={`listener-detail-${listener.listener_id}`} sourceLocation={listener.source_location} registrationSource={listener.registration_source} onViewCode={onSwitchToCode} />
</HandlerDetailLayout>
```

**Rewrite JobDetail** (`job-detail.tsx`) similarly. Note:
- `job-detail.tsx` currently imports `layoutStyles` from `handler-detail-layout.module.css` for `.runNow` and `.subtitle`
- After the rewrite: `.runNow` stays in `handler-detail-layout.module.css` — keep importing it
- `.subtitle` moved to `detail-header.module.css` — import from there for the predicate description

## Focus

- The callers must produce identical visual output. The composition is structural, not behavioral.
- `ListenerDetail` uses `listenerHealthKind` from `./handler-list`; `JobDetail` uses `jobHealthKind`.
- The error banner is conditional on `statusKind === "err"` — both callers already construct the error object inline.
- `job-detail.tsx`'s `RunNowButton` component stays in `job-detail.tsx` — it's job-specific, not extracted.
- Verify with `cd frontend && npm run build && npm test` that everything compiles and existing tests pass.

## Verify

- [ ] FR#3: `HandlerDetailLayout` accepts only `testId` and `children`; all rendering delegated to sub-components
- [ ] AC#2: `cd frontend && npm run build && npm test` passes; `grep -c "children" frontend/src/components/app-detail/handler-detail-layout.tsx` confirms the thin shell
