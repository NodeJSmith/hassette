import type { CSSProperties } from "react";
import { useMemo } from "react";

import { useRovingTabIndex } from "../../hooks/use-roving-tab-index";
import { EmptyState } from "../shared/empty-state";
import { HandlerHealthCard } from "./handler-health-card";
import { OVERVIEW_SECTION_CLASS } from "./overview-section";
import { sortedByFailingFirst } from "./overview-tab-helpers";
import type { UnifiedItem } from "./unified-handler-row";

const SECTION_LABEL_CLASS = "mb-2 font-sans text-[length:var(--text-h3)] font-semibold text-foreground";

export function HandlerHealthGrid({
  items,
  appKey,
  instanceQs,
}: {
  items: UnifiedItem[];
  appKey: string;
  instanceQs: string;
}) {
  const sorted = useMemo(() => sortedByFailingFirst(items), [items]);
  // setActiveIndex omitted — clicking a card navigates away, unmounting the grid.
  const { containerRef, onContainerKeyDown, getTabIndex } = useRovingTabIndex<HTMLDivElement>(sorted.length, "both");

  if (items.length === 0) {
    return (
      <section className={OVERVIEW_SECTION_CLASS} data-testid="overview-health-grid">
        <h3 className={SECTION_LABEL_CLASS}>handler health</h3>
        <EmptyState
          title="No handlers registered"
          body="This app has not registered any event handlers or scheduled jobs."
          data-testid="overview-health-empty"
        />
      </section>
    );
  }

  return (
    <section className={OVERVIEW_SECTION_CLASS} data-testid="overview-health-grid">
      <h3 className={SECTION_LABEL_CLASS}>handler health</h3>
      <div
        className="max-h-[calc(var(--health-grid-rows)*var(--health-card-height)+2*var(--sp-3))] overflow-x-hidden overflow-y-auto"
        style={
          {
            "--health-card-height": "140px",
            "--health-card-min-width": "280px",
            "--health-grid-rows": 3,
          } as CSSProperties
        }
      >
        <div
          className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(var(--health-card-min-width),100%),1fr))]"
          ref={containerRef}
          onKeyDown={onContainerKeyDown}
        >
          {sorted.map((item, i) => (
            <HandlerHealthCard
              key={`${item.kind}-${item.id}`}
              item={item}
              appKey={appKey}
              instanceQs={instanceQs}
              tabIndex={getTabIndex(i)}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
