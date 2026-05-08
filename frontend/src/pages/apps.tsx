import { signal } from "@preact/signals";
import { useRef, useState } from "preact/hooks";
import { useDocumentTitle } from "../hooks/use-document-title";
import {
  getManifests,
  getDashboardAppGrid,
} from "../api/endpoints";
import { useScopedApi, PRESET_WINDOW_SECONDS } from "../hooks/use-scoped-api";
import { useApi } from "../hooks/use-api";
import { useAppState } from "../state/context";
import { statusToKind, statusToVariant, INACTIVE_STATUSES, type StatusKind } from "../utils/status";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../hooks/use-media-query";
import { formatRelativeTime, formatTimestamp } from "../utils/format";
import { type AppRow, type AppSortState, mergeManifestsAndGrid, compareAppRows } from "../utils/app-data";
import { StatusShape } from "../components/shared/status-shape";
import { MiniSparkline } from "../components/shared/mini-sparkline";
import { ActionButtons } from "../components/shared/action-buttons";
import { SortHeader } from "../components/shared/sort-header";
import { Spinner } from "../components/shared/spinner";

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

// ---- Stats strip ----

function StatsStrip({ apps, windowSeconds }: { apps: AppRow[]; windowSeconds: number | null }) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const counts = { total: apps.length, running: 0, failed: 0, stopped: 0, disabled: 0, blocked: 0 };
  let totalHandlers = 0;
  let totalRuns = 0;
  for (const a of apps) {
    const s = a.status as keyof typeof counts;
    if (s in counts && s !== "total") (counts as Record<string, number>)[s]++;
    totalHandlers += a.handler_count + a.job_count;
    totalRuns += a.total_invocations + a.total_executions;
  }
  const runsPerHour = windowSeconds && windowSeconds >= 60 ? totalRuns / (windowSeconds / 3600) : null;

  const cells: Array<{ label: string; value: number | string; tone?: StatusKind }> = [
    { label: "total", value: counts.total },
    { label: "running", value: counts.running, tone: "ok" },
    { label: "failed", value: counts.failed, tone: counts.failed > 0 ? "err" : undefined },
  ];

  if (isMobile) {
    cells.push({ label: "inactive", value: counts.stopped + counts.disabled });
  } else {
    cells.push({ label: "stopped", value: counts.stopped });
    cells.push({ label: "disabled", value: counts.disabled });
  }

  cells.push({ label: "handlers", value: totalHandlers });
  cells.push({ label: "runs / hr", value: runsPerHour !== null ? runsPerHour.toFixed(1) : "—" });

  return (
    <div class="ht-apps-stats" data-testid="apps-stats-strip">
      {cells.map((c) => (
        <div key={c.label} class="ht-apps-stats__cell">
          <span class="ht-apps-stats__label">{c.label}</span>
          <span class={`ht-apps-stats__value${c.tone ? ` ht-apps-stats__value--${c.tone}` : ""}`}>{c.value}</span>
        </div>
      ))}
    </div>
  );
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

// ---- Sort header ----



// ---- Table row ----

function AppTableRow({ app, liveStatus, isExpanded, onToggle }: {
  app: AppRow;
  liveStatus?: string;
  isExpanded: boolean;
  onToggle: () => void;
}) {
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
          {isMulti && (
            <button type="button" class="ht-apps-row__expand" onClick={onToggle} aria-expanded={isExpanded} aria-label={`${isExpanded ? "Collapse" : "Expand"} ${app.app_key}`}>
              {isExpanded ? "▾" : "▸"}
            </button>
          )}
          <StatusShape kind={kind} size={7} />
          <a href={`/apps/${app.app_key}`} class="ht-apps-row__app-name">{app.app_key}</a>
          <span class="ht-apps-row__class-name">{app.class_name}</span>
          {app.auto_loaded && <span class="ht-apps-row__auto-badge">auto</span>}
        </td>
        {/* Status */}
        <td>
          <span class={`ht-badge ht-badge--${statusToVariant(status)} ht-badge--sm`} data-testid="status-pill">{status}</span>
          {isMulti && <span class="ht-apps-row__instance-count">{app.instance_count} instances</span>}
        </td>
        {/* Error */}
        <td class="ht-apps-row__error-cell">
          {app.error_message ? (
            <span
              class="ht-text-mono ht-text-sm ht-text-danger"
              title={app.error_message}
            >
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
              <a href={`/apps/${app.app_key}/${inst.index}`} class="ht-text-mono ht-text-sm">{inst.instance_name}</a>
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

  const { appStatus, timePreset, uptimeSeconds } = useAppState();
  const { data: manifestData, loading: manifestLoading } = useApi(getManifests);
  const { data: gridData } = useScopedApi(
    (since) => getDashboardAppGrid(since),
  );

  const [filter, setFilter] = useState<FilterId>("all");
  const [sort, setSort] = useState<AppSortState>({ key: "status", dir: "asc" });
  const [search, setSearch] = useState("");
  const expanded = useRef(signal<Set<string>>(new Set())).current;

  const toggleExpand = (appKey: string) => {
    const next = new Set(expanded.value);
    if (next.has(appKey)) next.delete(appKey);
    else next.add(appKey);
    expanded.value = next;
  };

  const manifests = manifestData.value?.manifests ?? [];
  const gridEntries = gridData.value?.apps ?? [];
  const allApps = mergeManifestsAndGrid(manifests, gridEntries);

  const windowSeconds = uptimeSeconds.value !== null && uptimeSeconds.value !== undefined
    ? (timePreset.value === "since-restart" ? uptimeSeconds.value : PRESET_WINDOW_SECONDS[timePreset.value])
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

  if (manifestLoading.value && manifests.length === 0) return <Spinner />;

  return (
    <div class="ht-page ht-apps-page" data-testid="apps-page">
      {/* Header */}
      <div class="ht-page-header">
        <h1 class="ht-display">apps</h1>
      </div>

      {/* Stats strip */}
      <StatsStrip apps={allApps} windowSeconds={windowSeconds} />

      {/* Toolbar: filters + search */}
      <div class="ht-apps-toolbar">
        <FilterPills counts={statusCounts} active={filter} onChange={setFilter} />
        <input
          type="text"
          class="ht-apps-search"
          placeholder="search apps…"
          aria-label="Search apps"
          value={search}
          onInput={(e) => setSearch((e.target as HTMLInputElement).value)}
          data-testid="apps-search"
        />
      </div>

      {/* Table */}
      <div class="ht-card ht-apps-table-card">
        {filtered.length === 0 ? (
          <div class="ht-empty-state">
            <p class="ht-text-muted">no apps match this filter.</p>
            {(filter !== "all" || q) && (
              <button type="button" class="ht-btn ht-btn--ghost ht-btn--sm" onClick={() => { setFilter("all"); setSearch(""); }}>clear filters</button>
            )}
          </div>
        ) : (
          <table class="ht-table ht-apps-table">
            <thead>
              <tr>
                <SortHeader sort={sort} onSort={setSort} sortKey="name">app</SortHeader>
                <SortHeader sort={sort} onSort={setSort} sortKey="status">status</SortHeader>
                <SortHeader sort={sort} onSort={setSort} sortKey="error">last error</SortHeader>
                <SortHeader sort={sort} onSort={setSort} sortKey="runs">runs</SortHeader>
                <SortHeader sort={sort} onSort={setSort} sortKey="last">last fired</SortHeader>
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
      </div>
    </div>
  );
}
