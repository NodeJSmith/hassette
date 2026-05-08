import { useEffect, useState } from "preact/hooks";
import { useScopedApi } from "../hooks/use-scoped-api";
import { getAllListeners, getAllJobs } from "../api/endpoints";
import type { ListenerData, JobData } from "../api/endpoints";
import { SortHeader } from "../components/shared/sort-header";
import { Spinner } from "../components/shared/spinner";
import { TierToolbar } from "../components/shared/tier-toolbar";
import { formatRelativeTime, formatDuration } from "../utils/format";

// ---- Tier toggle ----

type Tab = "handlers" | "jobs";

// ---- Sort ----

type HandlerSortKey = "app" | "handler" | "invocations" | "failed" | "error_rate" | "avg_duration" | "max_duration";
type JobSortKey = "app" | "name" | "trigger" | "executions" | "failed" | "timed_out" | "next_run" | "status";
interface SortState<K extends string> { key: K; dir: "asc" | "desc" }

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
    case "avg_duration":
      return dir * (a.avg_duration_ms - b.avg_duration_ms);
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

// ---- Tier filter type ----

type TierFilter = "all" | "app" | "framework";

// ---- Handlers table ----

interface HandlersTableProps {
  listeners: ListenerData[];
  sort: SortState<HandlerSortKey>;
  onSort: (s: SortState<HandlerSortKey>) => void;
}

