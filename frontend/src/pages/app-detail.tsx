import { getAppHealth, getAppJobs, getAppListeners, getManifests } from "../api/endpoints";
import { ActionButtons } from "../components/apps/action-buttons";
import { HandlerList } from "../components/app-detail/handler-list";
import { HealthStrip } from "../components/app-detail/health-strip";
import { JobList } from "../components/app-detail/job-list";
import { StatusBadge } from "../components/shared/status-badge";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";
import { useAppState } from "../state/context";

interface Props {
  params: { key: string };
}

export function AppDetailPage({ params }: Props) {
  const appKey = params.key;
  const { appStatus } = useAppState();

  const manifests = useApi(getManifests);
  const health = useApi(() => getAppHealth(appKey));
  const listeners = useApi(() => getAppListeners(appKey));
  const jobs = useApi(() => getAppJobs(appKey));

  const manifest = manifests.data.value?.manifests.find((m) => m.app_key === appKey);
  const liveStatus = appStatus.value[appKey]?.status ?? manifest?.status ?? "unknown";

  const isLoading = health.loading.value && listeners.loading.value;
  if (isLoading) return <Spinner />;

  return (
    <div>
      <div class="ht-level" style={{ marginBottom: "var(--ht-sp-4)" }}>
        <div class="ht-level-start">
          <h1>{manifest?.display_name ?? appKey}</h1>
          <StatusBadge status={liveStatus} />
        </div>
        <div class="ht-level-end">
          <ActionButtons appKey={appKey} status={liveStatus} />
        </div>
      </div>

      <HealthStrip health={health.data.value} status={liveStatus} />

      <section style={{ marginTop: "var(--ht-sp-6)" }}>
        <h2>Handlers</h2>
        {listeners.error.value && <p class="ht-text-danger">{listeners.error.value}</p>}
        <HandlerList listeners={listeners.data.value} />
      </section>

      <section style={{ marginTop: "var(--ht-sp-6)" }}>
        <h2>Scheduled Jobs</h2>
        {jobs.error.value && <p class="ht-text-danger">{jobs.error.value}</p>}
        <JobList jobs={jobs.data.value} />
      </section>
    </div>
  );
}
