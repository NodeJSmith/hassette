import { useEffect, useRef } from "preact/hooks";
import { useSignal, type Signal } from "@preact/signals";
import type { UseApiResult } from "../hooks/use-api";
import {
  getDashboardAppGrid,
  getDashboardErrors,
  getDashboardKpis,
} from "../api/endpoints";
import type { SourceTier, DashboardAppGridEntry, DashboardKpis, DashboardErrorEntry } from "../api/endpoints";
import { AppGrid } from "../components/dashboard/app-grid";
import { ErrorFeed } from "../components/dashboard/error-feed";
import { FrameworkHealth } from "../components/dashboard/framework-health";
import { KpiStrip } from "../components/dashboard/kpi-strip";
import { ServiceStatusPanel } from "../components/dashboard/service-status-panel";
import { TelemetryDegradedBanner } from "../components/layout/alert-banner";
import { IconCheck, IconInfo, IconWarning } from "../components/shared/icons";
import { Spinner } from "../components/shared/spinner";
import { useScopedApi } from "../hooks/use-scoped-api";
import { useDebouncedEffect } from "../hooks/use-debounced-effect";
import { useAppState } from "../state/context";

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

// ---- Hero Card components --------------------------------------------------

function HeroCardHealthy() {
  return (
    <div class="ht-hero-card ht-hero-card--healthy" data-testid="hero-card-healthy">
      <div class="ht-hero-card__icon">
        <IconCheck />
      </div>
      <div class="ht-hero-card__body">
        <h1 class="ht-hero-card__title">Everything's running smoothly</h1>
        <p class="ht-hero-card__subtitle">All apps are active and healthy.</p>
      </div>
    </div>
  );
}

function HeroCardQuiet() {
  return (
    <div class="ht-hero-card ht-hero-card--quiet" data-testid="hero-card-quiet">
      <div class="ht-hero-card__body">
        <h1 class="ht-hero-card__title">All quiet</h1>
        <p class="ht-hero-card__subtitle">Apps are loaded but haven't seen any activity yet.</p>
      </div>
    </div>
  );
}

function HeroCardFirstInstall() {
  return (
    <div class="ht-hero-card ht-hero-card--first-install" data-testid="hero-card-first-install">
      <div class="ht-hero-card__body">
        <h1 class="ht-hero-card__title">Welcome to Hassette</h1>
        <p class="ht-hero-card__subtitle">No apps loaded yet. Get started by creating your first app.</p>
      </div>
    </div>
  );
}

interface HeroCardSingleFailureProps {
  apps: DashboardAppGridEntry[];
}

function HeroCardSingleFailure({ apps }: HeroCardSingleFailureProps) {
  const failedApp = apps.find((a) => a.status === "failed" || a.status === "crashed");
  return (
    <div class="ht-hero-card ht-hero-card--failure" data-testid="hero-card-single-failure">
      <div class="ht-hero-card__icon ht-hero-card__icon--err">
        <IconWarning />
      </div>
      <div class="ht-hero-card__body">
        <h1 class="ht-hero-card__title">
          {failedApp ? failedApp.display_name : "An app"} has failed
        </h1>
        <p class="ht-hero-card__subtitle">Check the error feed below for details.</p>
      </div>
    </div>
  );
}

interface HeroCardMultipleFailuresProps {
  apps: DashboardAppGridEntry[];
}

function HeroCardMultipleFailures({ apps }: HeroCardMultipleFailuresProps) {
  const failedCount = apps.filter((a) => a.status === "failed" || a.status === "crashed").length;
  return (
    <div class="ht-hero-card ht-hero-card--failure" data-testid="hero-card-multiple-failures">
      <div class="ht-hero-card__icon ht-hero-card__icon--err">
        <IconWarning />
      </div>
      <div class="ht-hero-card__body">
        <h1 class="ht-hero-card__title">{failedCount} apps failed</h1>
        <p class="ht-hero-card__subtitle">Multiple apps are reporting failures. Check the error feed below.</p>
      </div>
    </div>
  );
}

interface HeroCardProps {
  state: SystemState;
  apps: DashboardAppGridEntry[] | null;
}

function HeroCard({ state, apps }: HeroCardProps) {
  if (state === "first_install") return <HeroCardFirstInstall />;
  if (state === "healthy") return <HeroCardHealthy />;
  if (state === "quiet") return <HeroCardQuiet />;
  if (state === "single_failure") return <HeroCardSingleFailure apps={apps ?? []} />;
  return <HeroCardMultipleFailures apps={apps ?? []} />;
}

// ---- Recent Errors Section -------------------------------------------------

