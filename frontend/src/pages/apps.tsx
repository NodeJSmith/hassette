import { keepPreviousData } from "@tanstack/react-query";
import clsx from "clsx";
import { useState } from "react";

import { ApiError } from "../api/client";
import { getDashboardAppGrid } from "../api/endpoints";
import { Button } from "../components/shared/button";
import popoverStyles from "../components/shared/column-filter-popover/index.module.css";
import { EmptyState } from "../components/shared/empty-state";
import { SortHeader } from "../components/shared/sort-header";
import { Spinner } from "../components/shared/spinner";
import { StatsStrip, type StatsStripCell } from "../components/shared/stats-strip";
import { StatusShape } from "../components/shared/status-shape";
import { TableCard } from "../components/shared/table-card";
import { TableFooter } from "../components/shared/table-footer";
import { type ColumnFilters } from "../components/shared/table-types";
import { useDocumentTitle } from "../hooks/use-document-title";
import { BREAKPOINT_MOBILE, useMediaQuery } from "../hooks/use-media-query";
import { useQueryInvalidator } from "../hooks/use-query-invalidator";
import { useQueryParams } from "../hooks/use-query-params";
import { useScopedQuery } from "../hooks/use-scoped-query";
import { queryKeys } from "../lib/query-keys";
import type { AppStatusEntry } from "../state/store";
import { useAppStore } from "../state/store";
import { appLiveStatus, type AppRow, type AppSortState, compareAppRows, toAppRow } from "../utils/app-data";
import { pluralize } from "../utils/format";
import { type StatusKind } from "../utils/status";
import { PRESET_WINDOW_SECONDS } from "../utils/time-window";
import styles from "./apps.module.css";
import { AppTableRow } from "./apps-table-row";

const FILTER_OPTIONS = ["all", "running", "failed", "stopped", "disabled", "blocked"] as const;
type FilterId = (typeof FILTER_OPTIONS)[number];

const FILTER_TONES: Record<FilterId, StatusKind | null> = {
  all: null,
  running: "ok",
  failed: "err",
  stopped: "mute",
  disabled: "mute",
  blocked: "warn",
};

const MIN_WINDOW_FOR_RATE_CALC = 60;
const VALID_SORT_KEYS: ReadonlySet<string> = new Set<AppSortState["key"]>(["name", "status", "error", "runs", "last"]);

function buildAppsCells(
  apps: AppRow[],
  appStatuses: Record<string, AppStatusEntry>,
  windowSeconds: number | null,
  isMobile: boolean,
): StatsStripCell[] {
  const statusCounts: Record<string, number> = { running: 0, failed: 0, stopped: 0, disabled: 0, blocked: 0 };
  let totalHandlers = 0;
  let totalRuns = 0;
  for (const a of apps) {
    const live = appLiveStatus(appStatuses, a);
    if (live in statusCounts) statusCounts[live]++;
    totalHandlers += a.handler_count + a.job_count;
    totalRuns += a.total_invocations + a.total_executions;
  }
  const runsPerHour =
    windowSeconds && windowSeconds >= MIN_WINDOW_FOR_RATE_CALC ? totalRuns / (windowSeconds / 3600) : null;

  const cells: StatsStripCell[] = [
    { label: "total", value: apps.length },
    { label: "running", value: statusCounts.running, tone: "ok" },
    { label: "failed", value: statusCounts.failed, tone: statusCounts.failed > 0 ? "err" : undefined },
  ];

  if (isMobile) {
    cells.push({ label: "inactive", value: statusCounts.stopped + statusCounts.disabled });
  } else {
    cells.push({ label: "stopped", value: statusCounts.stopped });
    cells.push({ label: "disabled", value: statusCounts.disabled });
  }

  cells.push({ label: "handlers", value: totalHandlers });
  cells.push({ label: "runs / hr", value: runsPerHour !== null ? runsPerHour.toFixed(1) : "—" });
  return cells;
}

