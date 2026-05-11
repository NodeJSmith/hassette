import { signal } from "@preact/signals";
import { useRef, useState } from "preact/hooks";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useQueryParams } from "../hooks/use-query-params";
import { getDashboardAppGrid } from "../api/endpoints";
import { useScopedApi, PRESET_WINDOW_SECONDS } from "../hooks/use-scoped-api";
import { useAppState } from "../state/context";
import { statusToKind, statusToVariant, INACTIVE_STATUSES, type StatusKind } from "../utils/status";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../hooks/use-media-query";
import { formatRelativeTime, formatTimestamp, pluralize } from "../utils/format";
import { type AppRow, type AppSortState, mergeManifestsAndGrid, compareAppRows } from "../utils/app-data";
import { AppLink } from "../components/shared/app-link";
import { EmptyState } from "../components/shared/empty-state";
import { StatusShape } from "../components/shared/status-shape";
import { MiniSparkline } from "../components/shared/mini-sparkline";
import { ActionButtons } from "../components/shared/action-buttons";
import { SortHeader } from "../components/shared/sort-header";
import { Spinner } from "../components/shared/spinner";
import { StatsStrip, type StatsStripCell } from "../components/shared/stats-strip";
import { TableCard } from "../components/shared/table-card";

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

// ---- Filter pills ----

function FilterPills({ counts, active, onChange }: {
  counts: Record<string, number>;
  active: FilterId;
  onChange: (f: FilterId) => void;
}) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    <div class="ht-apps-filters" role="group" aria-label="Filter by status" data-testid="apps-filter-pills">
      {FILTER_OPTIONS.map((f) => {
        const count = f === "all" ? total : (counts[f] ?? 0);
        if (f !== "all" && count === 0) return null;
        const isActive = active === f;
        const tone = FILTER_TONES[f];
        return (
          <button
            key={f}
            type="button"
            class={`ht-apps-filter-pill${isActive ? " ht-apps-filter-pill--active" : ""}`}
            aria-pressed={isActive}
            onClick={() => onChange(f)}
            data-testid={`filter-${f}`}
          >
            {tone && <StatusShape kind={tone} size={7} />}
            <span>{f}</span>
            <span class="ht-apps-filter-pill__count">{count}</span>
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
  const status = liveStatus ?? app.status;
  const kind = statusToKind(status);
  const isMulti = app.instance_count > 1;
  const isDimmed = INACTIVE_STATUSES.has(status);
  const totalRuns = app.total_invocations + app.total_executions;

  return (
    <>
      <tr
        class={`ht-apps-row${isDimmed ? " ht-apps-row--dimmed" : ""}`}
        data-testid={`app-row-${app.app_key}`}
      >
        {/* Name */}
        <td class="ht-apps-row__name-cell">
          <span class="ht-apps-row__expand-gutter">
            {isMulti && (
              <button type="button" class="ht-apps-row__expand" onClick={onToggle} aria-expanded={isExpanded} aria-label={`${isExpanded ? "Collapse" : "Expand"} ${app.app_key}`}>
                <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                  <polyline points={isExpanded ? "2,4 6,8 10,4" : "4,2 8,6 4,10"} fill="none" stroke="currentColor" stroke-width="1.5" />
                </svg>
              </button>
            )}
          </span>
          <StatusShape kind={kind} size={7} />
          <AppLink appKey={app.app_key} />
          <span class="ht-apps-row__class-name">{app.class_name}</span>
          {app.auto_loaded && <span class="ht-chip ht-chip--auto">auto</span>}
        </td>
        {/* Status */}
        <td>
          <span class={`ht-badge ht-badge--${statusToVariant(status)} ht-badge--sm`} data-testid="status-pill">{status}</span>
          {isMulti && <span class="ht-apps-row__instance-count">{app.instance_count} instances</span>}
        </td>
        {/* Error */}
        <td
          class={`ht-apps-row__error-cell${errorExpanded ? " is-expanded" : ""}`}
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
                <span class="ht-apps-row__error-age"> · {formatRelativeTime(app.last_error_ts)}</span>
              )}
            </span>
          ) : "—"}
        </td>
        {/* Runs + sparkline */}
        <td class="ht-apps-row__runs-cell">
          <span class="ht-text-mono">{totalRuns}</span>
          <MiniSparkline buckets={app.activity_buckets} />
        </td>
        {/* Last fired */}
        <td class="ht-text-mono ht-text-muted ht-text-sm">
          {app.last_activity_ts ? (
            <span title={formatTimestamp(app.last_activity_ts)}>{formatRelativeTime(app.last_activity_ts)}</span>
          ) : "—"}
        </td>
        {/* Actions */}
        <td class="ht-apps-row__actions-cell">
          <ActionButtons appKey={app.app_key} status={status} />
        </td>
      </tr>
      {isMulti && isExpanded && app.instances?.map((inst) => {
        const instStatus = liveStatus ?? inst.status;
        const instKind = statusToKind(instStatus);
        return (
          <tr key={`${app.app_key}-${inst.index}`} class="ht-apps-row ht-apps-row--instance" data-testid={`instance-row-${app.app_key}-${inst.index}`}>
            <td class="ht-apps-row__name-cell">
              <span class="ht-apps-row__instance-corner">└</span>
              <StatusShape kind={instKind} size={6} />
              <AppLink appKey={app.app_key} instanceIndex={inst.index}>{inst.instance_name}</AppLink>
            </td>
            <td><span class={`ht-badge ht-badge--${statusToVariant(instStatus)} ht-badge--sm`}>{instStatus}</span></td>
            <td class="ht-apps-row__error-cell">
              {inst.error_message ? (
                <span class="ht-text-mono ht-text-sm ht-text-danger" title={inst.error_message}>{inst.error_message}</span>
              ) : "—"}
            </td>
            <td />
            <td />
            <td class="ht-apps-row__actions-cell">
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

  const { appStatus, effectiveTimePreset, uptimeSeconds, manifests: manifestsState, manifestsLoading } = useAppState();
  const { data: gridData } = useScopedApi(
    (since) => getDashboardAppGrid(since),
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

  return (
    <div class="ht-page ht-apps-page" data-testid="apps-page">
      {/* Header */}
      <div class="ht-page-header">
        <h1 class="ht-display">apps</h1>
      </div>

      {/* Stats strip */}
      <StatsStrip cells={buildAppsCells(allApps, windowSeconds, isMobile)} data-testid="apps-stats-strip" />

      <TableCard
        count={pluralize(filtered.length, "app")}
        controls={<>
          <FilterPills counts={statusCounts} active={filter} onChange={(newFilter) => qp.set({ filter: newFilter === "all" ? null : newFilter })} />
          <input
            type="text"
            class="ht-search"
            placeholder="search apps…"
            aria-label="Search apps"
            value={search}
            onInput={(e) => qp.set({ search: (e.target as HTMLInputElement).value || null })}
            data-testid="apps-search"
          />
        </>}
      >
        {filtered.length === 0 ? (
          <EmptyState title="no apps match this filter.">
            {(filter !== "all" || q) && (
              <button type="button" class="ht-btn ht-btn--ghost ht-btn--sm" onClick={() => qp.set({ filter: null, search: null })}>clear filters</button>
            )}
          </EmptyState>
        ) : (
          <table class="ht-table ht-apps-table">
            <thead>
              <tr>
                <SortHeader sort={sort} onSort={handleSort} sortKey="name">app</SortHeader>
                <SortHeader sort={sort} onSort={handleSort} sortKey="status">status</SortHeader>
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
