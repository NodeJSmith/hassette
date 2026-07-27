import { useMemo } from "react";

import { useRovingTabIndex } from "../../hooks/use-roving-tab-index";
import { EmptyState } from "../shared/empty-state";
import { HandlerHealthCard } from "./handler-health-card";
// Grid layout classes live in overview-tab's stylesheet — this component is only rendered within OverviewTab
import styles from "./overview-tab.module.css";
import { sortedByFailingFirst } from "./overview-tab-helpers";
import type { UnifiedItem } from "./unified-handler-row";

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
      <section className={styles.section} data-testid="overview-health-grid">
        <h3 className="ht-section-label">handler health</h3>
        <EmptyState
          title="No handlers registered"
          body="This app has not registered any event handlers or scheduled jobs."
          data-testid="overview-health-empty"
        />
      </section>
    );
  }

  return (
    <section className={styles.section} data-testid="overview-health-grid">
      <h3 className="ht-section-label">handler health</h3>
      <div className={styles.healthGridScroll}>
        <div className={styles.healthGrid} ref={containerRef} onKeyDown={onContainerKeyDown}>
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
