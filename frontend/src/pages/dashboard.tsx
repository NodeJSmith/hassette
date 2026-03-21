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

  // Refetch app grid when an app status changes via WS
  const lastStatus = appStatus.value;
  const refetchAppGrid = useCallback(() => {
    void appGrid.refetch();
  }, [appGrid.refetch]);

  useEffect(() => {
    // Skip initial render — only refetch on subsequent status changes
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
      <h1>Dashboard</h1>

      {kpis.error.value && (
        <p class="ht-text-danger">Failed to load KPIs: {kpis.error.value}</p>
      )}
      <KpiStrip data={kpis.data.value} />

      <section style={{ marginTop: "var(--ht-sp-6)" }}>
        <h2>Apps</h2>
        {appGrid.error.value && (
          <p class="ht-text-danger">Failed to load app grid: {appGrid.error.value}</p>
        )}
        <AppGrid apps={appGrid.data.value} />
      </section>

      <section style={{ marginTop: "var(--ht-sp-6)" }}>
        <h2>Recent Errors</h2>
        {errors.error.value && (
          <p class="ht-text-danger">Failed to load errors: {errors.error.value}</p>
        )}
        <ErrorFeed errors={errors.data.value} />
      </section>
    </div>
  );
}
