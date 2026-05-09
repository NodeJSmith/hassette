import { useState } from "preact/hooks";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useScopedApi } from "../hooks/use-scoped-api";
import { getAllListeners, getAllJobs } from "../api/endpoints";
import type { ListenerData, JobData } from "../api/endpoints";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../hooks/use-media-query";
import { AppLink } from "../components/shared/app-link";
import { EmptyState } from "../components/shared/empty-state";
import { SortHeader, type SortState } from "../components/shared/sort-header";
import { Spinner } from "../components/shared/spinner";
import { TierToolbar } from "../components/shared/tier-toolbar";
import { formatRelativeTime, formatDurationOrDash, pluralize } from "../utils/format";

// ---- Unified row model ----

interface UnifiedRow {
  kind: "handler" | "job";
  id: string;
  app_key: string;
  name: string;
  handler_method: string;
  trigger: string | null;
  runs: number;
  failed: number;
  timed_out: number;
  avg_duration_ms: number;
  next_run: string | null;
  next_run_ts: number | null;
  status: string | null;
  cancelled: boolean;
  source_tier: string;
}

function listenerToRow(l: ListenerData): UnifiedRow {
  return {
    kind: "handler",
    id: `h-${l.listener_id}`,
    app_key: l.app_key,
    name: l.handler_method.split(".").pop() ?? l.handler_method,
    handler_method: l.handler_method,
    trigger: l.listener_kind,
    runs: l.total_invocations,
    failed: l.failed,
    timed_out: l.timed_out,
    avg_duration_ms: l.avg_duration_ms,
    next_run: null,
    next_run_ts: null,
    status: null,
    cancelled: false,
    source_tier: l.source_tier,
  };
}

function jobToRow(j: JobData): UnifiedRow {
  return {
    kind: "job",
    id: `j-${j.job_id}`,
    app_key: j.app_key,
    name: j.job_name,
    handler_method: j.handler_method,
    trigger: j.trigger_label || j.trigger_type || null,
    runs: j.total_executions,
    failed: j.failed,
    timed_out: j.timed_out,
    avg_duration_ms: j.avg_duration_ms,
    next_run: formatNextRunValue(j),
    next_run_ts: j.cancelled || j.next_run === null || j.next_run === undefined ? null : j.next_run,
    status: j.cancelled ? "cancelled" : (j.failed > 0 ? "failing" : "active"),
    cancelled: j.cancelled,
    source_tier: j.source_tier,
  };
}

// ---- Formatting helpers ----

function fmtRate(failed: number, total: number): string {
  return total > 0 ? ((failed / total) * 100).toFixed(1) + "%" : "—";
}

function formatNextRunValue(job: JobData): string {
  if (job.cancelled) return "cancelled";
  if (job.next_run === null || job.next_run === undefined) return "—";
  const now = Date.now() / 1000;
  if (job.next_run < now) return "overdue";
  return formatRelativeTime(job.next_run);
}

// ---- Tier filter ----

type TierFilter = "all" | "app" | "framework";

function filterByTier<T extends { source_tier: string }>(items: T[], tier: TierFilter): T[] {
  if (tier === "all") return items;
  return tier === "app"
    ? items.filter((i) => i.source_tier === "app")
    : items.filter((i) => i.source_tier !== "app");
}

// ---- Sort ----

type SortKey = "kind" | "app" | "name" | "trigger" | "runs" | "failed" | "timed_out" | "error_rate" | "avg_duration" | "next_run" | "status";

function compareRows(a: UnifiedRow, b: UnifiedRow, sort: SortState<SortKey>): number {
  const dir = sort.dir === "asc" ? 1 : -1;
  switch (sort.key) {
    case "kind":
      return dir * a.kind.localeCompare(b.kind);
    case "app":
      return dir * a.app_key.localeCompare(b.app_key);
    case "name":
      return dir * a.name.localeCompare(b.name);
    case "trigger":
      return dir * (a.trigger ?? "").localeCompare(b.trigger ?? "");
    case "runs":
      return dir * (a.runs - b.runs);
    case "failed":
      return dir * (a.failed - b.failed);
    case "timed_out":
      return dir * (a.timed_out - b.timed_out);
    case "error_rate": {
      const rateA = a.runs > 0 ? a.failed / a.runs : 0;
      const rateB = b.runs > 0 ? b.failed / b.runs : 0;
      return dir * (rateA - rateB);
    }
    case "avg_duration":
      return dir * (a.avg_duration_ms - b.avg_duration_ms);
    case "next_run": {
      const ts = (r: UnifiedRow) => r.next_run_ts ?? Infinity;
      return dir * (ts(a) - ts(b));
    }
    case "status": {
      const rank = (r: UnifiedRow) => r.status === null ? 3 : r.cancelled ? 2 : r.failed > 0 ? 0 : 1;
      return dir * (rank(a) - rank(b));
    }
    default:
      return 0;
  }
}

