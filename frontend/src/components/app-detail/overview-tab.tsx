import clsx from "clsx";
import { useMemo } from "preact/hooks";

import type { JobData, ListenerData } from "../../api/endpoints";
import { useSignal } from "../../hooks/use-signal";
import { useSubscribe } from "../../hooks/use-subscribe";
import { useAppState } from "../../state/context";
import { INACTIVE_STATUSES } from "../../utils/status";
import { EmptyState } from "../shared/empty-state";
import { LogTableView, LogTableWithDrawer, useLogTable } from "../shared/log-table";
import { TableCard } from "../shared/table-card";
import { TableFooter } from "../shared/table-footer";
import { ErrorSpotlight } from "./error-spotlight";
import { HandlerHealthGrid } from "./handler-health-grid";
import { buildItems } from "./handler-list";
import styles from "./overview-tab.module.css";
import { isFailing } from "./overview-tab-helpers";
import { RecentActivitySection } from "./recent-activity-section";

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  appKey: string;
  instanceQs: string;
  resolvedInstanceIndex: number;
  appStatus?: string;
}

function RecentLogsSection({ appKey, appStatus }: { appKey: string; appStatus?: string }) {
  const isInactive = appStatus !== undefined && INACTIVE_STATUSES.has(appStatus);
  const search = useSignal("");
  useSubscribe(search);
  const log = useLogTable({ context: "app", appKey, useLocalState: true, search: search.value });

  const emptyTitle = isInactive ? `this app is ${appStatus}` : "no log lines in window";
  const emptyBody = isInactive
    ? "no logs have been recorded for this app."
    : "nothing has been logged recently. change the level filter or extend the time window to see older lines.";

  const searchInput = (
    <input
      type="text"
      class="ht-search"
      placeholder="Search logs…"
      aria-label="Search app logs"
      value={search.value}
      onInput={(e) => {
        search.value = (e.target as HTMLInputElement).value;
      }}
      data-testid="overview-logs-search"
    />
  );

  const footer = (
    <TableFooter
      count={log.countLabel}
      columnFilters={log.columnFilters}
      onResetFilters={log.hasActiveFilter ? log.resetFilters : undefined}
    />
  );

  return (
    <section class={styles.section} data-testid="overview-logs-section">
      <h3 class="ht-section-label">logs</h3>
      <TableCard search={searchInput} footer={footer} scrollHeight="400px">
        <LogTableWithDrawer drawerProps={log.drawerProps}>
          {log.isEmpty ? <EmptyState title={emptyTitle} body={emptyBody} /> : <LogTableView {...log.tableProps} />}
        </LogTableWithDrawer>
      </TableCard>
    </section>
  );
}

export function OverviewTab({ listeners, jobs, appKey, instanceQs, resolvedInstanceIndex, appStatus }: Props) {
  const { connection } = useAppState();
  const wsConnected = connection.value === "connected";
  const allItems = useMemo(() => buildItems(listeners, jobs), [listeners, jobs]);
  const failingItems = useMemo(() => allItems.filter(isFailing), [allItems]);

  return (
    <div class={clsx(styles.overviewTab, !wsConnected && styles.overviewTabStale)} data-testid="overview-tab">
      {failingItems.length > 0 && (
        <ErrorSpotlight failingItems={failingItems} appKey={appKey} instanceQs={instanceQs} />
      )}

      <HandlerHealthGrid items={allItems} appKey={appKey} instanceQs={instanceQs} />

      <RecentActivitySection appKey={appKey} resolvedInstanceIndex={resolvedInstanceIndex} />

      <RecentLogsSection appKey={appKey} appStatus={appStatus} />
    </div>
  );
}
