import { useCallback, useEffect } from "preact/hooks";
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

      {errors.data.value && errors.data.value.length > 0 ? (
        <div class="ht-card ht-mb-4">
          <h2 class="ht-heading-5">
            <IconWarning />
            <span>Recent Errors</span>
          </h2>
          {errors.error.value && (
            <p class="ht-text-danger">Failed to load errors: {errors.error.value}</p>
          )}
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
