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
import { formatRelativeTime, formatDurationOrDash, formatOptionalDuration } from "../utils/format";

// ---- Formatting helpers ----

function fmtRate(failed: number, total: number): string {
  return total > 0 ? ((failed / total) * 100).toFixed(1) + "%" : "—";
}

// ---- Tier toggle ----

type Tab = "handlers" | "jobs";

// ---- Sort ----

type HandlerSortKey = "app" | "handler" | "invocations" | "failed" | "timed_out" | "error_rate" | "avg_duration" | "min_duration" | "max_duration";
type JobSortKey = "app" | "name" | "trigger" | "executions" | "failed" | "timed_out" | "error_rate" | "avg_duration" | "min_duration" | "max_duration" | "next_run" | "status";

// ---- Next-run display ----

function formatNextRun(job: JobData): string {
  if (job.cancelled) return "cancelled";
  if (job.next_run === null || job.next_run === undefined) return "—";
  const now = Date.now() / 1000;
  if (job.next_run < now) return "overdue";
  return formatRelativeTime(job.next_run);
}

// ---- Handler sort comparator ----

function compareHandlers(a: ListenerData, b: ListenerData, sort: SortState<HandlerSortKey>): number {
  const dir = sort.dir === "asc" ? 1 : -1;
  switch (sort.key) {
    case "app":
      return dir * a.app_key.localeCompare(b.app_key);
    case "handler":
      return dir * a.handler_method.localeCompare(b.handler_method);
    case "invocations":
      return dir * (a.total_invocations - b.total_invocations);
    case "failed":
      return dir * (a.failed - b.failed);
    case "error_rate": {
      const rateA = a.total_invocations > 0 ? a.failed / a.total_invocations : 0;
      const rateB = b.total_invocations > 0 ? b.failed / b.total_invocations : 0;
      return dir * (rateA - rateB);
    }
    case "timed_out":
      return dir * (a.timed_out - b.timed_out);
    case "avg_duration":
      return dir * (a.avg_duration_ms - b.avg_duration_ms);
    case "min_duration":
      return dir * ((a.min_duration_ms ?? 0) - (b.min_duration_ms ?? 0));
    case "max_duration":
      return dir * ((a.max_duration_ms ?? 0) - (b.max_duration_ms ?? 0));
    default:
      return 0;
  }
}

// ---- Job sort comparator ----

function compareJobs(a: JobData, b: JobData, sort: SortState<JobSortKey>): number {
  const dir = sort.dir === "asc" ? 1 : -1;
  switch (sort.key) {
    case "app":
      return dir * a.app_key.localeCompare(b.app_key);
    case "name":
      return dir * a.job_name.localeCompare(b.job_name);
    case "trigger":
      return dir * (a.trigger_label ?? "").localeCompare(b.trigger_label ?? "");
    case "executions":
      return dir * (a.total_executions - b.total_executions);
    case "failed":
      return dir * (a.failed - b.failed);
    case "timed_out":
      return dir * (a.timed_out - b.timed_out);
    case "error_rate": {
      const rateA = a.total_executions > 0 ? a.failed / a.total_executions : 0;
      const rateB = b.total_executions > 0 ? b.failed / b.total_executions : 0;
      return dir * (rateA - rateB);
    }
    case "avg_duration":
      return dir * (a.avg_duration_ms - b.avg_duration_ms);
    case "min_duration":
      return dir * ((a.min_duration_ms ?? 0) - (b.min_duration_ms ?? 0));
    case "max_duration":
      return dir * ((a.max_duration_ms ?? 0) - (b.max_duration_ms ?? 0));
    case "next_run": {
      const aN = a.next_run ?? Infinity;
      const bN = b.next_run ?? Infinity;
      return dir * (aN - bN);
    }
    case "status": {
      const statusRank = (j: JobData) => j.cancelled ? 2 : (j.failed > 0 ? 0 : 1);
      return dir * (statusRank(a) - statusRank(b));
    }
    default:
      return 0;
  }
}

// ---- Tier filter ----

type TierFilter = "all" | "app" | "framework";

