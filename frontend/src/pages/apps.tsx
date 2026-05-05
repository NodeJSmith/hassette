import { signal } from "@preact/signals";
import { useEffect, useRef, useState } from "preact/hooks";
import {
  getManifests,
  getDashboardAppGrid,
  type AppManifest,
  type DashboardAppGridEntry,
} from "../api/endpoints";
import { useScopedApi } from "../hooks/use-scoped-api";
import { useApi } from "../hooks/use-api";
import { useAppState } from "../state/context";
import { statusToKind, INACTIVE_STATUSES, type StatusKind } from "../utils/status";
import { formatRelativeTime, formatTimestamp } from "../utils/format";
import { StatusShape } from "../components/shared/status-shape";
import { ActionButtons } from "../components/apps/action-buttons";
import { Spinner } from "../components/shared/spinner";

// ---- Merged app row type ----

interface AppRow {
  app_key: string;
  class_name: string;
  display_name: string;
  filename: string;
  status: string;
  block_reason: string | null;
  enabled: boolean;
  auto_loaded: boolean;
  instance_count: number;
  instances: AppManifest["instances"];
  error_message: string | null;
  handler_count: number;
  job_count: number;
  total_invocations: number;
  total_executions: number;
  total_errors: number;
  total_timed_out: number;
  total_job_errors: number;
  total_job_timed_out: number;
  error_rate: number;
  last_activity_ts: number | null;
  activity_buckets: Array<{ ok: number; err: number }>;
  last_error_message: string | null;
  last_error_type: string | null;
  last_error_ts: number | null;
}

function mergeData(
  manifests: AppManifest[],
  gridEntries: DashboardAppGridEntry[],
): AppRow[] {
  const gridMap = new Map(gridEntries.map((e) => [e.app_key, e]));
  return manifests.map((m) => {
    const g = gridMap.get(m.app_key);
    return {
      app_key: m.app_key,
      class_name: m.class_name,
      display_name: m.display_name,
      filename: m.filename,
      status: m.status,
      block_reason: m.block_reason ?? null,
      enabled: m.enabled,
      auto_loaded: m.auto_loaded,
      instance_count: m.instance_count,
      instances: m.instances,
      error_message: g?.last_error_message ?? m.error_message ?? null,
      last_error_message: g?.last_error_message ?? null,
      last_error_type: g?.last_error_type ?? null,
      last_error_ts: g?.last_error_ts ?? null,
      handler_count: g?.handler_count ?? 0,
      job_count: g?.job_count ?? 0,
      total_invocations: g?.total_invocations ?? 0,
      total_executions: g?.total_executions ?? 0,
      total_errors: g?.total_errors ?? 0,
      total_timed_out: g?.total_timed_out ?? 0,
      total_job_errors: g?.total_job_errors ?? 0,
      total_job_timed_out: g?.total_job_timed_out ?? 0,
      error_rate: g?.error_rate ?? 0,
      last_activity_ts: g?.last_activity_ts ?? null,
      activity_buckets: g?.activity_buckets ?? [],
    };
  });
}

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

// ---- Sort ----

type SortKey = "name" | "status" | "error" | "runs" | "last";
interface SortState { key: SortKey; dir: "asc" | "desc" }

function compareRows(a: AppRow, b: AppRow, sort: SortState, liveStatuses: Record<string, { status: string } | undefined>): number {
  const dir = sort.dir === "asc" ? 1 : -1;
  const aStatus = liveStatuses[a.app_key]?.status ?? a.status;
  const bStatus = liveStatuses[b.app_key]?.status ?? b.status;
  switch (sort.key) {
    case "name":
      return dir * a.app_key.localeCompare(b.app_key);
    case "status": {
      const order: Record<string, number> = { failed: 0, blocked: 1, running: 2, stopped: 3, disabled: 4 };
      return dir * ((order[aStatus] ?? 5) - (order[bStatus] ?? 5));
    }
    case "error":
      return dir * ((a.error_message ? 0 : 1) - (b.error_message ? 0 : 1));
    case "runs": {
      const aRuns = a.total_invocations + a.total_executions;
      const bRuns = b.total_invocations + b.total_executions;
      return dir * (aRuns - bRuns);
    }
    case "last":
      return dir * ((a.last_activity_ts ?? 0) - (b.last_activity_ts ?? 0));
    default:
      return 0;
  }
}

// ---- Mini sparkline ----