function HandlersTable({ listeners, sort, onSort }: HandlersTableProps) {
  function header(k: HandlerSortKey, children: preact.ComponentChildren) {
    const isActive = sort.key === k;
    return (
      <SortHeader
        active={isActive}
        direction={isActive ? sort.dir : "asc"}
        onClick={() => onSort({ key: k, dir: isActive && sort.dir === "asc" ? "desc" : "asc" })}
      >
        {children}
      </SortHeader>
    );
  }

  if (listeners.length === 0) {
    return (
      <div class="ht-empty-state" data-testid="handlers-empty">
        <p class="ht-text-muted">no handlers registered.</p>
      </div>
    );
  }

  return (
    <div class="ht-handlers-table-wrap" data-testid="handlers-table-container">
      <table class="ht-table ht-handlers-table">
        <thead>
          <tr>
            {header("app", "app")}
            {header("handler", "handler")}
            {header("invocations", "invocations")}
            {header("failed", "failed")}
            {header("error_rate", "error rate")}
            {header("avg_duration", "avg")}
            {header("max_duration", "max")}
          </tr>
        </thead>
        <tbody>
          {listeners.map((l) => {
            const errorRate = l.total_invocations > 0
              ? ((l.failed / l.total_invocations) * 100).toFixed(1) + "%"
              : "—";
            const avgDur = l.avg_duration_ms > 0 ? formatDuration(l.avg_duration_ms) : "—";
            const maxDur = l.max_duration_ms !== null && l.max_duration_ms !== undefined
              ? formatDuration(l.max_duration_ms) : "—";
            return (
              <tr
                key={l.listener_id}
                class={`ht-handlers-row${l.failed > 0 ? " ht-handlers-row--failing" : ""}`}
                data-testid={`handler-row-${l.listener_id}`}
              >
                <td class="ht-text-mono ht-text-sm">
                  <a href={`/apps/${l.app_key}`} class="ht-handlers-row__app-link">{l.app_key}</a>
                </td>
                <td class="ht-text-mono ht-text-sm">
                  <a href={`/apps/${l.app_key}?focus=${l.handler_method}`} class="ht-handlers-row__handler-link" title={l.handler_method}>
                    {l.handler_method.split(".").pop()}
                  </a>
                </td>
                <td class="ht-text-mono ht-text-sm">{l.total_invocations}</td>
                <td class={`ht-text-mono ht-text-sm${l.failed > 0 ? " ht-text-danger" : ""}`}>
                  {l.failed > 0 ? l.failed : "—"}
                </td>
                <td class={`ht-text-mono ht-text-sm${l.failed > 0 ? " ht-text-danger" : ""}`}>
                  {errorRate}
                </td>
                <td class="ht-text-mono ht-text-sm">{avgDur}</td>
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
  function header(k: JobSortKey, children: preact.ComponentChildren) {
    const isActive = sort.key === k;
    return (
      <SortHeader
        active={isActive}
        direction={isActive ? sort.dir : "asc"}
        onClick={() => onSort({ key: k, dir: isActive && sort.dir === "asc" ? "desc" : "asc" })}
      >
        {children}
      </SortHeader>
    );
  }

  if (jobs.length === 0) {
    return (
      <div class="ht-empty-state" data-testid="jobs-empty">
        <p class="ht-text-muted">no jobs scheduled.</p>
      </div>
    );
  }

  return (
    <div class="ht-handlers-table-wrap" data-testid="jobs-table-container">
      <table class="ht-table ht-handlers-table">
        <thead>
          <tr>
            {header("app", "app")}
            {header("name", "job name")}
            {header("trigger", "trigger")}
            {header("executions", "executions")}
            {header("failed", "failed")}
            {header("timed_out", "timed out")}
            {header("next_run", "next run")}
            {header("status", "status")}
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => {
            const nextRun = formatNextRun(j);
            const isOverdue = nextRun === "overdue";
            const isCancelled = j.cancelled;
            const statusText = isCancelled ? "cancelled" : (j.failed > 0 ? "failing" : "active");
            return (
              <tr
                key={j.job_id}
                class={`ht-handlers-row${j.failed > 0 ? " ht-handlers-row--failing" : ""}`}
                data-testid={`job-row-${j.job_id}`}
              >
                <td class="ht-text-mono ht-text-sm">
                  <a href={`/apps/${j.app_key}`} class="ht-handlers-row__app-link">{j.app_key}</a>
                </td>
                <td class="ht-text-mono ht-text-sm">
                  <a href={`/apps/${j.app_key}?focus=${j.handler_method}`} class="ht-handlers-row__handler-link">{j.job_name}</a>
                </td>
                <td class="ht-text-mono ht-text-sm">{j.trigger_label}</td>
                <td class="ht-text-mono ht-text-sm">{j.total_executions}</td>
                <td class={`ht-text-mono ht-text-sm${j.failed > 0 ? " ht-text-danger" : ""}`}>
                  {j.failed > 0 ? j.failed : "—"}
                </td>
                <td class={`ht-text-mono ht-text-sm${j.timed_out > 0 ? " ht-text-warning" : ""}`}>
                  {j.timed_out > 0 ? j.timed_out : "—"}
                </td>
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
  useEffect(() => { document.title = "Handlers - Hassette"; }, []);

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
  const tierFilteredListeners = tierFilter === "all"
    ? allListeners
    : tierFilter === "app"
      ? allListeners.filter((l) => l.source_tier === "app")
      : allListeners.filter((l) => l.source_tier !== "app");

  const tierFilteredJobs = tierFilter === "all"
    ? allJobs
    : tierFilter === "app"
      ? allJobs.filter((j) => j.source_tier === "app")
      : allJobs.filter((j) => j.source_tier !== "app");

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
      <div class="ht-tabs" role="tablist" aria-label="View" data-testid="handlers-tabs">
        <button
          type="button"
          role="tab"
          id="tab-handlers"
          aria-selected={activeTab === "handlers"}
          aria-controls="tabpanel-handlers"
          onClick={() => { setActiveTab("handlers"); setSelectedApp(""); setSearch(""); }}
          data-testid="tab-handlers"
        >
          handlers{allListeners.length > 0 ? ` (${tierFilteredListeners.length})` : ""}
        </button>
        <button
          type="button"
          role="tab"
          id="tab-jobs"
          aria-selected={activeTab === "jobs"}
          aria-controls="tabpanel-jobs"
          onClick={() => { setActiveTab("jobs"); setSelectedApp(""); setSearch(""); }}
          data-testid="tab-jobs"
        >
          jobs{allJobs.length > 0 ? ` (${tierFilteredJobs.length})` : ""}
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