function RecentErrorsSection({
  errors,
  tierFilter,
  filterInteracted,
}: {
  errors: UseApiResult<DashboardErrorEntry[]>;
  tierFilter: Signal<SourceTier>;
  filterInteracted: Signal<boolean>;
}) {
  if (errors.error.value) {
    return (
      <div class="ht-empty-section ht-mb-6">
        <IconWarning />
        <span class="ht-text-danger ht-text-xs">Failed to load errors: {errors.error.value}</span>
      </div>
    );
  }

  const hasErrors = errors.data.value && errors.data.value.length > 0;
  const showCard = errors.loading.value || hasErrors || tierFilter.value !== "all" || filterInteracted.value;

  if (!showCard) {
    return (
      <div class="ht-empty-section ht-mb-6">
        <IconCheck />
        <span class="ht-text-muted ht-text-xs">No recent errors. All systems healthy.</span>
      </div>
    );
  }

  const headingIcon = errors.loading.value ? null : hasErrors ? <IconWarning /> : <IconCheck />;

  return (
    <div class={`ht-card${hasErrors ? " ht-card--urgent" : ""} ht-mb-6`}>
      <h2 class="ht-heading-5">
        {headingIcon}
        <span>Recent Errors</span>
        <span class="ht-info-hint" title="Showing errors from the last 24 hours" aria-label="Showing errors from the last 24 hours"><IconInfo /></span>
        <div class="ht-tier-toggle">
          {TIER_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              class={`ht-tier-toggle__btn${tierFilter.value === opt.value ? " ht-tier-toggle__btn--active" : ""}`}
              onClick={() => { tierFilter.value = opt.value; filterInteracted.value = true; }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </h2>
      {errors.loading.value ? (
        <Spinner />
      ) : hasErrors ? (
        <ErrorFeed errors={errors.data.value!} />
      ) : (
        <p class="ht-text-muted ht-text-xs">No errors for this filter.</p>
      )}
    </div>
  );
}

// ---- Dashboard Page --------------------------------------------------------

export function DashboardPage() {
  useEffect(() => { document.title = "Dashboard - Hassette"; }, []);
  const { appStatus, invocationCompleted, executionCompleted } = useAppState();

  const errorTierFilter = useSignal<SourceTier>("all");
  const errorFilterInteracted = useSignal(false);

  const kpis = useScopedApi((since) => getDashboardKpis(since));
  const appGrid = useScopedApi((since) => getDashboardAppGrid(since).then((r) => r.apps));
  const errors = useScopedApi(
    (since) => getDashboardErrors(since, errorTierFilter.value).then((r) => r.errors),
    { deps: [errorTierFilter.value] },
  );

  // Debounce appStatus-driven refetches so rapid WS updates coalesce into one
  // round of API calls. maxWait caps staleness during bulk startup. Reconnection
  // refetches bypass this — they go through useApi's reconnectVersion signal.
  //
  // To prevent a phantom refetch when initial load completes, we track a version
  // counter that only increments on real WS-driven appStatus changes AFTER load.
  // The hook sees numeric changes (0→1→2...) instead of object reference changes,
  // avoiding the undefined→object transition that would trigger a false refetch.
  const initialLoadDone = !kpis.loading.value && !appGrid.loading.value;
  const statusVersionRef = useRef(0);
  const prevStatusRef = useRef(appStatus.value);
  const prevInvRef = useRef(invocationCompleted.value);
  const prevExecRef = useRef(executionCompleted.value);

  useEffect(() => {
    if (!initialLoadDone) return;
    let bumped = false;
    if (appStatus.value !== prevStatusRef.current) {
      prevStatusRef.current = appStatus.value;
      bumped = true;
    }
    if (invocationCompleted.value !== prevInvRef.current) {
      prevInvRef.current = invocationCompleted.value;
      bumped = true;
    }
    if (executionCompleted.value !== prevExecRef.current) {
      prevExecRef.current = executionCompleted.value;
      bumped = true;
    }
    if (bumped) statusVersionRef.current += 1;
  });

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

  return (
    <div>
      <TelemetryDegradedBanner />

      {kpis.error.value && (
        <p class="ht-text-danger">Failed to load KPIs: {kpis.error.value}</p>
      )}

      <HeroCard state={systemState} apps={appGrid.data.value} />

      <KpiStrip
        data={kpis.data.value}
        appCount={appGrid.data.value?.length ?? 0}
        runningCount={appGrid.data.value?.filter((a) => a.status === "running").length ?? 0}
      />

      <div class="ht-dashboard-section ht-mb-6">
        <h2 class="ht-heading-5"><a href="/apps" class="ht-heading-link">App Health</a></h2>
        {appGrid.error.value && (
          <p class="ht-text-danger">Failed to load app grid: {appGrid.error.value}</p>
        )}
        <AppGrid apps={appGrid.data.value} />
      </div>

      <RecentErrorsSection
        errors={errors}
        tierFilter={errorTierFilter}
        filterInteracted={errorFilterInteracted}
      />

      <ServiceStatusPanel />
      <FrameworkHealth />
    </div>
  );
}
