import { useEffect, useRef } from "preact/hooks";
import { signal, useSignal, type Signal } from "@preact/signals";
import type { UseApiResult } from "../hooks/use-api";
import { useApi } from "../hooks/use-api";
import {
  getDashboardAppGrid,
  getDashboardErrors,
  getDashboardKpis,
  getSystemStatus,
} from "../api/endpoints";
import type {
  SourceTier,
  DashboardAppGridEntry,
  DashboardKpis,
  DashboardErrorEntry,
  BootIssue,
} from "../api/endpoints";
import { TelemetryDegradedBanner } from "../components/layout/alert-banner";
import { Spinner } from "../components/shared/spinner";
import { StatusShape } from "../components/shared/status-shape";
import { useScopedApi } from "../hooks/use-scoped-api";
import { useDebouncedEffect } from "../hooks/use-debounced-effect";
import { useAppState } from "../state/context";
import { statusToKind } from "../utils/status";
import { formatRelativeTime, lastDotSegment, TIME_PRESET_LABELS } from "../utils/format";

const TIER_OPTIONS: { value: SourceTier; label: string }[] = [
  { value: "all", label: "All" },
  { value: "app", label: "Apps" },
  { value: "framework", label: "Framework" },
];

// ---- System state detection ------------------------------------------------

type SystemState =
  | "first_install"
  | "healthy"
  | "quiet"
  | "single_failure"
  | "multiple_failures";

function detectSystemState(
  apps: DashboardAppGridEntry[] | null,
  kpis: DashboardKpis | null,
): SystemState {
  if (!apps || apps.length === 0) return "first_install";

  const failedApps = apps.filter((a) => a.status === "failed" || a.status === "crashed");
  if (failedApps.length >= 2) return "multiple_failures";
  if (failedApps.length === 1) return "single_failure";

  const totalActivity = (kpis?.total_invocations ?? 0) + (kpis?.total_executions ?? 0);
  if (totalActivity === 0) return "quiet";

  return "healthy";
}

// ---- Greeting helpers -------------------------------------------------------

/** Intentionally recomputed on each render so greeting updates across noon. */
function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning.";
  if (h < 18) return "Good afternoon.";
  return "Good evening.";
}

function getSubtitle(
  state: SystemState,
  apps: DashboardAppGridEntry[] | null,
): string {
  switch (state) {
    case "first_install":
      return "no apps loaded yet. drop a python file into your apps directory to get started.";
    case "healthy":
      return "all apps are healthy. nothing needs your attention right now.";
    case "quiet":
      return "all apps are running, but nothing has happened in a while.";
    case "multiple_failures": {
      const failCount = (apps ?? []).filter((a) => a.status === "failed" || a.status === "crashed").length;
      return `${failCount} apps are failing — start with the worst, or stop them all to triage offline.`;
    }
    case "single_failure": {
      const failed = (apps ?? []).find((a) => a.status === "failed" || a.status === "crashed");
      return `hassette is healthy overall — but ${failed?.display_name ?? "an app"} needs your attention.`;
    }
  }
}

// ---- Framework error banner -------------------------------------------------

function FrameworkErrorBanner({ issues }: { issues: BootIssue[] }) {
  if (!issues || issues.length === 0) return null;
  const top = issues[0];
  const errorCount = issues.filter((i) => i.severity === "err").length;
  const warnCount = issues.filter((i) => i.severity === "warn").length;

  const countText = [
    errorCount > 0 ? `${errorCount} error${errorCount > 1 ? "s" : ""}` : "",
    warnCount > 0 ? `${warnCount} warning${warnCount > 1 ? "s" : ""}` : "",
  ].filter(Boolean).join(" · ");

  return (
    <div
      class="ht-card ht-framework-error-banner"
      data-testid="framework-error-banner"
      role="alert"
    >
      <div class="ht-framework-error-banner__inner">
        <span class="ht-framework-error-banner__icon" aria-hidden="true">!</span>
        <span class="ht-framework-error-banner__count">
          hassette started with {countText}
        </span>
        <span class="ht-framework-error-banner__detail">
          {top.label} — {top.detail}
        </span>
        <a href="/config" class="ht-framework-error-banner__link">view all →</a>
      </div>
    </div>
  );
}

