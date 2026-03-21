import { useCallback, useEffect } from "preact/hooks";
import {
  getDashboardAppGrid,
  getDashboardErrors,
  getDashboardKpis,
} from "../api/endpoints";
import { AppGrid } from "../components/dashboard/app-grid";
import { ErrorFeed } from "../components/dashboard/error-feed";
import { KpiStrip } from "../components/dashboard/kpi-strip";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";
import { useAppState } from "../state/context";

export function DashboardPage() {
  const { appStatus } = useAppState();

  const kpis = useApi(getDashboardKpis);
  const appGrid = useApi(() => getDashboardAppGrid().then((r) => r.apps));
  const errors = useApi(() => getDashboardErrors().then((r) => r.errors));

  const lastStatus = appStatus.value;
  const refetchAppGrid = useCallback(() => {
    void appGrid.refetch();
  }, [appGrid.refetch]);

  useEffect(() => {
    if (Object.keys(lastStatus).length > 0) {
      refetchAppGrid();
    }
  }, [lastStatus, refetchAppGrid]);

  const isLoading = kpis.loading.value && appGrid.loading.value && errors.loading.value;

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
          <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />
            <path d="M3.22 12H9.5l.5-1 2 4.5 2-7 1.5 3.5h5.27" />
          </svg>
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

      <div class="ht-card ht-mb-4">
        <h2 class="ht-heading-5">
          <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />
            <path d="M12 9v4" /><path d="M12 17h.01" />
          </svg>
          <span>Recent Errors</span>
        </h2>
        {errors.error.value && (
          <p class="ht-text-danger">Failed to load errors: {errors.error.value}</p>
        )}
        <ErrorFeed errors={errors.data.value} />
      </div>

      {/* Session info bar */}
      <div class="ht-session-bar" data-testid="session-info">
        <span class="ht-session-bar__item">
          <span class="ht-text-xs ht-text-muted">Hassette</span>
        </span>
        {kpis.data.value?.uptime_seconds != null && (
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
