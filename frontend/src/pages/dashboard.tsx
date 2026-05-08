import { useEffect, useRef } from "preact/hooks";
import { useApi } from "../hooks/use-api";
import {
  getDashboardAppGrid,
  getDashboardErrors,
  getDashboardKpis,
  getManifests,
  getSystemStatus,
  type DashboardErrorEntry,
  type BootIssue,
} from "../api/endpoints";
import { TelemetryDegradedBanner } from "../components/layout/alert-banner";
import { Spinner } from "../components/shared/spinner";
import { StatusShape } from "../components/shared/status-shape";
import { MiniSparkline } from "../components/shared/mini-sparkline";
import { useScopedApi } from "../hooks/use-scoped-api";
import { useDebouncedEffect } from "../hooks/use-debounced-effect";
import { useAppState } from "../state/context";
import { statusToKind } from "../utils/status";
import { formatRelativeTime, formatUptime, lastDotSegment } from "../utils/format";
import { type AppRow, mergeManifestsAndGrid, compareAppRows } from "../utils/app-data";

// ---- Stats strip (unified) --------------------------------------------------

interface StatsStripProps {
  uptime: number | null;
  appCount: number;
  serviceTotal: number;
  serviceHealthy: number;
  runsPerHour: number | null;
  successRate: number;
  handlerCount: number;
  droppedEvents: number;
}

function StatsStrip(props: StatsStripProps) {
  const svcUnhealthy = props.serviceTotal - props.serviceHealthy;

  const cells: Array<{ label: string; value: string | number; warn?: boolean }> = [
    { label: "uptime", value: props.uptime !== null ? formatUptime(props.uptime) : "—" },
    { label: "apps", value: props.appCount },
    { label: "services", value: svcUnhealthy > 0 ? `${props.serviceHealthy}/${props.serviceTotal}` : String(props.serviceTotal), warn: svcUnhealthy > 0 },
    { label: "runs / hr", value: props.runsPerHour !== null ? Math.round(props.runsPerHour) : "—" },
    { label: "success", value: `${props.successRate.toFixed(1)}%`, warn: props.successRate < 95 },
    { label: "handlers", value: props.handlerCount },
    { label: "dropped", value: props.droppedEvents, warn: props.droppedEvents > 0 },
  ];

  return (
    <div class="ht-overview-stats" data-testid="overview-stats-strip">
      {cells.map((c) => (
        <div key={c.label} class="ht-overview-stats__cell">
          <span class="ht-overview-stats__label">{c.label}</span>
          <span class={`ht-overview-stats__value${c.warn ? " ht-overview-stats__value--warn" : ""}`}>{c.value}</span>
        </div>
      ))}
    </div>
  );
}

// ---- Alerts bar -------------------------------------------------------------

function AlertsBar({ bootIssues, unhealthyServices }: {
  bootIssues: BootIssue[];
  unhealthyServices: Array<{ name: string; status: string }>;
}) {
  if (bootIssues.length === 0 && unhealthyServices.length === 0) return null;

  const parts: string[] = [];
  const errorCount = bootIssues.filter((i) => i.severity === "err").length;
  const warnCount = bootIssues.filter((i) => i.severity === "warn").length;
  if (errorCount > 0) parts.push(`${errorCount} boot error${errorCount > 1 ? "s" : ""}`);
  if (warnCount > 0) parts.push(`${warnCount} boot warning${warnCount > 1 ? "s" : ""}`);
  if (unhealthyServices.length > 0) {
    parts.push(`${unhealthyServices.length} degraded service${unhealthyServices.length > 1 ? "s" : ""}`);
  }

  return (
    <div class="ht-overview-alerts" data-testid="overview-alerts-bar" role="status">
      <StatusShape kind="warn" size={8} />
      <span class="ht-overview-alerts__text">{parts.join(" · ")}</span>
      <a href="/diagnostics" class="ht-overview-alerts__link">view diagnostics →</a>
    </div>
  );
}

// ---- App health table -------------------------------------------------------

