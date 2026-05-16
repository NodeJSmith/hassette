import { useMemo } from "preact/hooks";
import { Link, useLocation } from "wouter";
import clsx from "clsx";
import { StatusShape } from "../shared/status-shape";
import { Chip } from "../shared/chip";
import { EmptyState } from "../shared/empty-state";
import { pluralize } from "../../utils/format";
import type { UnifiedItem } from "./unified-handler-row";
import {
  handlerPath,
  isFailing,
  itemRunCount,
  sortedByFailingFirst,
  itemKindChip,
  itemErrorType,
} from "./overview-tab-helpers";
import styles from "./overview-tab.module.css";

function HealthGridRow({ item, appKey, instanceQs }: {
  item: UnifiedItem;
  appKey: string;
  instanceQs: string;
}) {
  const [, navigate] = useLocation();
  const href = handlerPath(appKey, item, instanceQs);
  const callLabel = item.kind === "listener" ? "call" : "run";
  const runCount = itemRunCount(item);
  const chipLabel = itemKindChip(item);
  const errorType = isFailing(item) ? itemErrorType(item) : null;

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
      <td>
        <StatusShape kind={item.statusKind} size={10} />
      </td>
      <td>
        <Chip variant="muted" size="sm" aria-label={`kind: ${chipLabel}`}>
          {chipLabel}
        </Chip>
      </td>
      <td class={styles.healthRowName}>
        <Link href={href} class={styles.healthRowLink} onClick={(e: MouseEvent) => e.stopPropagation()}>
          {item.name}
        </Link>
      </td>
      <td class={styles.healthRowCount}>
        {pluralize(runCount, callLabel)}
      </td>
      <td class={clsx(styles.healthRowError, "ht-text-danger ht-text-sm")}>
        {errorType}
      </td>
    </tr>
  );
}

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
      <table class={clsx("ht-table", styles.healthTable)}>
        <thead>
          <tr>
            <th class={styles.colDot} scope="col"></th>
            <th scope="col">Kind</th>
            <th scope="col">Handler</th>
            <th class={styles.healthRowCount} scope="col">Runs</th>
            <th scope="col"></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((item) => (
            <HealthGridRow
              key={`${item.kind}-${item.id}`}
              item={item}
              appKey={appKey}
              instanceQs={instanceQs}
            />
          ))}
        </tbody>
      </table>
    </section>
  );
}
