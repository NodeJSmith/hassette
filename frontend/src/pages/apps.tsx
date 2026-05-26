import clsx from "clsx";

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
import { useManifests } from "../hooks/use-manifests";
import { BREAKPOINT_MOBILE, useMediaQuery } from "../hooks/use-media-query";
import { useQueryInvalidator } from "../hooks/use-query-invalidator";
import { useQueryParams } from "../hooks/use-query-params";
import { useScopedQuery } from "../hooks/use-scoped-query";
import { useSignal } from "../hooks/use-signal";
import { queryKeys } from "../lib/query-keys";
import { useAppState } from "../state/context";
import { type AppRow, type AppSortState, compareAppRows, mergeManifestsAndGrid } from "../utils/app-data";
import { pluralize } from "../utils/format";
import { type StatusKind } from "../utils/status";
import { PRESET_WINDOW_SECONDS } from "../utils/time-window";
import styles from "./apps.module.css";
import { AppTableRow } from "./apps-table-row";

// ---- Filter types ----

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

// ---- Stats strip helpers ----

function buildAppsCells(apps: AppRow[], windowSeconds: number | null, isMobile: boolean): StatsStripCell[] {
  const statusCounts: Record<string, number> = { running: 0, failed: 0, stopped: 0, disabled: 0, blocked: 0 };
  let totalHandlers = 0;
  let totalRuns = 0;
  for (const a of apps) {
    if (a.status in statusCounts) statusCounts[a.status]++;
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

// ---- Status filter popover content ----

function StatusFilterContent({
  counts,
  active,
  onChange,
}: {
  counts: Record<string, number>;
  active: FilterId;
  onChange: (f: FilterId) => void;
}) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    <div class={styles.statusFilter}>
      {FILTER_OPTIONS.map((f) => {
        const count = f === "all" ? total : (counts[f] ?? 0);
        if (f !== "all" && count === 0) return null;
        const isActive = active === f;
        const tone = FILTER_TONES[f];
        return (
          <button
            key={f}
            type="button"
            class={clsx(popoverStyles.tierBtn, isActive && popoverStyles.active)}
            aria-pressed={isActive}
            onClick={() => onChange(f)}
            data-testid={`filter-${f}`}
          >
            <span class={styles.statusFilterRow}>
              {tone && <StatusShape kind={tone} size={8} />}
              <span>{f}</span>
              <span class={styles.statusFilterCount}>{count}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ---- Page ----

export function AppsPage() {
  useDocumentTitle("Apps");

  const { appStatus, effectiveTimePreset, uptimeSeconds, invocationCompleted, executionCompleted } = useAppState();
  const { data: manifests = [], isPending: manifestsLoading } = useManifests();
  const { data: gridData, error: gridError } = useScopedQuery(queryKeys.dashboardGrid(), (since, signal) =>
    getDashboardAppGrid(since, signal),
  );

  useQueryInvalidator(
    [
      [invocationCompleted, (events) => events !== null],
      [executionCompleted, (events) => events !== null],
    ],
    queryKeys.dashboardGrid(),
  );

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
  const expanded = useSignal<Set<string>>(new Set());

  const toggleExpand = (appKey: string) => {
    const next = new Set(expanded.value);
    if (next.has(appKey)) next.delete(appKey);
    else next.add(appKey);
    expanded.value = next;
  };

  const gridEntries = gridData?.apps ?? [];
  const allApps = mergeManifestsAndGrid(manifests, gridEntries);

  let windowSeconds: number | null = null;
  if (uptimeSeconds.value !== null) {
    windowSeconds =
      effectiveTimePreset.value === "since-restart"
        ? uptimeSeconds.value
        : PRESET_WINDOW_SECONDS[effectiveTimePreset.value];
  }

  const statusCounts: Record<string, number> = {};
  for (const a of allApps) {
    const s = appStatus.value[a.app_key]?.status ?? a.status;
    statusCounts[s] = (statusCounts[s] ?? 0) + 1;
  }

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

  const q = search.toLowerCase();
  const filtered = allApps
    .filter((a) => {
      const s = appStatus.value[a.app_key]?.status ?? a.status;
      if (filter !== "all" && s !== filter) return false;
      if (
        q &&
        !a.app_key.toLowerCase().includes(q) &&
        !a.class_name.toLowerCase().includes(q) &&
        !a.display_name.toLowerCase().includes(q)
      )
        return false;
      return true;
    })
    .sort((a, b) => compareAppRows(a, b, sort, appStatus.value));

  if (manifestsLoading && manifests.length === 0) return <Spinner />;

  if (gridError) {
    return (
      <div class="ht-alert ht-alert--danger" role="alert">
        {gridError.message}
      </div>
    );
  }

  const searchInput = (
    <input
      type="text"
      class="ht-search"
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
  else if (q) emptyStateTitle = `no apps match "${q}".`;

  return (
    <div class={`ht-page ${styles.page}`} data-testid="apps-page">
      {/* Header */}
      <div class="ht-page-header">
        <h1 class="ht-display">apps</h1>
      </div>

      {/* Stats strip */}
      <StatsStrip cells={buildAppsCells(allApps, windowSeconds, isMobile)} data-testid="apps-stats-strip" />

      {searchInput}
      <TableCard footer={footer}>
        {filtered.length === 0 ? (
          <EmptyState title={emptyStateTitle}>
            {(filter !== "all" || q) && (
              <Button ghost size="sm" onClick={clearFilters}>
                clear filters
              </Button>
            )}
          </EmptyState>
        ) : (
          <table class={`ht-table ht-table--fixed ${styles.appsTable}`} data-testid="apps-table">
            <colgroup>
              <col style="width: 35%" />
              <col style="width: 12%" />
              <col style="width: 22%" />
              <col style="width: 10%" />
              <col style="width: 11%" />
              <col style="width: 10%" />
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
                  liveStatus={appStatus.value[app.app_key]?.status}
                  isExpanded={app.instance_count > 1 && expanded.value.has(app.app_key)}
                  onToggle={() => toggleExpand(app.app_key)}
                />
              ))}
            </tbody>
          </table>
        )}
      </TableCard>
    </div>
  );
}