function AppHealthTable({ apps, liveStatuses }: {
  apps: AppRow[];
  liveStatuses: Record<string, { status: string } | undefined>;
}) {
  const sorted = [...apps].sort((a, b) =>
    compareAppRows(a, b, { key: "status", dir: "asc" }, liveStatuses),
  );

  if (sorted.length === 0) {
    return (
      <div class="ht-card ht-overview-apps" data-testid="overview-app-table">
        <div class="ht-overview-apps__header">
          <h2 class="ht-overview-section-title">apps</h2>
          <a href="/apps" class="ht-overview-section-link">all apps →</a>
        </div>
        <p class="ht-empty-state ht-text-muted">
          no apps loaded. <a href="https://hassette.readthedocs.io/en/latest/getting-started/" class="ht-link">get started →</a>
        </p>
      </div>
    );
  }

  return (
    <div class="ht-card ht-overview-apps" data-testid="overview-app-table">
      <div class="ht-overview-apps__header">
        <h2 class="ht-overview-section-title">apps</h2>
        <a href="/apps" class="ht-overview-section-link">all apps →</a>
      </div>
      <table class="ht-table ht-table--dense ht-overview-apps__table" aria-label="App health">
        <thead>
          <tr>
            <th scope="col">app</th>
            <th scope="col" class="ht-overview-apps__sparkline-cell">activity</th>
            <th scope="col" class="ht-overview-apps__col-num">runs</th>
            <th scope="col" class="ht-overview-apps__col-num">err %</th>
            <th scope="col" class="ht-overview-apps__col-last-err">last error</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((app) => {
            const status = liveStatuses[app.app_key]?.status ?? app.status;
            const kind = statusToKind(status);
            const totalRuns = app.total_invocations + app.total_executions;
            const totalErrors = app.total_errors + app.total_timed_out + app.total_job_errors + app.total_job_timed_out;
            const errPct = totalRuns > 0 ? (totalErrors / totalRuns) * 100 : 0;
            const isDimmed = status === "stopped" || status === "disabled";

            return (
              <tr
                key={app.app_key}
                class={`ht-overview-apps__row${isDimmed ? " ht-overview-apps__row--dimmed" : ""}`}
                data-testid={`overview-app-${app.app_key}`}
              >
                <td class="ht-overview-apps__name-cell">
                  <StatusShape kind={kind} size={7} />
                  <a href={`/apps/${app.app_key}`} class="ht-overview-apps__name">{app.app_key}</a>
                </td>
                <td class="ht-overview-apps__sparkline-cell">
                  <MiniSparkline buckets={app.activity_buckets} width={64} height={16} />
                </td>
                <td class="ht-text-mono ht-text-sm ht-overview-apps__col-num">{totalRuns}</td>
                <td class={`ht-text-mono ht-text-sm ht-overview-apps__col-num${errPct > 0 ? " ht-text-danger" : ""}`}>
                  {errPct > 0 ? errPct.toFixed(1) : "0"}
                </td>
                <td class="ht-text-mono ht-text-sm ht-text-muted ht-overview-apps__col-last-err">
                  {app.last_error_ts ? formatRelativeTime(app.last_error_ts) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- Recent errors ----------------------------------------------------------

const MAX_RECENT_ERRORS = 5;

function RecentErrors({ errors }: { errors: DashboardErrorEntry[] | null }) {
  if (!errors || errors.length === 0) return null;

  const visible = errors.slice(0, MAX_RECENT_ERRORS);

  return (
    <div class="ht-card ht-overview-errors" data-testid="overview-recent-errors">
      <div class="ht-overview-errors__header">
        <h2 class="ht-overview-section-title">recent errors</h2>
        <a href="/logs" class="ht-overview-section-link">all logs →</a>
      </div>
      <table class="ht-table ht-table--dense ht-overview-errors__table" aria-label="Recent errors">
        <tbody>
          {visible.map((err, i) => {
            const age = formatRelativeTime(err.execution_start_ts);
            const errType = err.error_type ? lastDotSegment(err.error_type) : "";
            const method = err.kind === "handler" ? err.handler_method : err.kind === "job" ? err.job_name : null;
            return (
              <tr key={`${err.kind}-${err.execution_start_ts}-${i}`}>
                <td class="ht-overview-errors__age">{age}</td>
                <td class="ht-overview-errors__app">
                  {err.app_key ? (
                    <a href={`/apps/${err.app_key}`} class="ht-link">{err.app_key}</a>
                  ) : (
                    <span class="ht-text-muted">framework</span>
                  )}
                </td>
                <td class="ht-overview-errors__detail">
                  {method && <span class="ht-overview-errors__method">{method}()</span>}
                  {errType && <span class="ht-overview-errors__type">{errType}</span>}
                  {err.error_message && (
                    <span class="ht-overview-errors__msg">: {err.error_message}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- Dashboard page ---------------------------------------------------------

export function DashboardPage() {
  useEffect(() => { document.title = "Overview - Hassette"; }, []);

  const {
    appStatus, invocationCompleted, executionCompleted,
    uptimeSeconds, droppedOverflow, droppedExhausted, droppedNoSession, droppedShutdown,
  } = useAppState();

  const totalDropped = droppedOverflow.value + droppedExhausted.value + droppedNoSession.value + droppedShutdown.value;

  const kpis = useScopedApi((since) => getDashboardKpis(since, "app"));
  const appGrid = useScopedApi((since) => getDashboardAppGrid(since).then((r) => r.apps));
  const manifests = useApi(getManifests);
  const errors = useScopedApi((since) => getDashboardErrors(since).then((r) => r.errors));
  const systemStatus = useApi(getSystemStatus);

  // Debounce WS-driven refetches
  const initialLoadDone = !kpis.loading.value && !appGrid.loading.value;
  const statusVersionRef = useRef(0);
  const prevStatusRef = useRef(appStatus.value);
  const prevInvRef = useRef(invocationCompleted.value);
  const prevExecRef = useRef(executionCompleted.value);

  if (initialLoadDone) {
    if (appStatus.value !== prevStatusRef.current) {
      prevStatusRef.current = appStatus.value;
      statusVersionRef.current += 1;
    }
    if (invocationCompleted.value !== prevInvRef.current) {
      prevInvRef.current = invocationCompleted.value;
      statusVersionRef.current += 1;
    }
    if (executionCompleted.value !== prevExecRef.current) {
      prevExecRef.current = executionCompleted.value;
      statusVersionRef.current += 1;
    }
  }

  useDebouncedEffect(
    () => statusVersionRef.current,
    500,
    () => {
      void Promise.allSettled([kpis.refetch(), appGrid.refetch(), errors.refetch()]);
    },
    2000,
  );

  // Merge manifests + grid into AppRow[]
  const manifestList = manifests.data.value?.manifests ?? [];
  const gridEntries = appGrid.data.value ?? [];
  const apps = mergeManifestsAndGrid(manifestList, gridEntries);

  // Compute KPI values
  const kpiData = kpis.data.value;
  const totalHandlers = (kpiData?.total_handlers ?? 0) + (kpiData?.total_jobs ?? 0);
  const successRate = kpiData ? 100 - kpiData.error_rate : 100;
  const uptime = uptimeSeconds.value ?? 0;
  const rateReliable = uptime >= 1800;
  const runsPerHour = rateReliable ? (kpiData?.runs_per_hour ?? 0) : null;

  // System health
  const services = systemStatus.data.value?.services ?? [];
  const bootIssues = systemStatus.data.value?.boot_issues ?? [];
  const unhealthyServices = services.filter((s) => s.status !== "running");

  const hasData = kpiData !== null || apps.length > 0;
  const isLoading = kpis.loading.value && manifests.loading.value && !hasData;

  if (isLoading) return <Spinner />;

  return (
    <div class="ht-page ht-overview" data-testid="overview-page">
      <TelemetryDegradedBanner />

      <div class="ht-page-header">
        <h1 class="ht-display">overview</h1>
      </div>

      <StatsStrip
        uptime={uptimeSeconds.value}
        appCount={apps.length}
        serviceTotal={services.length}
        serviceHealthy={services.filter((s) => s.status === "running").length}
        runsPerHour={runsPerHour}
        successRate={successRate}
        handlerCount={totalHandlers}
        droppedEvents={totalDropped}
      />

      <AlertsBar bootIssues={bootIssues} unhealthyServices={unhealthyServices} />

      <AppHealthTable apps={apps} liveStatuses={appStatus.value} />

      <RecentErrors errors={errors.data.value} />
    </div>
  );
}
