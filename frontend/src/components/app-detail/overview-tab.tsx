import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";

import type { JobData, ListenerData } from "../../api/endpoints";
import type { components } from "../../api/generated-types";
import { useAppStore } from "../../state/store";
import { INACTIVE_STATUSES } from "../../utils/status";
import { EmptyState } from "../shared/empty-state";
import { LogTableView, LogTableWithDrawer, useLogTable } from "../shared/log-table";
import { TableCard } from "../shared/table-card";
import { TableFooter } from "../shared/table-footer";
import { ErrorSpotlight } from "./error-spotlight";
import { HandlerHealthGrid } from "./handler-health-grid";
import { buildItems } from "./handler-list";
import { OverviewHealthStrip } from "./health-strip";
import { OVERVIEW_SECTION_CLASS } from "./overview-section";
import { isFailing } from "./overview-tab-helpers";
import { RecentActivitySection } from "./recent-activity-section";

type ManifestStatus = components["schemas"]["ManifestStatus"];
type ResourceStatus = components["schemas"]["ResourceStatus"];

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  appKey: string;
  instanceQs: string;
  resolvedInstanceIndex: number;
  appStatus?: ManifestStatus | ResourceStatus | "unknown";
}

const SEARCH_INPUT_CLASS =
  "min-w-[var(--size-search-min)] rounded-md border border-[var(--border-strong)] bg-input px-2 py-1.5 font-sans text-[length:var(--text-mono-sm)] text-foreground outline-none placeholder:text-foreground-faint focus-visible:border-primary focus-visible:shadow-[0_0_0_2px_var(--primary-soft)] max-mobile:w-full max-mobile:min-w-0";
const SECTION_LABEL_CLASS = "mb-2 font-sans text-[length:var(--text-h3)] font-semibold text-foreground";

function RecentLogsSection({
  appKey,
  appStatus,
}: {
  appKey: string;
  appStatus?: ManifestStatus | ResourceStatus | "unknown";
}) {
  const isInactive = appStatus !== undefined && INACTIVE_STATUSES.has(appStatus);
  const [search, setSearch] = useState("");
  const log = useLogTable({ context: "app", appKey, useLocalState: true, search });

  const emptyTitle = isInactive ? `this app is ${appStatus}` : "no log lines in window";
  const emptyBody = isInactive
    ? "no logs have been recorded for this app."
    : "nothing has been logged recently. change the level filter or extend the time window to see older lines.";

  const searchInput = (
    <input
      type="text"
      className={SEARCH_INPUT_CLASS}
      placeholder="Search logs…"
      aria-label="Search app logs"
      value={search}
      onInput={(e) => {
        setSearch((e.target as HTMLInputElement).value);
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
    <section className={OVERVIEW_SECTION_CLASS} data-testid="overview-logs-section">
      <div className="flex items-baseline justify-between gap-4">
        <h3 className={SECTION_LABEL_CLASS}>logs</h3>
        {searchInput}
      </div>
      <TableCard footer={footer} scrollHeight="400px">
        <LogTableWithDrawer drawerProps={log.drawerProps}>
          {log.isEmpty ? <EmptyState title={emptyTitle} body={emptyBody} /> : <LogTableView {...log.tableProps} />}
        </LogTableWithDrawer>
      </TableCard>
    </section>
  );
}

export function OverviewTab({ listeners, jobs, appKey, instanceQs, resolvedInstanceIndex, appStatus }: Props) {
  const connection = useAppStore((s) => s.connection);
  const wsConnected = connection === "connected";
  const allItems = useMemo(() => buildItems(listeners, jobs), [listeners, jobs]);
  const failingItems = useMemo(() => allItems.filter(isFailing), [allItems]);

  return (
    <div className={cn("flex flex-col gap-7", !wsConnected && "opacity-[var(--op-muted)]")} data-testid="overview-tab">
      <OverviewHealthStrip listeners={listeners} jobs={jobs} />

      {failingItems.length > 0 && (
        <ErrorSpotlight failingItems={failingItems} appKey={appKey} instanceQs={instanceQs} />
      )}

      <HandlerHealthGrid items={allItems} appKey={appKey} instanceQs={instanceQs} />

      <RecentActivitySection appKey={appKey} resolvedInstanceIndex={resolvedInstanceIndex} />

      <RecentLogsSection appKey={appKey} appStatus={appStatus} />
    </div>
  );
}
