import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import clsx from "clsx";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useQueryParams } from "../hooks/use-query-params";
import { getDashboardAppGrid } from "../api/endpoints";
import { useScopedApi, PRESET_WINDOW_SECONDS } from "../hooks/use-scoped-api";
import { useFilteredSignalRefetch, WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS } from "../hooks/use-filtered-signal-refetch";
import { useAppState } from "../state/context";
import { statusToKind, statusToVariant, INACTIVE_STATUSES, type StatusKind } from "../utils/status";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../hooks/use-media-query";
import { formatTimestamp, pluralize } from "../utils/format";
import { useRelativeTime } from "../hooks/use-relative-time";
import { useState } from "preact/hooks";
import { type AppRow, type AppSortState, mergeManifestsAndGrid, compareAppRows } from "../utils/app-data";
import { AppLink } from "../components/shared/app-link";
import { EmptyState } from "../components/shared/empty-state";
import { StatusShape } from "../components/shared/status-shape";
import { Badge } from "../components/shared/badge";
import { Button } from "../components/shared/button";
import { Chip } from "../components/shared/chip";
import { MiniSparkline } from "../components/shared/mini-sparkline";
import { ActionButtons } from "../components/shared/action-buttons";
import { SortHeader } from "../components/shared/sort-header";
import { Spinner } from "../components/shared/spinner";
import { StatsStrip, type StatsStripCell } from "../components/shared/stats-strip";
import { TableCard } from "../components/shared/table-card";
import { TableFooter } from "../components/shared/table-footer";
import { type ColumnFilters } from "../components/shared/table-types";
import popoverStyles from "../components/shared/column-filter-popover/index.module.css";
import styles from "./apps.module.css";

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
  const runsPerHour = windowSeconds && windowSeconds >= 60 ? totalRuns / (windowSeconds / 3600) : null;

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

