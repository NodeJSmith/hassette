import { useEffect, useRef } from "preact/hooks";
import {
  getDashboardAppGrid,
  getDashboardErrors,
  getDashboardKpis,
} from "../api/endpoints";
import { AppGrid } from "../components/dashboard/app-grid";
import { ErrorFeed } from "../components/dashboard/error-feed";
import { KpiStrip } from "../components/dashboard/kpi-strip";
import { IconHeart, IconWarning } from "../components/shared/icons";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";
import { useDebouncedEffect } from "../hooks/use-debounced-effect";
import { useAppState } from "../state/context";

export function DashboardPage() {
  useEffect(() => { document.title = "Dashboard - Hassette"; }, []);
  const { appStatus } = useAppState();

  const kpis = useApi(getDashboardKpis);
  const appGrid = useApi(() => getDashboardAppGrid().then((r) => r.apps));
  const errors = useApi(() => getDashboardErrors().then((r) => r.errors));

  // Debounce appStatus-driven refetches so rapid WS updates coalesce into one
  // round of API calls. maxWait caps staleness during bulk startup. Reconnection
  // refetches bypass this — they go through useApi's reconnectVersion signal.
  //
  // To prevent a phantom refetch when initial load completes, we track a version
  // counter that only increments on real WS-driven appStatus changes AFTER load.
  // The hook sees numeric changes (0→1→2...) instead of object reference changes,
  // avoiding the undefined→object transition that would trigger a false refetch.
  const initialLoadDone = !kpis.loading.value && !appGrid.loading.value && !errors.loading.value;
  const statusVersionRef = useRef(0);
  const prevStatusRef = useRef(appStatus.value);
  if (initialLoadDone && appStatus.value !== prevStatusRef.current) {
    prevStatusRef.current = appStatus.value;
    statusVersionRef.current += 1;
  }
  useDebouncedEffect(
    () => statusVersionRef.current,
    500,
    () => {
      void Promise.allSettled([kpis.refetch(), appGrid.refetch(), errors.refetch()]);
    },
    2000,
  );

  const isLoading = kpis.loading.value || appGrid.loading.value || errors.loading.value;

  if (isLoading) {
    return <Spinner />;
  }

  return (
    <div>
      {kpis.error.value && (
        <p class="ht-text-danger">Failed to load KPIs: {kpis.error.value}</p>
      )}
      <KpiStrip
        data={kpis.data.value}
        appCount={appGrid.data.value?.length ?? 0}
        runningCount={appGrid.data.value?.filter((a) => a.status === "running").length ?? 0}
      />

      <div class="ht-card ht-mb-4">
        <h2 class="ht-heading-5">
          <IconHeart />
          <span>App Health</span>
        </h2>
        {appGrid.error.value && (
          <p class="ht-text-danger">Failed to load app grid: {appGrid.error.value}</p>
        )}
        <AppGrid apps={appGrid.data.value} />
        <div class="ht-mt-3">
          <a href="/apps" class="ht-btn ht-btn--sm ht-btn--link">Manage Apps</a>
        </div>
      </div>

      {errors.error.value ? (
        <div class="ht-empty-section ht-mb-4">
          <IconWarning />
          <span class="ht-text-danger ht-text-xs">Failed to load errors: {errors.error.value}</span>
        </div>
      ) : errors.data.value && errors.data.value.length > 0 ? (
        <div class="ht-card ht-mb-4">
          <h2 class="ht-heading-5">
            <IconWarning />
            <span>Recent Errors</span>
          </h2>
          <ErrorFeed errors={errors.data.value} />
        </div>
      ) : (
        <div class="ht-empty-section ht-mb-4">
          <IconWarning />
          <span class="ht-text-muted ht-text-xs">No recent errors. All systems healthy.</span>
        </div>
      )}

      {/* Session info bar */}
      <div class="ht-session-bar" data-testid="session-info">
        <span class="ht-session-bar__item">
          <span class="ht-text-xs ht-text-muted">Hassette</span>
        </span>
        {kpis.data.value?.uptime_seconds !== null && kpis.data.value?.uptime_seconds !== undefined && (
          <span class="ht-session-bar__item">
            <span class="ht-text-xs ht-text-muted">Started</span>
            <span class="ht-text-xs">
              {new Date(Date.now() - (kpis.data.value.uptime_seconds * 1000)).toLocaleString()}
            </span>
          </span>
        )}
      </div>
    </div>
  );
}