// ---- Mobile card ----

interface MobileCardProps {
  href: string;
  appKey: string;
  name: string;
  failing?: boolean;
  muted?: boolean;
  "data-testid"?: string;
  metrics: preact.ComponentChildren;
  footer?: preact.ComponentChildren;
}

function MobileCard({ href, appKey, name, failing, muted, metrics, footer, ...rest }: MobileCardProps) {
  let cls = "ht-mobile-card";
  if (failing) cls += " ht-mobile-card--failing";
  if (muted) cls += " ht-mobile-card--muted";
  return (
    <a href={href} class={cls} data-testid={rest["data-testid"]}>
      <div class="ht-mobile-card__header">
        <span class="ht-text-mono ht-text-sm">{appKey}</span>
        <span class="ht-text-mono ht-text-sm ht-text-semibold">{name}</span>
      </div>
      <div class="ht-mobile-card__metrics">{metrics}</div>
      {footer && <div class="ht-mobile-card__footer">{footer}</div>}
    </a>
  );
}

// ---- Kind indicator ----

function KindBadge({ kind }: { kind: "handler" | "job" }) {
  return (
    <span class="ht-chip ht-chip--muted ht-chip--sm">
      {kind === "handler" ? "event" : "job"}
    </span>
  );
}

// ---- Page ----

