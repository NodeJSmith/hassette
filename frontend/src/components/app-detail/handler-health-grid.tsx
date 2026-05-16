import { useMemo } from "preact/hooks";
import { EmptyState } from "../shared/empty-state";
import type { UnifiedItem } from "./unified-handler-row";
import { sortedByFailingFirst } from "./overview-tab-helpers";
import { HandlerHealthCard } from "./handler-health-card";
import styles from "./overview-tab.module.css";

export function HandlerHealthGrid({ items, appKey, instanceQs }: {
  items: UnifiedItem[];
  appKey: string;
  instanceQs: string;
}) {
  const sorted = useMemo(() => sortedByFailingFirst(items), [items]);

  if (items.length === 0) {
    return (
      <section class={styles.section} data-testid="overview-health-grid">
        <h3 class="ht-section-label">handler health</h3>
        <EmptyState
          title="No handlers registered"
          body="This app has not registered any event handlers or scheduled jobs."
          data-testid="overview-health-empty"
        />
      </section>
    );
  }

  return (
    <section class={styles.section} data-testid="overview-health-grid">
      <h3 class="ht-section-label">handler health</h3>
      <div class={styles.healthGridScroll}>
        <div class={styles.healthGrid}>
          {sorted.map((item) => (
            <HandlerHealthCard
              key={`${item.kind}-${item.id}`}
              item={item}
              appKey={appKey}
              instanceQs={instanceQs}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