function StatusFilterContent({ counts, active, onChange }: {
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

// ---- Table row ----

function AppTableRow({ app, liveStatus, isExpanded, onToggle }: {
  app: AppRow;
  liveStatus?: string;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const [errorExpanded, setErrorExpanded] = useState(false);
  if (!app.error_message && errorExpanded) setErrorExpanded(false);
  const lastErrorLabel = useRelativeTime(app.last_error_ts ?? null);
  const lastActivityLabel = useRelativeTime(app.last_activity_ts ?? null);
  const status = liveStatus ?? app.status;
  const kind = statusToKind(status);
  const isMulti = app.instance_count > 1;
  const isDimmed = INACTIVE_STATUSES.has(status);
  const totalRuns = app.total_invocations + app.total_executions;

  return (
    <>
      <tr
        class={clsx(styles.row, isDimmed && styles.rowDimmed)}
        data-testid={`app-row-${app.app_key}`}
      >
        {/* Name */}
        <td class={styles.nameCell}>
          <div class={styles.nameCellInner}>
            <span class={styles.expandGutter}>
              {isMulti && (
                <button type="button" class={styles.expand} onClick={onToggle} aria-expanded={isExpanded} aria-label={`${isExpanded ? "Collapse" : "Expand"} ${app.app_key}`} data-testid="app-row-expand">
                  <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                    <polyline points={isExpanded ? "2,4 6,8 10,4" : "4,2 8,6 4,10"} fill="none" stroke="currentColor" stroke-width="1.5" />
                  </svg>
                </button>
              )}
            </span>
            <StatusShape kind={kind} size={7} />
            <AppLink appKey={app.app_key} />
            <span class={styles.className}>{app.class_name}</span>
            {app.auto_loaded && <Chip variant="muted">auto</Chip>}
          </div>
        </td>
        {/* Status */}
        <td>
          <Badge variant={statusToVariant(status)} size="sm" data-testid="status-pill">{status}</Badge>
          {isMulti && <span class={styles.instanceCount}>{app.instance_count} instances</span>}
        </td>
        {/* Error */}
        <td
          class={clsx(styles.errorCell, errorExpanded && styles.errorCellExpanded)}
          {...(app.error_message ? {
            role: "button", tabIndex: 0,
            "aria-label": `${errorExpanded ? "Collapse" : "Expand"} error: ${app.error_message}`,
            onClick: (e: Event) => { e.stopPropagation(); setErrorExpanded(!errorExpanded); },
            onKeyDown: (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setErrorExpanded(!errorExpanded); } },
          } : {})}
        >
          {app.error_message ? (
            <span class="ht-text-mono ht-text-sm ht-text-danger">
              {app.error_message}
              {app.last_error_ts && (
                <span class={styles.errorAge}> · {lastErrorLabel}</span>
              )}
            </span>
          ) : "—"}
        </td>
        {/* Runs + sparkline */}
        <td class={styles.runsCell}>
          <div class={styles.runsCellInner}>
            <MiniSparkline buckets={app.activity_buckets} height={16} />
            <span class="ht-text-mono">{totalRuns}</span>
          </div>
        </td>
        {/* Last fired */}
        <td class="ht-text-mono ht-text-muted ht-text-sm">
          {app.last_activity_ts ? (
            <span title={formatTimestamp(app.last_activity_ts)}>{lastActivityLabel}</span>
          ) : "—"}
        </td>
        {/* Actions */}
        <td class={styles.actionsCell}>
          <ActionButtons appKey={app.app_key} status={status} />
        </td>
      </tr>
      {isMulti && isExpanded && app.instances?.map((inst) => {
        const instStatus = liveStatus ?? inst.status;
        const instKind = statusToKind(instStatus);
        return (
          <tr key={`${app.app_key}-${inst.index}`} class={clsx(styles.row, styles.rowInstance)} data-testid={`instance-row-${app.app_key}-${inst.index}`}>
            <td class={styles.nameCell}>
              <div class={styles.nameCellInner}>
                <span class={styles.instanceCorner}>└</span>
                <StatusShape kind={instKind} size={6} />
                <AppLink appKey={app.app_key} instanceIndex={inst.index}>{inst.instance_name}</AppLink>
              </div>
            </td>
            <td><Badge variant={statusToVariant(instStatus)} size="sm">{instStatus}</Badge></td>
            <td class={styles.errorCell}>
              {inst.error_message ? (
                <span class="ht-text-mono ht-text-sm ht-text-danger" title={inst.error_message}>{inst.error_message}</span>
              ) : "—"}
            </td>
            <td />
            <td />
            <td class={styles.actionsCell}>
              <ActionButtons appKey={app.app_key} status={instStatus} />
            </td>
          </tr>
        );
      })}
    </>
  );
}

// ---- Page ----

export function AppsPage() {
  useDocumentTitle("Apps");

  const { appStatus, effectiveTimePreset, uptimeSeconds, manifests: manifestsState, manifestsLoading, invocationCompleted, executionCompleted } = useAppState();
  const { data: gridData, refetch: gridRefetch } = useScopedApi(
    (since) => getDashboardAppGrid(since),
  );

  useFilteredSignalRefetch(
    invocationCompleted,
    (events) => events !== null,
    () => void gridRefetch(),
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  useFilteredSignalRefetch(
    executionCompleted,
    (events) => events !== null,
    () => void gridRefetch(),
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const qp = useQueryParams();
  const rawFilter = qp.get("filter");
  const filter: FilterId = rawFilter !== null && (FILTER_OPTIONS as readonly string[]).includes(rawFilter)
    ? rawFilter as FilterId : "all";
  const rawSort = qp.get("sort");
  const rawDir = qp.get("dir");
  const sort: AppSortState = {
    key: rawSort !== null && ["name", "status", "error", "runs", "last"].includes(rawSort)
      ? rawSort as AppSortState["key"] : "status",
    dir: rawDir === "desc" ? "desc" : "asc",
  };
  const search = qp.get("search") ?? "";
  const handleSort = (newSort: AppSortState) =>
    qp.set({
      sort: newSort.key === "status" ? null : newSort.key,
      dir: newSort.dir === "asc" ? null : newSort.dir,
    });
  const expanded = useRef(signal<Set<string>>(new Set())).current;

  const toggleExpand = (appKey: string) => {
    const next = new Set(expanded.value);
    if (next.has(appKey)) next.delete(appKey);
    else next.add(appKey);
    expanded.value = next;
  };

  const manifests = manifestsState.value;
  const gridEntries = gridData.value?.apps ?? [];
  const allApps = mergeManifestsAndGrid(manifests, gridEntries);

  const windowSeconds = uptimeSeconds.value !== null && uptimeSeconds.value !== undefined
    ? (effectiveTimePreset.value === "since-restart" ? uptimeSeconds.value : PRESET_WINDOW_SECONDS[effectiveTimePreset.value])
    : null;

  // Status counts from all apps (unfiltered)
  const statusCounts: Record<string, number> = {};
  for (const a of allApps) {
    const s = appStatus.value[a.app_key]?.status ?? a.status;
    statusCounts[s] = (statusCounts[s] ?? 0) + 1;
  }

  const clearFilters = () => qp.set({ filter: null, search: null });

  // Column filters map — single source for desktop popovers and mobile panel
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

  // Filter + search + sort
  const q = search.toLowerCase();
  const filtered = allApps
    .filter((a) => {
      const s = appStatus.value[a.app_key]?.status ?? a.status;
      if (filter !== "all" && s !== filter) return false;
      if (q && !a.app_key.toLowerCase().includes(q) && !a.class_name.toLowerCase().includes(q) && !a.display_name.toLowerCase().includes(q)) return false;
      return true;
    })
    .sort((a, b) => compareAppRows(a, b, sort, appStatus.value));

  if (manifestsLoading.value && manifests.length === 0) return <Spinner />;

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

  // Build empty state message that names the active filter
  const emptyStateTitle = filter !== "all"
    ? `no apps match status: ${filter}.`
    : q
      ? `no apps match "${q}".`
      : "no apps match this filter.";

  return (
    <div class={`ht-page ${styles.page}`} data-testid="apps-page">
      {/* Header */}
      <div class="ht-page-header">
        <h1 class="ht-display">apps</h1>
      </div>

      {/* Stats strip */}
      <StatsStrip cells={buildAppsCells(allApps, windowSeconds, isMobile)} data-testid="apps-stats-strip" />

      <TableCard search={searchInput} footer={footer}>
        {filtered.length === 0 ? (
          <EmptyState title={emptyStateTitle}>
            {(filter !== "all" || q) && (
              <Button ghost size="sm" onClick={clearFilters}>clear filters</Button>
            )}
          </EmptyState>
        ) : (
          <table class={`ht-table ${styles.appsTable}`} data-testid="apps-table">
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
                <SortHeader sort={sort} onSort={handleSort} sortKey="name">app</SortHeader>
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
                <SortHeader sort={sort} onSort={handleSort} sortKey="error">last error</SortHeader>
                <SortHeader sort={sort} onSort={handleSort} sortKey="runs">runs</SortHeader>
                <SortHeader sort={sort} onSort={handleSort} sortKey="last">last fired</SortHeader>
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