function MiniSparkline({ buckets, width = 80, height = 20 }: {
  buckets: Array<{ ok: number; err: number }>;
  width?: number;
  height?: number;
}) {
  if (!buckets || buckets.length < 2) return null;
  const totals = buckets.map((b) => b.ok + b.err);
  const maxVal = Math.max(...totals, 1);
  const points = buckets.map((b, i) => {
    const x = (i / (buckets.length - 1)) * width;
    const y = height - ((b.ok + b.err) / maxVal) * height;
    return { x, y, ok: b.ok, err: b.err };
  });
  const line = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const errPoints = points.filter((p) => p.err > 0);

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" class="ht-apps-sparkline">
      <polyline points={line} fill="none" stroke="var(--ok)" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" />
      {errPoints.map((p, i) => (
        <circle key={i} cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r="2.5" fill="var(--err)">
          <title>{`${p.err} error${p.err > 1 ? "s" : ""}, ${p.ok} ok`}</title>
        </circle>
      ))}
    </svg>
  );
}

// ---- Stats strip ----

function StatsStrip({ apps, windowSeconds }: { apps: AppRow[]; windowSeconds: number | null }) {
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
    { label: "stopped", value: counts.stopped },
    { label: "disabled", value: counts.disabled },
    { label: "handlers", value: totalHandlers },
    { label: "runs / hr", value: runsPerHour !== null ? runsPerHour.toFixed(1) : "—" },
  ];

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

function SortHeader({ sort, setSort, k, children }: {
  sort: SortState;
  setSort: (s: SortState) => void;
  k: SortKey;
  children: preact.ComponentChildren;
}) {
  const isActive = sort.key === k;
  const arrow = isActive ? (sort.dir === "asc" ? " ↑" : " ↓") : "";
  return (
    <button
      type="button"
      class={`ht-apps-sort-header${isActive ? " ht-apps-sort-header--active" : ""}`}
      onClick={() => setSort({ key: k, dir: isActive && sort.dir === "asc" ? "desc" : "asc" })}
    >
      {children}{arrow}
    </button>
  );
}

// ---- Status pill ----

function StatusPill({ status }: { status: string }) {
  const kind = statusToKind(status);
  return (
    <span class={`ht-apps-status-pill ht-apps-status-pill--${kind}`} data-testid="status-pill">
      {status}
    </span>
  );
}

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
          <StatusPill status={status} />
          {isMulti && <span class="ht-apps-row__instance-count">{app.instance_count} instances</span>}
        </td>
        {/* Error */}
        <td class="ht-apps-row__error-cell">
          {app.error_message ? (
            <span
              class="ht-text-mono ht-text-sm"
              style={{ color: "var(--err)" }}
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
            <td><StatusPill status={instStatus} /></td>
            <td class="ht-apps-row__error-cell">
              {inst.error_message ? (
                <span class="ht-text-mono ht-text-sm" style={{ color: "var(--err)" }} title={inst.error_message}>{inst.error_message}</span>
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
  useEffect(() => { document.title = "Apps - Hassette"; }, []);

  const { appStatus, timePreset, uptimeSeconds } = useAppState();
  const { data: manifestData, loading: manifestLoading } = useApi(getManifests);
  const { data: gridData } = useScopedApi(
    (since) => getDashboardAppGrid(since),
  );

  const [filter, setFilter] = useState<FilterId>("all");
  const [sort, setSort] = useState<SortState>({ key: "status", dir: "asc" });
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
  const allApps = mergeData(manifests, gridEntries);

  const windowSeconds = uptimeSeconds.value !== null && uptimeSeconds.value !== undefined
    ? (timePreset.value === "since-restart" ? uptimeSeconds.value
      : timePreset.value === "1h" ? 3600
      : timePreset.value === "24h" ? 86400
      : 604800)
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
    .sort((a, b) => compareRows(a, b, sort, appStatus.value));

  if (manifestLoading.value && manifests.length === 0) return <Spinner />;

  return (
    <div class="ht-apps-page" data-testid="apps-page">
      {/* Header */}
      <div class="ht-apps-header">
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
          value={search}
          onInput={(e) => setSearch((e.target as HTMLInputElement).value)}
          data-testid="apps-search"
        />
      </div>

      {/* Table */}
      <div class="ht-card ht-apps-table-card">
        {filtered.length === 0 ? (
          <div class="ht-apps-empty">
            <p class="ht-text-muted">No apps match this filter.</p>
            {(filter !== "all" || q) && (
              <button type="button" class="ht-btn ht-btn--ghost ht-btn--sm" onClick={() => { setFilter("all"); setSearch(""); }}>clear filters</button>
            )}
          </div>
        ) : (
          <table class="ht-table ht-apps-table">
            <thead>
              <tr>
                <th><SortHeader sort={sort} setSort={setSort} k="name">app</SortHeader></th>
                <th><SortHeader sort={sort} setSort={setSort} k="status">status</SortHeader></th>
                <th><SortHeader sort={sort} setSort={setSort} k="error">last error</SortHeader></th>
                <th><SortHeader sort={sort} setSort={setSort} k="runs">runs</SortHeader></th>
                <th><SortHeader sort={sort} setSort={setSort} k="last">last fired</SortHeader></th>
                <th>actions</th>
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
