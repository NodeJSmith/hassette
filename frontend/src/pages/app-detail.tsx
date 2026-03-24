import { getAppHealth, getAppJobs, getAppListeners, getManifests } from "../api/endpoints";
import { ErrorDisplay } from "../components/app-detail/error-display";
import { ActionButtons } from "../components/apps/action-buttons";
import { HandlerList } from "../components/app-detail/handler-list";
import { HealthStrip } from "../components/app-detail/health-strip";
import { IconBell, IconClock, IconLayers, IconScroll } from "../components/shared/icons";
import { JobList } from "../components/app-detail/job-list";
import { LogTable } from "../components/shared/log-table";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";
import { useAppState } from "../state/context";
import { useLocation } from "wouter";

interface Props {
  params: { key: string; index?: string };
}

export function AppDetailPage({ params }: Props) {
  const appKey = params.key;
  const instanceIndex = params.index ? parseInt(params.index, 10) : 0;
  const { appStatus } = useAppState();
  const [, navigate] = useLocation();

  const manifests = useApi(getManifests);
  const health = useApi(() => getAppHealth(appKey, instanceIndex), [appKey, instanceIndex]);
  const listeners = useApi(() => getAppListeners(appKey, instanceIndex), [appKey, instanceIndex]);
  const jobs = useApi(() => getAppJobs(appKey, instanceIndex), [appKey, instanceIndex]);

  const manifest = manifests.data.value?.manifests.find((m) => m.app_key === appKey);
  const isMultiInstance = (manifest?.instance_count ?? 0) > 1;
  const currentInstance = manifest?.instances.find((i) => i.index === instanceIndex);
  const liveStatus = appStatus.value[appKey]?.status ?? currentInstance?.status ?? manifest?.status ?? "unknown";
  const listenerCount = listeners.data.value?.length ?? 0;
  const jobCount = jobs.data.value?.length ?? 0;

  const isLoading = health.loading.value || listeners.loading.value || jobs.loading.value || manifests.loading.value;
  if (isLoading) return <Spinner />;

  return (
    <div>
      {/* Breadcrumb */}
      <nav class="ht-breadcrumb ht-mb-3" aria-label="Breadcrumb">
        <a href="/apps">Apps</a>
        <span class="ht-breadcrumb__separator" aria-hidden="true">/</span>
        <span class="ht-breadcrumb__current" aria-current="page">
          {manifest?.display_name ?? appKey}
        </span>
      </nav>

      {/* App header */}
      <div class="ht-level ht-mb-4">
        <div class="ht-level-start">
          <div class="ht-level-item">
            <h1 class="ht-heading-4" data-testid="app-title">
              <IconLayers />
              <span>{manifest?.display_name ?? appKey}</span>
            </h1>
          </div>
        </div>
        <div class="ht-level-end">
          <div class="ht-level-item ht-btn-group">
            <ActionButtons appKey={appKey} status={liveStatus} />
          </div>
        </div>
      </div>

      {/* Instance metadata */}
      {manifest && (
        <p class="ht-text-muted ht-text-sm ht-mb-3" data-testid="instance-meta">
          Instance {instanceIndex}
          {currentInstance?.instance_name && <> &middot; PID {currentInstance.instance_name}</>}
        </p>
      )}

      {/* Instance switcher (multi-instance only) */}
      {isMultiInstance && manifest?.instances && (
        <div class="ht-mb-4">
          <label class="ht-detail-label ht-mr-2">Instance</label>
          <div class="ht-select ht-select--sm" style={{ display: "inline-block" }}>
            <select
              value={instanceIndex}
              onChange={(e) => {
                const idx = (e.target as HTMLSelectElement).value;
                navigate(`/apps/${appKey}/${idx}`);
              }}
            >
              {manifest.instances.map((inst) => (
                <option key={inst.index} value={inst.index}>
                  {inst.instance_name} ({inst.status})
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Error display for failed apps */}
      {manifest?.error_message && (
        <ErrorDisplay
          errorMessage={manifest.error_message}
          errorTraceback={manifest.error_traceback ?? null}
        />
      )}

      {/* Health strip */}
      <div class="ht-mb-8">
        <HealthStrip health={health.data.value} status={liveStatus} />
      </div>

      {/* Event Handlers */}
      <div class="ht-card ht-mb-8">
        <h2 class="ht-heading-5" data-testid="handlers-heading">
          <IconBell />
          Event Handlers ({listenerCount} registered)
        </h2>
        {listeners.error.value && <p class="ht-text-danger">{listeners.error.value}</p>}
        {listenerCount > 0 && <HandlerList listeners={listeners.data.value} />}
      </div>

      {/* Scheduled Jobs */}
      <div class="ht-card ht-mb-8">
        <h2 class="ht-heading-5" data-testid="jobs-heading">
          <IconClock />
          Scheduled Jobs ({jobCount} active)
        </h2>
        {jobs.error.value && <p class="ht-text-danger">{jobs.error.value}</p>}
        {jobCount > 0 && <JobList jobs={jobs.data.value} />}
      </div>

      {/* Logs */}
      <div class="ht-card" data-testid="logs-section">
        <h2 class="ht-heading-5">
          <IconScroll />
          Logs
        </h2>
        <LogTable showAppColumn={false} appKey={appKey} />
      </div>
    </div>
  );
}