export function HandlersPage() {
  useDocumentTitle("Handlers");

  const [tierFilter, setTierFilter] = useState<TierFilter>("app");
  const [selectedApp, setSelectedApp] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortState<SortKey>>({ key: "app", dir: "asc" });

  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  const listenersApi = useScopedApi((since) => getAllListeners(since));
  const jobsApi = useScopedApi((since) => getAllJobs(since));

  const allListeners = listenersApi.data.value ?? [];
  const allJobs = jobsApi.data.value ?? [];

  const isLoading = (listenersApi.loading.value && allListeners.length === 0)
    || (jobsApi.loading.value && allJobs.length === 0);

  if (isLoading) return <Spinner />;

  // Build unified rows
  const allRows: UnifiedRow[] = [
    ...allListeners.map(listenerToRow),
    ...allJobs.map(jobToRow),
  ];

  // Client-side tier filtering
  const tierFiltered = filterByTier(allRows, tierFilter);

  // Unique app keys for filter dropdown
  const appKeys = [...new Set(tierFiltered.map((r) => r.app_key))].sort();

  // App filter
  const appFiltered = selectedApp
    ? tierFiltered.filter((r) => r.app_key === selectedApp)
    : tierFiltered;

  // Search filter
  const searchLower = search.toLowerCase();
  const filtered = searchLower
    ? appFiltered.filter(
        (r) =>
          r.name.toLowerCase().includes(searchLower) ||
          r.app_key.toLowerCase().includes(searchLower) ||
          (r.trigger ?? "").toLowerCase().includes(searchLower),
      )
    : appFiltered;

  // Sort
  const sorted = [...filtered].sort((a, b) => compareRows(a, b, sort));

  return (
    <div class="ht-page ht-handlers-page" data-testid="handlers-page">
      <div class="ht-page-header">
        <h1 class="ht-display">handlers</h1>
      </div>

      <div class="ht-card ht-card--compact ht-handlers-card">
        <div class="ht-table-toolbar">
          <div class="ht-table-toolbar__title">
            <span class="ht-table-toolbar__note" aria-live="polite">
              {pluralize(sorted.filter((r) => r.kind === "handler").length, "handler")}
              {" · "}
              {pluralize(sorted.filter((r) => r.kind === "job").length, "job")}
            </span>
          </div>
          <div class="ht-table-toolbar__controls">
            <TierToolbar
              tierFilter={tierFilter}
              onTierChange={setTierFilter}
              appKeys={appKeys}
              selectedApp={selectedApp}
              onAppChange={setSelectedApp}
              search={search}
              onSearchChange={setSearch}
              searchPlaceholder="Search..."
              testIdPrefix="handlers"
            />
          </div>
        </div>
        <div class="ht-handlers-scroll">
          {sorted.length === 0 ? (
            <EmptyState title="no handlers found." data-testid="handlers-empty" />
          ) : isMobile ? (
            <div class="ht-mobile-cards" data-testid="handlers-table-container">
              {sorted.map((row) => {
                const errorRate = fmtRate(row.failed, row.runs);
                const avgDur = formatDurationOrDash(row.avg_duration_ms);
                return (
                  <MobileCard
                    key={row.id}
                    href={`/apps/${row.app_key}?focus=${row.handler_method}`}
                    appKey={row.app_key}
                    name={row.name}
                    failing={row.failed > 0}
                    muted={row.cancelled}
                    data-testid={`${row.kind}-row-${row.id}`}
                    metrics={<>
                      <KindBadge kind={row.kind} />
                      {row.trigger && <span>{row.trigger}</span>}
                      <span>{row.runs} runs</span>
                      {row.failed > 0 && <span class="ht-text-danger">{row.failed} failed</span>}
                      {row.timed_out > 0 && <span class="ht-text-warning">{row.timed_out} timed out</span>}
                      {row.runs > 0 && <span>{errorRate} err</span>}
                      {row.avg_duration_ms > 0 && <span>avg {avgDur}</span>}
                    </>}
                    footer={row.kind === "job" ? <>
                      <span class={row.cancelled ? "ht-text-muted" : row.failed > 0 ? "ht-text-danger" : ""}>{row.status}</span>
                      {!row.cancelled && row.next_run !== "—" && <span class="ht-text-muted">next {row.next_run}</span>}
                    </> : undefined}
                  />
                );
              })}
            </div>
          ) : (
            <div data-testid="handlers-table-container">
              <table class="ht-table ht-handlers-table">
                <thead>
                  <tr>
                    <SortHeader sort={sort} onSort={setSort} sortKey="kind">type</SortHeader>
                    <SortHeader sort={sort} onSort={setSort} sortKey="app">app</SortHeader>
                    <SortHeader sort={sort} onSort={setSort} sortKey="name">name</SortHeader>
                    <SortHeader sort={sort} onSort={setSort} sortKey="trigger">trigger</SortHeader>
                    <SortHeader sort={sort} onSort={setSort} sortKey="runs">runs</SortHeader>
                    <SortHeader sort={sort} onSort={setSort} sortKey="failed">failed</SortHeader>
                    <SortHeader sort={sort} onSort={setSort} sortKey="timed_out">timed out</SortHeader>
                    <SortHeader sort={sort} onSort={setSort} sortKey="error_rate">error rate</SortHeader>
                    <SortHeader sort={sort} onSort={setSort} sortKey="avg_duration">avg</SortHeader>
                    <SortHeader sort={sort} onSort={setSort} sortKey="next_run">next run</SortHeader>
                    <SortHeader sort={sort} onSort={setSort} sortKey="status">status</SortHeader>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((row) => {
                    const errorRate = fmtRate(row.failed, row.runs);
                    const avgDur = formatDurationOrDash(row.avg_duration_ms);
                    return (
                      <tr
                        key={row.id}
                        class={`ht-handlers-row${row.failed > 0 ? " ht-handlers-row--failing" : ""}${row.cancelled ? " ht-handlers-row--muted" : ""}`}
                        data-testid={`${row.kind}-row-${row.id}`}
                      >
                        <td><KindBadge kind={row.kind} /></td>
                        <td class="ht-text-mono ht-text-sm">
                          <AppLink appKey={row.app_key} />
                        </td>
                        <td class="ht-text-mono ht-text-sm">
                          <AppLink appKey={row.app_key} query={`focus=${row.handler_method}`}>{row.name}</AppLink>
                        </td>
                        <td class="ht-text-mono ht-text-sm">{row.trigger ?? "—"}</td>
                        <td class="ht-text-mono ht-text-sm">{row.runs}</td>
                        <td class={`ht-text-mono ht-text-sm${row.failed > 0 ? " ht-text-danger" : ""}`}>
                          {row.failed > 0 ? row.failed : "—"}
                        </td>
                        <td class={`ht-text-mono ht-text-sm${row.timed_out > 0 ? " ht-text-warning" : ""}`}>
                          {row.timed_out > 0 ? row.timed_out : "—"}
                        </td>
                        <td class={`ht-text-mono ht-text-sm${row.failed > 0 ? " ht-text-danger" : ""}`}>
                          {errorRate}
                        </td>
                        <td class="ht-text-mono ht-text-sm">{avgDur}</td>
                        <td class={`ht-text-mono ht-text-sm${row.next_run === "overdue" ? " ht-text-warning" : ""}`}>
                          {row.next_run ?? "—"}
                        </td>
                        <td class={`ht-text-mono ht-text-sm${row.cancelled ? " ht-text-muted" : row.failed > 0 ? " ht-text-danger" : ""}`}>
                          {row.status ?? "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