function StatusFilterContent({
  counts,
  active,
  onChange,
}: {
  counts: Record<string, number>;
  active: FilterId;
  onChange: (filter: FilterId) => void;
}) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    <div className={styles.statusFilter}>
      {FILTER_OPTIONS.map((f) => {
        const count = f === "all" ? total : (counts[f] ?? 0);
        if (f !== "all" && count === 0) return null;
        const isActive = active === f;
        const tone = FILTER_TONES[f];
        return (
          <button
            key={f}
            type="button"
            className={clsx(popoverStyles.tierBtn, isActive && popoverStyles.active)}
            aria-pressed={isActive}
            onClick={() => onChange(f)}
            data-testid={`filter-${f}`}
          >
            <span className={styles.statusFilterRow}>
              {tone && <StatusShape kind={tone} size={8} />}
              <span>{f}</span>
              <span className={styles.statusFilterCount}>{count}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function AppsPage() {
  useDocumentTitle("Apps");

  const appStatus = useAppStore((s) => s.appStatus);
  const timePreset = useAppStore((s) => s.timePreset);
  const urlWindowParam = useAppStore((s) => s.urlWindowParam);
  const effectiveTimePreset = urlWindowParam ?? timePreset;
  const uptimeSeconds = useAppStore((s) => s.uptimeSeconds);
  const executionCompleted = useAppStore((s) => s.executionCompleted);
  const {
    data: gridData,
    error: gridError,
    isPending: gridLoading,
  } = useScopedQuery(queryKeys.dashboardGrid(), (since, signal) => getDashboardAppGrid(since, signal), {
    // The apps list must render even when HA/WS is unreachable (design/specs/018-dashboard-without-ha) —
    // don't block on uptimeSeconds like other scoped views. Falls back to an all-time window until
    // uptime arrives, then refetches with the accurate restart-relative window.
    waitForUptime: false,
    // Keep the table populated during that refetch instead of dropping to the full-page spinner.
    placeholderData: keepPreviousData,
  });

  useQueryInvalidator(executionCompleted, (events) => events !== null, queryKeys.dashboardGrid());

  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const qp = useQueryParams();
  const rawFilter = qp.get("filter");
  const filter: FilterId =
    rawFilter !== null && (FILTER_OPTIONS as readonly string[]).includes(rawFilter) ? (rawFilter as FilterId) : "all";
  const rawSort = qp.get("sort");
  const sort: AppSortState = {
    key: (rawSort !== null && VALID_SORT_KEYS.has(rawSort) ? rawSort : "status") as AppSortState["key"],
    dir: qp.get("dir") === "desc" ? "desc" : "asc",
  };
  const search = qp.get("search") ?? "";
  const handleSort = (newSort: AppSortState) =>
    qp.set({
      sort: newSort.key === "status" ? null : newSort.key,
      dir: newSort.dir === "asc" ? null : newSort.dir,
    });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggleExpand = (appKey: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(appKey)) next.delete(appKey);
      else next.add(appKey);
      return next;
    });
  };

  const allApps = (gridData?.apps ?? []).map(toAppRow);

  let windowSeconds: number | null = null;
  if (uptimeSeconds !== null) {
    windowSeconds =
      effectiveTimePreset === "since-restart" ? uptimeSeconds : PRESET_WINDOW_SECONDS[effectiveTimePreset];
  }

  const statusCounts: Record<string, number> = {};
  for (const a of allApps) {
    const liveStatus = appLiveStatus(appStatus, a);
    statusCounts[liveStatus] = (statusCounts[liveStatus] ?? 0) + 1;
  }

  const uniqueStatuses = Object.keys(statusCounts);
  const allSameStatus = uniqueStatuses.length === 1;

  const clearFilters = () => qp.set({ filter: null, search: null });

  const columnFilters: ColumnFilters = {
    status: {
      active: filter !== "all",
      label: "Status",
      content: (
        <StatusFilterContent
          counts={statusCounts}
          active={filter}
          onChange={(newFilter) => qp.set({ filter: newFilter === "all" ? null : newFilter })}
        />
      ),
    },
  };

  const searchLower = search.toLowerCase();
  const filtered = allApps
    .filter((a) => {
      const liveStatus = appLiveStatus(appStatus, a);
      if (filter !== "all" && liveStatus !== filter) return false;
      if (
        searchLower &&
        !a.app_key.toLowerCase().includes(searchLower) &&
        !a.class_name.toLowerCase().includes(searchLower) &&
        !a.display_name.toLowerCase().includes(searchLower)
      )
        return false;
      return true;
    })
    .sort((a, b) => compareAppRows(a, b, sort, appStatus));

  if (gridLoading) return <Spinner />;

  if (gridError) {
    const isUnavailable = gridError instanceof ApiError && gridError.status === 503;
    return (
      <div className="ht-alert ht-alert--danger" role="alert" data-testid="apps-load-error">
        {isUnavailable ? "Telemetry unavailable — the database is unreachable." : gridError.message}
      </div>
    );
  }

  const searchInput = (
    <input
      type="text"
      className="ht-search"
      placeholder="search apps…"
      aria-label="Search apps"
      value={search}
      onInput={(e) => qp.set({ search: (e.target as HTMLInputElement).value || null })}
      data-testid="apps-search"
    />
  );

  const footer = (
    <TableFooter
      count={pluralize(filtered.length, "app")}
      columnFilters={columnFilters}
      onResetFilters={clearFilters}
    />
  );

  let emptyStateTitle = "no apps match this filter.";
  if (filter !== "all") emptyStateTitle = `no apps match status: ${filter}.`;
  else if (search) emptyStateTitle = `no apps match "${search}".`;

  return (
    <div className={`ht-page ${styles.page}`} data-testid="apps-page">
      {/* Header */}
      <div className="ht-page-header">
        <h1 className="ht-display">apps</h1>
      </div>

      <div className="ht-table-section">
        <StatsStrip
          cells={buildAppsCells(allApps, appStatus, windowSeconds, isMobile)}
          data-testid="apps-stats-strip"
        />
        {searchInput}
        <TableCard footer={footer}>
          {filtered.length === 0 ? (
            <EmptyState title={emptyStateTitle}>
              {(filter !== "all" || search) && (
                <Button ghost size="sm" onClick={clearFilters}>
                  clear filters
                </Button>
              )}
            </EmptyState>
          ) : (
            <table className={`ht-table ht-table--fixed ${styles.appsTable}`} data-testid="apps-table">
              <colgroup>
                <col className={styles.colName} />
                <col className={styles.colStatus} />
                <col className={styles.colError} />
                <col className={styles.colRuns} />
                <col className={styles.colLast} />
                <col className={styles.colActions} />
              </colgroup>
              <thead>
                <tr>
                  <SortHeader sort={sort} onSort={handleSort} sortKey="name">
                    app
                  </SortHeader>
                  <SortHeader
                    sort={sort}
                    onSort={handleSort}
                    sortKey="status"
                    ariaLabel="status"
                    filterContent={columnFilters.status.content}
                    hasActiveFilter={columnFilters.status.active}
                  >
                    status
                  </SortHeader>
                  <SortHeader sort={sort} onSort={handleSort} sortKey="error">
                    last error
                  </SortHeader>
                  <SortHeader sort={sort} onSort={handleSort} sortKey="runs">
                    runs
                  </SortHeader>
                  <SortHeader sort={sort} onSort={handleSort} sortKey="last">
                    last fired
                  </SortHeader>
                  <th scope="col">actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((app) => (
                  <AppTableRow
                    key={app.app_key}
                    app={app}
                    appStatuses={appStatus}
                    isExpanded={app.instance_count > 1 && expanded.has(app.app_key)}
                    onToggle={() => toggleExpand(app.app_key)}
                    muteStatus={allSameStatus}
                  />
                ))}
              </tbody>
            </table>
          )}
        </TableCard>
      </div>
    </div>
  );
}