function filterByTier<T extends { source_tier: string }>(items: T[], tier: TierFilter): T[] {
  if (tier === "all") return items;
  return tier === "app"
    ? items.filter((i) => i.source_tier === "app")
    : items.filter((i) => i.source_tier !== "app");
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

// ---- Handlers table ----

interface HandlersTableProps {
  listeners: ListenerData[];
  sort: SortState<HandlerSortKey>;
  onSort: (s: SortState<HandlerSortKey>) => void;
}

function HandlersTable({ listeners, sort, onSort }: HandlersTableProps) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  if (listeners.length === 0) {
    return (
      <EmptyState title="no handlers registered." data-testid="handlers-empty" />
    );
  }

  if (isMobile) {
    return (
      <div class="ht-mobile-cards" data-testid="handlers-table-container">
        {listeners.map((l) => {
          const errorRate = fmtRate(l.failed, l.total_invocations);
          const avgDur = formatDurationOrDash(l.avg_duration_ms);
          return (
            <MobileCard
              key={l.listener_id}
              href={`/apps/${l.app_key}?focus=${l.handler_method}`}
              appKey={l.app_key}
              name={l.handler_method.split(".").pop() ?? l.handler_method}
              failing={l.failed > 0}
              data-testid={`handler-row-${l.listener_id}`}
              metrics={<>
                <span>{l.total_invocations} calls</span>
                {l.failed > 0 && <span class="ht-text-danger">{l.failed} failed</span>}
                {l.timed_out > 0 && <span class="ht-text-warning">{l.timed_out} timed out</span>}
                {l.total_invocations > 0 && <span>{errorRate} err</span>}
                {l.avg_duration_ms > 0 && <span>avg {avgDur}</span>}
              </>}
            />
          );
        })}
      </div>
    );
  }

  return (
    <div class="ht-handlers-table-wrap" data-testid="handlers-table-container">
      <table class="ht-table ht-handlers-table">
        <thead>
          <tr>
            <SortHeader sort={sort} onSort={onSort} sortKey="app">app</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="handler">handler</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="invocations">invocations</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="failed">failed</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="timed_out">timed out</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="error_rate">error rate</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="avg_duration">avg</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="min_duration">min</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="max_duration">max</SortHeader>
          </tr>
        </thead>
        <tbody>
          {listeners.map((l) => {
            const errorRate = fmtRate(l.failed, l.total_invocations);
            const avgDur = formatDurationOrDash(l.avg_duration_ms);
            const minDur = formatOptionalDuration(l.min_duration_ms);
            const maxDur = formatOptionalDuration(l.max_duration_ms);
            return (
              <tr
                key={l.listener_id}
                class={`ht-handlers-row${l.failed > 0 ? " ht-handlers-row--failing" : ""}`}
                data-testid={`handler-row-${l.listener_id}`}
              >
                <td class="ht-text-mono ht-text-sm">
                  <AppLink appKey={l.app_key} />
                </td>
                <td class="ht-text-mono ht-text-sm">
                  <AppLink appKey={l.app_key} query={`focus=${l.handler_method}`}>{l.handler_method.split(".").pop()}</AppLink>
                </td>
                <td class="ht-text-mono ht-text-sm">{l.total_invocations}</td>
                <td class={`ht-text-mono ht-text-sm${l.failed > 0 ? " ht-text-danger" : ""}`}>
                  {l.failed > 0 ? l.failed : "—"}
                </td>
                <td class={`ht-text-mono ht-text-sm${l.timed_out > 0 ? " ht-text-warning" : ""}`}>
                  {l.timed_out > 0 ? l.timed_out : "—"}
                </td>
                <td class={`ht-text-mono ht-text-sm${l.failed > 0 ? " ht-text-danger" : ""}`}>
                  {errorRate}
                </td>
                <td class="ht-text-mono ht-text-sm">{avgDur}</td>
                <td class="ht-text-mono ht-text-sm">{minDur}</td>
                <td class="ht-text-mono ht-text-sm">{maxDur}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- Jobs table ----

interface JobsTableProps {
  jobs: JobData[];
  sort: SortState<JobSortKey>;
  onSort: (s: SortState<JobSortKey>) => void;
}

function JobsTable({ jobs, sort, onSort }: JobsTableProps) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  if (jobs.length === 0) {
    return (
      <EmptyState title="no jobs scheduled." data-testid="jobs-empty" />
    );
  }

  if (isMobile) {
    return (
      <div class="ht-mobile-cards" data-testid="jobs-table-container">
        {jobs.map((j) => {
          const nextRun = formatNextRun(j);
          const isCancelled = j.cancelled;
          const statusText = isCancelled ? "cancelled" : (j.failed > 0 ? "failing" : "active");
          const avgDur = formatDurationOrDash(j.avg_duration_ms);
          return (
            <MobileCard
              key={j.job_id}
              href={`/apps/${j.app_key}?focus=${j.handler_method}`}
              appKey={j.app_key}
              name={j.job_name}
              failing={j.failed > 0}
              muted={isCancelled}
              data-testid={`job-row-${j.job_id}`}
              metrics={<>
                <span>{j.trigger_label}</span>
                <span>{j.total_executions} runs</span>
                {j.failed > 0 && <span class="ht-text-danger">{j.failed} failed</span>}
                {j.timed_out > 0 && <span class="ht-text-warning">{j.timed_out} timed out</span>}
                {j.avg_duration_ms > 0 && <span>avg {avgDur}</span>}
              </>}
              footer={<>
                <span class={isCancelled ? "ht-text-muted" : j.failed > 0 ? "ht-text-danger" : ""}>{statusText}</span>
                {!isCancelled && nextRun !== "—" && <span class="ht-text-muted">next {nextRun}</span>}
              </>}
            />
          );
        })}
      </div>
    );
  }

  return (
    <div class="ht-handlers-table-wrap" data-testid="jobs-table-container">
      <table class="ht-table ht-handlers-table">
        <thead>
          <tr>
            <SortHeader sort={sort} onSort={onSort} sortKey="app">app</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="name">job name</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="trigger">trigger</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="executions">executions</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="failed">failed</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="timed_out">timed out</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="error_rate">error rate</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="avg_duration">avg</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="min_duration">min</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="max_duration">max</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="next_run">next run</SortHeader>
            <SortHeader sort={sort} onSort={onSort} sortKey="status">status</SortHeader>
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => {
            const nextRun = formatNextRun(j);
            const isOverdue = nextRun === "overdue";
            const isCancelled = j.cancelled;
            const statusText = isCancelled ? "cancelled" : (j.failed > 0 ? "failing" : "active");
            const errorRate = fmtRate(j.failed, j.total_executions);
            const avgDur = formatDurationOrDash(j.avg_duration_ms);
            const minDur = formatOptionalDuration(j.min_duration_ms);
            const maxDur = formatOptionalDuration(j.max_duration_ms);
            return (
              <tr
                key={j.job_id}
                class={`ht-handlers-row${j.failed > 0 ? " ht-handlers-row--failing" : ""}`}
                data-testid={`job-row-${j.job_id}`}
              >
                <td class="ht-text-mono ht-text-sm">
                  <AppLink appKey={j.app_key} />
                </td>
                <td class="ht-text-mono ht-text-sm">
                  <AppLink appKey={j.app_key} query={`focus=${j.handler_method}`}>{j.job_name}</AppLink>
                </td>
                <td class="ht-text-mono ht-text-sm">{j.trigger_label}</td>
                <td class="ht-text-mono ht-text-sm">{j.total_executions}</td>
                <td class={`ht-text-mono ht-text-sm${j.failed > 0 ? " ht-text-danger" : ""}`}>
                  {j.failed > 0 ? j.failed : "—"}
                </td>
                <td class={`ht-text-mono ht-text-sm${j.timed_out > 0 ? " ht-text-warning" : ""}`}>
                  {j.timed_out > 0 ? j.timed_out : "—"}
                </td>
                <td class={`ht-text-mono ht-text-sm${j.failed > 0 ? " ht-text-danger" : ""}`}>
                  {errorRate}
                </td>
                <td class="ht-text-mono ht-text-sm">{avgDur}</td>
                <td class="ht-text-mono ht-text-sm">{minDur}</td>
                <td class="ht-text-mono ht-text-sm">{maxDur}</td>
                <td class={`ht-text-mono ht-text-sm${isOverdue ? " ht-text-warning" : ""}`}>
                  {nextRun}
                </td>
                <td class={`ht-text-mono ht-text-sm${isCancelled ? " ht-text-muted" : j.failed > 0 ? " ht-text-danger" : ""}`}>
                  {statusText}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- Page ----

export function HandlersPage() {
  useDocumentTitle("Handlers");

  const [activeTab, setActiveTab] = useState<Tab>("handlers");
  const [tierFilter, setTierFilter] = useState<TierFilter>("app");
  const [selectedApp, setSelectedApp] = useState("");
  const [search, setSearch] = useState("");
  const [handlerSort, setHandlerSort] = useState<SortState<HandlerSortKey>>({ key: "app", dir: "asc" });
  const [jobSort, setJobSort] = useState<SortState<JobSortKey>>({ key: "app", dir: "asc" });

  const listenersApi = useScopedApi((since) => getAllListeners(since));
  const jobsApi = useScopedApi((since) => getAllJobs(since));

  const allListeners = listenersApi.data.value ?? [];
  const allJobs = jobsApi.data.value ?? [];

  // Client-side tier filtering
  const tierFilteredListeners = filterByTier(allListeners, tierFilter);
  const tierFilteredJobs = filterByTier(allJobs, tierFilter);

  // Unique app keys for filter dropdowns
  const handlerAppKeys = [...new Set(tierFilteredListeners.map((l) => l.app_key))].sort();
  const jobAppKeys = [...new Set(tierFilteredJobs.map((j) => j.app_key))].sort();

  // App filter
  const appFilteredListeners = selectedApp
    ? tierFilteredListeners.filter((l) => l.app_key === selectedApp)
    : tierFilteredListeners;

  const appFilteredJobs = selectedApp
    ? tierFilteredJobs.filter((j) => j.app_key === selectedApp)
    : tierFilteredJobs;

  // Search filter (case-insensitive match on handler_method, app_key, job_name)
  const searchLower = search.toLowerCase();
  const filteredListeners = searchLower
    ? appFilteredListeners.filter(
        (l) =>
          l.handler_method.toLowerCase().includes(searchLower) ||
          l.app_key.toLowerCase().includes(searchLower),
      )
    : appFilteredListeners;

  const filteredJobs = searchLower
    ? appFilteredJobs.filter(
        (j) =>
          j.job_name.toLowerCase().includes(searchLower) ||
          j.app_key.toLowerCase().includes(searchLower),
      )
    : appFilteredJobs;

  // Sort
  const sortedListeners = [...filteredListeners].sort((a, b) => compareHandlers(a, b, handlerSort));
  const sortedJobs = [...filteredJobs].sort((a, b) => compareJobs(a, b, jobSort));

  const isLoading = activeTab === "handlers"
    ? listenersApi.loading.value && allListeners.length === 0
    : jobsApi.loading.value && allJobs.length === 0;

  if (isLoading) return <Spinner />;

  const appKeys = activeTab === "handlers" ? handlerAppKeys : jobAppKeys;

  return (
    <div class="ht-page ht-handlers-page" data-testid="handlers-page">
      {/* Header */}
      <div class="ht-page-header">
        <h1 class="ht-display">handlers</h1>
      </div>

      {/* Tabs */}
      <div class="ht-tab-strip" role="tablist" aria-label="View" data-testid="handlers-tabs">
        <button
          type="button"
          role="tab"
          id="tab-handlers"
          aria-selected={activeTab === "handlers"}
          aria-controls="tabpanel-handlers"
          class={`ht-tab-btn${activeTab === "handlers" ? " ht-tab-btn--active" : ""}`}
          onClick={() => { setActiveTab("handlers"); setSelectedApp(""); setSearch(""); }}
          data-testid="tab-handlers"
        >
          handlers{allListeners.length > 0 && <span class="ht-tab-btn__badge">{tierFilteredListeners.length}</span>}
        </button>
        <button
          type="button"
          role="tab"
          id="tab-jobs"
          aria-selected={activeTab === "jobs"}
          aria-controls="tabpanel-jobs"
          class={`ht-tab-btn${activeTab === "jobs" ? " ht-tab-btn--active" : ""}`}
          onClick={() => { setActiveTab("jobs"); setSelectedApp(""); setSearch(""); }}
          data-testid="tab-jobs"
        >
          jobs{allJobs.length > 0 && <span class="ht-tab-btn__badge">{tierFilteredJobs.length}</span>}
        </button>
      </div>

      {/* Toolbar */}
      <TierToolbar
        tierFilter={tierFilter}
        onTierChange={setTierFilter}
        appKeys={appKeys}
        selectedApp={selectedApp}
        onAppChange={setSelectedApp}
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="Search..."
        testIdPrefix={activeTab === "handlers" ? "handlers" : "jobs"}
      />

      {/* Content */}
      {activeTab === "handlers" ? (
        <div role="tabpanel" id="tabpanel-handlers" aria-labelledby="tab-handlers" class="ht-card ht-handlers-table-card">
          <HandlersTable
            listeners={sortedListeners}
            sort={handlerSort}
            onSort={setHandlerSort}
          />
        </div>
      ) : (
        <div role="tabpanel" id="tabpanel-jobs" aria-labelledby="tab-jobs" class="ht-card ht-handlers-table-card">
          <JobsTable
            jobs={sortedJobs}
            sort={jobSort}
            onSort={setJobSort}
          />
        </div>
      )}
    </div>
  );
}