// ---- Hero card variants -----------------------------------------------------

function HeroCardFirstInstall() {
  const codeSnippet = `from hassette import App, D, states


class HelloApp(App):
    async def on_change(
        self,
        event: D.TypedStateChangeEvent[states.LightState],
    ):
        new = event.payload.data.new_state
        self.logger.info(
            "%s → %s",
            event.payload.data.entity_id,
            new.value if new else None,
        )`;

  const tomlSnippet = `[apps.hello]
filename = "hello.py"
class_name = "HelloApp"`;

  return (
    <div class="ht-hero-card ht-hero-card--first-install" data-testid="hero-card-first-install">
      <div class="ht-first-install__layout">
        <div class="ht-card ht-first-install__code-card">
          <h3 class="ht-first-install__section-title">your first app</h3>
          <p class="ht-first-install__hint">
            create <code>~/hassette/apps/hello.py</code> with this:
          </p>
          <div class="ht-card ht-first-install__snippet">
            <pre class="ht-first-install__pre"><code>{codeSnippet}</code></pre>
          </div>
          <p class="ht-first-install__hint">
            register it in <code>hassette.toml</code>:
          </p>
          <div class="ht-card ht-first-install__snippet">
            <pre class="ht-first-install__pre"><code>{tomlSnippet}</code></pre>
          </div>
          <p class="ht-first-install__note">
            hassette will hot-reload as soon as you save.
          </p>
        </div>
        <div class="ht-first-install__sidebar">
          <div class="ht-card ht-first-install__system-card">
            <h3 class="ht-first-install__section-title">system</h3>
            <div class="ht-first-install__service-list">
              {[
                ["bus", "ready"],
                ["scheduler", "0 jobs"],
                ["HA websocket", "connected"],
                ["file watcher", "watching apps/"],
              ].map(([name, sub]) => (
                <div key={name} class="ht-first-install__service-row">
                  <StatusShape kind="ok" size={8} />
                  <span class="ht-first-install__service-name">{name}</span>
                  <span class="ht-first-install__service-meta">{sub}</span>
                </div>
              ))}
            </div>
          </div>
          <div class="ht-card ht-first-install__appdaemon-card">
            <h3 class="ht-first-install__section-title">coming from AppDaemon?</h3>
            <p class="ht-first-install__hint">
              hassette is a fresh start, not a drop-in replacement. config moves from{" "}
              <code>apps.yaml</code> to <code>hassette.toml</code>.
            </p>
            <p class="ht-first-install__note">
              ↗ see the migration guide in the docs
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

interface HeroCardSingleFailureProps {
  apps: DashboardAppGridEntry[];
  errors: DashboardErrorEntry[] | null;
}

function HeroCardSingleFailure({ apps, errors }: HeroCardSingleFailureProps) {
  const failedApp = apps.find((a) => a.status === "failed" || a.status === "crashed");
  const latestError = errors?.find((e) => e.app_key === failedApp?.app_key);

  return (
    <div
      class="ht-hero-card ht-hero-card--failure"
      data-testid="hero-card-single-failure"
    >
      <div class="ht-hero-card__icon ht-hero-card__icon--err">!</div>
      <div class="ht-hero-card__body">
        <h3 class="ht-hero-card__title ht-hero-card__title--err">
          {failedApp?.display_name ?? failedApp?.app_key ?? "an app"} is failing
        </h3>
        {latestError && (
          <p class="ht-hero-card__subtitle">
            <span class="ht-hero-card__error-type">{latestError.error_type}</span>
            {latestError.error_message && (
              <span> — {latestError.error_message}</span>
            )}
            {latestError.kind === "handler" && latestError.handler_method && (
              <span class="ht-hero-card__location"> in {latestError.handler_method}()</span>
            )}
          </p>
        )}
        <div class="ht-hero-card__actions">
          {failedApp && (
            <a href={`/apps/${failedApp.app_key}`} class="ht-btn ht-btn--xs">
              open app →
            </a>
          )}
          <button type="button" class="ht-btn ht-btn--xs ht-btn--ghost" disabled aria-label="Traceback viewer coming soon">
            view traceback
          </button>
        </div>
      </div>
    </div>
  );
}

interface HeroCardMultipleFailuresProps {
  apps: DashboardAppGridEntry[];
}

function HeroCardMultipleFailures({ apps }: HeroCardMultipleFailuresProps) {
  const failedApps = apps.filter((a) => a.status === "failed" || a.status === "crashed");

  return (
    <div
      class="ht-hero-card ht-hero-card--failure ht-hero-card--multi"
      data-testid="hero-card-multiple-failures"
    >
      <div class="ht-hero-card__multi-header">
        <div class="ht-hero-card__icon ht-hero-card__icon--err">!</div>
        <div>
          <h3 class="ht-hero-card__title ht-hero-card__title--err">
            {failedApps.length} apps are failing
          </h3>
          <p class="ht-hero-card__subtitle">
            ranked by recency below — start with the top one.
          </p>
        </div>
      </div>
      <div class="ht-hero-card__failure-list">
        {failedApps.map((app) => (
          <a key={app.app_key} href={`/apps/${app.app_key}`} class="ht-hero-card__failure-row">
            <StatusShape kind="err" size={10} />
            <div class="ht-hero-card__failure-detail">
              <div class="ht-hero-card__failure-name-line">
                <span class="ht-hero-card__failure-name">{app.app_key}</span>
                <span class="ht-hero-card__failure-meta">
                  · {app.total_errors} error{app.total_errors !== 1 ? "s" : ""}
                </span>
              </div>
            </div>
            <span class="ht-badge ht-badge--danger ht-badge--sm">failing</span>
            <span class="ht-hero-card__failure-arrow">→</span>
          </a>
        ))}
      </div>
      <div class="ht-hero-card__multi-actions">
        <a href="/logs" class="ht-btn ht-btn--xs ht-btn--ghost">view all in logs →</a>
      </div>
    </div>
  );
}

interface HeroCardProps {
  state: SystemState;
  apps: DashboardAppGridEntry[] | null;
  errors: DashboardErrorEntry[] | null;
}

function HeroCard({ state, apps, errors }: HeroCardProps) {
  if (state === "first_install") return <HeroCardFirstInstall />;
  if (state === "healthy" || state === "quiet") return null;
  if (state === "single_failure") return <HeroCardSingleFailure apps={apps ?? []} errors={errors} />;
  return <HeroCardMultipleFailures apps={apps ?? []} />;
}

// ---- Sparkline --------------------------------------------------------------

interface SparklineProps {
  buckets: Array<{ ok: number; err: number }>;
  width?: number;
  height?: number;
}

function Sparkline({ buckets, width = 260, height = 36 }: SparklineProps) {
  if (!buckets || buckets.length < 2) return null;

  const totals = buckets.map((b) => b.ok + b.err);
  const maxVal = Math.max(...totals, 1);

  const points = buckets.map((b, i) => {
    const x = (i / (buckets.length - 1)) * width;
    const y = height - ((b.ok + b.err) / maxVal) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      class="ht-sparkline"
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke="var(--ok)"
        stroke-width="1.5"
        stroke-linejoin="round"
        stroke-linecap="round"
      />
    </svg>
  );
}

// ---- Three summary cards ----------------------------------------------------

interface YourAppsCardProps {
  apps: DashboardAppGridEntry[] | null;
}

const YOUR_APPS_COLLAPSED_COUNT = 8;

function YourAppsCard({ apps }: YourAppsCardProps) {
  const showAll = useRef(signal(false)).current;
  const allApps = [...(apps ?? [])].sort((a, b) =>
    (b.total_invocations + b.total_executions) - (a.total_invocations + a.total_executions),
  );
  const visible = showAll.value ? allApps : allApps.slice(0, YOUR_APPS_COLLAPSED_COUNT);
  const hasMore = allApps.length > YOUR_APPS_COLLAPSED_COUNT;

  return (
    <div class="ht-card ht-summary-card" data-testid="your-apps-card">
      <a href="/apps" class="ht-summary-card__title ht-summary-card__title--link">your apps</a>
      <div class="ht-app-list">
        {visible.map((app) => (
          <a key={app.app_key} href={`/apps/${app.app_key}`} class="ht-app-list__row">
            <StatusShape kind={statusToKind(app.status)} size={8} />
            <span class="ht-app-list__name">
              {app.app_key}
              {app.instance_count > 1 && (
                <span class="ht-app-list__instances"> ×{app.instance_count}</span>
              )}
            </span>
            <span class="ht-app-list__runs">{app.total_invocations + app.total_executions} runs</span>
          </a>
        ))}
        {allApps.length === 0 && (
          <p class="ht-summary-card__empty">no apps loaded</p>
        )}
      </div>
      {hasMore && (
        <button
          type="button"
          class="ht-btn ht-btn--xs ht-btn--ghost ht-show-more"
          onClick={() => { showAll.value = !showAll.value; }}
        >
          {showAll.value ? "Show less" : `Show all ${allApps.length}`}
        </button>
      )}
    </div>
  );
}

interface ActivityCardProps {
  kpis: DashboardKpis | null;
  isQuiet: boolean;
  timeLabel: string;
}

function ActivityCard({ kpis, isQuiet, timeLabel }: ActivityCardProps) {
  const totalRuns = (kpis?.total_invocations ?? 0) + (kpis?.total_executions ?? 0);
  const buckets = kpis?.activity_buckets ?? [];

  const errCount = (kpis?.total_errors ?? 0) + (kpis?.total_timed_out ?? 0)
    + (kpis?.total_job_errors ?? 0) + (kpis?.total_job_timed_out ?? 0);
  const okCount = Math.max(0, totalRuns - errCount);

  return (
    <div class="ht-card ht-summary-card" data-testid="activity-card">
      <h3 class="ht-summary-card__title">activity</h3>
      {isQuiet ? (
        <div class="ht-activity-quiet">
          <p class="ht-activity-quiet__count">0 runs / hour</p>
          <p class="ht-activity-quiet__note">
            apps are loaded and connected — they just haven't had anything to react to.
          </p>
        </div>
      ) : (
        <>
          <div class="ht-activity-big-number">
            {totalRuns.toLocaleString()}
          </div>
          <p class="ht-activity-label">runs {timeLabel}</p>
          {buckets.length >= 2 && <Sparkline buckets={buckets} />}
          <div class="ht-activity-breakdown">
            <span class="ht-activity-breakdown__ok">
              <StatusShape kind="ok" size={8} /> {Math.max(0, okCount)} ok
            </span>
            {errCount > 0 && (
              <span class="ht-activity-breakdown__err">
                <StatusShape kind="err" size={8} /> {errCount} err
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

interface ServiceEntry {
  name: string;
  status: string;
}

interface SystemCardProps {
  services: ServiceEntry[];
}

function humanizeServiceName(name: string): string {
  return name
    .replace(/Service$/, "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase();
}

const SYSTEM_CARD_COLLAPSED_COUNT = 8;

function SystemCard({ services }: SystemCardProps) {
  const showAll = useRef(signal(false)).current;
  const visible = showAll.value ? services : services.slice(0, SYSTEM_CARD_COLLAPSED_COUNT);
  const hasMore = services.length > SYSTEM_CARD_COLLAPSED_COUNT;

  return (
    <div class="ht-card ht-summary-card" data-testid="system-card">
      <h3 class="ht-summary-card__title">system</h3>
      <div class="ht-system-service-list">
        {visible.map((svc) => (
          <div key={svc.name} class="ht-system-service-row">
            <StatusShape kind={statusToKind(svc.status)} size={8} />
            <span class="ht-system-service-name">{humanizeServiceName(svc.name)}</span>
            <span class="ht-system-service-meta">{svc.status === "running" ? "ready" : svc.status}</span>
          </div>
        ))}
      </div>
      {hasMore && (
        <button
          type="button"
          class="ht-btn ht-btn--xs ht-btn--ghost ht-show-more"
          onClick={() => { showAll.value = !showAll.value; }}
        >
          {showAll.value ? "Show less" : `Show all ${services.length}`}
        </button>
      )}
    </div>
  );
}

// ---- Recent errors table ----------------------------------------------------

function shortErrorType(t: string | null | undefined): string {
  if (!t) return "";
  return lastDotSegment(t);
}

function getHandlerMethod(err: DashboardErrorEntry): string | null {
  if (err.kind === "handler") return err.handler_method ?? null;
  if (err.kind === "job") return err.job_name ?? null;
  return null;
}

function RecentErrorsTable({
  errors,
  tierFilter,
}: {
  errors: UseApiResult<DashboardErrorEntry[]>;
  tierFilter: Signal<SourceTier>;
}) {
  const staleRef = useRef<DashboardErrorEntry[] | null>(null);
  const currentData = errors.data.value;
  const isLoading = errors.loading.value;

  if (currentData && currentData.length > 0) {
    staleRef.current = currentData;
  }

  const displayErrors = currentData ?? staleRef.current;
  if (!displayErrors || displayErrors.length === 0) return null;
  const isRefetching = isLoading && currentData === null;

  return (
    <div
      class="ht-card ht-card--urgent ht-recent-errors"
      data-testid="recent-errors-table"
      style={isRefetching ? "opacity: 0.6; transition: opacity 0.15s ease" : undefined}
    >
      <div class="ht-recent-errors__header">
        <h3 class="ht-summary-card__title ht-recent-errors__title">recent errors</h3>
        <div class="ht-tier-toggle">
          {TIER_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              class={`ht-tier-toggle__btn${tierFilter.value === opt.value ? " ht-tier-toggle__btn--active" : ""}`}
              onClick={() => { tierFilter.value = opt.value; }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      <table class="ht-table ht-table--dense ht-recent-errors__table">
        <thead>
          <tr>
            <th class="ht-recent-errors__col-time">TIME</th>
            <th class="ht-recent-errors__col-app">APP</th>
            <th class="ht-recent-errors__col-location">LOCATION</th>
            <th class="ht-recent-errors__col-exception">EXCEPTION</th>
            <th class="ht-recent-errors__col-age">AGE</th>
          </tr>
        </thead>
        <tbody>
          {displayErrors.map((err, i) => {
            const errType = shortErrorType(err.error_type);
            const method = getHandlerMethod(err);
            const age = formatRelativeTime(err.execution_start_ts);
            const time = new Date(err.execution_start_ts * 1000).toLocaleTimeString("en-US", {
              hour: "numeric",
              minute: "2-digit",
              second: "2-digit",
              hour12: true,
            });

            return (
              <tr key={`${err.kind}-${err.execution_start_ts}-${i}`}>
                <td class="ht-recent-errors__time">{time}</td>
                <td class="ht-recent-errors__app">
                  {err.app_key ? (
                    <a href={`/apps/${err.app_key}`} class="ht-recent-errors__app-link">
                      {err.app_key}
                    </a>
                  ) : (
                    <span class="ht-text-muted">—</span>
                  )}
                </td>
                <td class="ht-recent-errors__location">
                  {method && (
                    <div class="ht-recent-errors__location-fn">
                      {method}()
                    </div>
                  )}
                  {err.source_location && (
                    <div class="ht-recent-errors__location-file">
                      {err.source_location}
                    </div>
                  )}
                </td>
                <td class="ht-recent-errors__exception">
                  {errType && (
                    <span class="ht-recent-errors__error-type">{errType}</span>
                  )}
                  {err.error_message && (
                    <span class="ht-recent-errors__error-msg">: {err.error_message}</span>
                  )}
                </td>
                <td class="ht-recent-errors__age">{age}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- Dashboard Page --------------------------------------------------------

export function DashboardPage() {
  useEffect(() => { document.title = "Dashboard - Hassette"; }, []);
  const { appStatus, invocationCompleted, executionCompleted, timePreset } = useAppState();

  const errorTierFilter = useSignal<SourceTier>("all");

  const kpis = useScopedApi((since) => getDashboardKpis(since, "app"));
  const appGrid = useScopedApi((since) => getDashboardAppGrid(since).then((r) => r.apps));
  const errors = useScopedApi(
    (since) => getDashboardErrors(since, errorTierFilter.value).then((r) => r.errors),
    { deps: [errorTierFilter.value] },
  );
  // System status for boot issues (uses useApi — not time-scoped)
  const systemStatus = useApi(() => getSystemStatus());

  // Debounce appStatus-driven refetches
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

  const hasData = kpis.data.value !== null && appGrid.data.value !== null;
  if (!hasData && (kpis.loading.value || appGrid.loading.value)) {
    return <Spinner />;
  }

  const systemState = detectSystemState(appGrid.data.value, kpis.data.value);
  const isQuiet = systemState === "quiet";
  const bootIssues = systemStatus.data.value?.boot_issues ?? [];

  const appCount = appGrid.data.value?.length ?? 0;
  const runsPerHour = kpis.data.value?.runs_per_hour ?? 0;

  return (
    <div class="ht-dashboard">
      <TelemetryDegradedBanner />

      {/* Greeting hero — state-tinted background */}
      <div class={`ht-dashboard-hero ht-dashboard-hero--${systemState.replace("_", "-")}`}>
        <div class="ht-dashboard-header">
          <div class="ht-dashboard-header__top">
            <h1 class="ht-dashboard-greeting">{getGreeting()}</h1>
            <span class="ht-dashboard-meta" data-testid="dashboard-metadata">
              {appCount} apps · {isQuiet ? 0 : Math.round(runsPerHour)} runs / hr
            </span>
          </div>
          <p class="ht-dashboard-subtitle" data-testid="dashboard-subtitle">
            {getSubtitle(systemState, appGrid.data.value)}
          </p>
        </div>

        {kpis.error.value && (
          <p class="ht-text-danger">Could not load dashboard stats — {kpis.error.value}</p>
        )}
        {appGrid.error.value && (
          <p class="ht-text-danger">Could not load apps — {appGrid.error.value}</p>
        )}

        {/* Stats strip */}
        {kpis.data.value && !isQuiet && (
          <div class="ht-dashboard-stats" data-testid="dashboard-stats-strip">
            <div class="ht-dashboard-stats__cell">
              <span class="ht-dashboard-stats__label">handlers</span>
              <span class="ht-dashboard-stats__value">{kpis.data.value.total_handlers + kpis.data.value.total_jobs}</span>
            </div>
            <div class="ht-dashboard-stats__cell">
              <span class="ht-dashboard-stats__label">invocations</span>
              <span class="ht-dashboard-stats__value">{kpis.data.value.total_invocations + kpis.data.value.total_executions}</span>
            </div>
            <div class="ht-dashboard-stats__cell">
              <span class="ht-dashboard-stats__label">success rate</span>
              <span class={`ht-dashboard-stats__value${kpis.data.value.error_rate > 0 ? " ht-dashboard-stats__value--warn" : ""}`}>
                {(100 - kpis.data.value.error_rate).toFixed(1)}%
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Framework error banner */}
      <FrameworkErrorBanner issues={bootIssues} />

      {/* Hero card */}
      <HeroCard
        state={systemState}
        apps={appGrid.data.value}
        errors={errors.data.value}
      />

      {/* Three summary cards */}
      <h2 class="ht-visually-hidden">Summary</h2>
      <div class="ht-summary-cards" data-testid="summary-cards">
        <YourAppsCard apps={appGrid.data.value} />
        <ActivityCard kpis={kpis.data.value} isQuiet={isQuiet} timeLabel={TIME_PRESET_LABELS[timePreset.value]} />
        <SystemCard services={systemStatus.data.value?.services ?? []} />
      </div>

      {/* Recent errors table */}
      <RecentErrorsTable
        errors={errors}
        tierFilter={errorTierFilter}
      />

    </div>
  );
}
