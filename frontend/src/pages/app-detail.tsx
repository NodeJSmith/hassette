import { getAppHealth, getAppJobs, getAppListeners, getManifests } from "../api/endpoints";
import { ErrorDisplay } from "../components/app-detail/error-display";
import { ActionButtons } from "../components/apps/action-buttons";
import { HandlerList } from "../components/app-detail/handler-list";
import { HealthStrip } from "../components/app-detail/health-strip";
import { JobList } from "../components/app-detail/job-list";
import { LogTable } from "../components/shared/log-table";
import { StatusBadge } from "../components/shared/status-badge";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";
import { useAppState } from "../state/context";

interface Props {
  params: { key: string; index?: string };
}

// Lucide SVG icons
const IconLayers = () => (
  <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="m21 16-9 5-9-5" /><path d="m21 12-9 5-9-5" /><path d="M12 2l9 5-9 5-9-5 9-5Z" />
  </svg>
);
const IconBell = () => (
  <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
  </svg>
);
const IconClock = () => (
  <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
  </svg>
);
const IconScroll = () => (
  <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M15 12h-5" /><path d="M15 8h-5" /><path d="M19 17V5a2 2 0 0 0-2-2H4" />
    <path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2" />
  </svg>
);

export function AppDetailPage({ params }: Props) {
  const appKey = params.key;
  const instanceIndex = params.index ? parseInt(params.index, 10) : 0;
  const { appStatus } = useAppState();

  const manifests = useApi(getManifests);
  const health = useApi(() => getAppHealth(appKey, instanceIndex));
  const listeners = useApi(() => getAppListeners(appKey, instanceIndex));
  const jobs = useApi(() => getAppJobs(appKey, instanceIndex));

  const manifest = manifests.data.value?.manifests.find((m) => m.app_key === appKey);
  const isMultiInstance = (manifest?.instance_count ?? 0) > 1;
  const currentInstance = manifest?.instances.find((i) => i.index === instanceIndex);
  const liveStatus = appStatus.value[appKey]?.status ?? currentInstance?.status ?? manifest?.status ?? "unknown";
  const listenerCount = listeners.data.value?.length ?? 0;
  const jobCount = (jobs.data.value as unknown[] | null)?.length ?? 0;

  const isLoading = health.loading.value && listeners.loading.value;
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
              <StatusBadge status={liveStatus} />
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
                window.location.href = `/apps/${appKey}/${idx}`;
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
      <HealthStrip health={health.data.value} status={liveStatus} />

      {/* Event Handlers */}
      <div class="ht-card ht-mb-4">
        <h2 class="ht-heading-5" data-testid="handlers-heading">
          <IconBell />
          Event Handlers ({listenerCount} registered)
        </h2>
        {listeners.error.value && <p class="ht-text-danger">{listeners.error.value}</p>}
        <HandlerList listeners={listeners.data.value} />
      </div>

      {/* Scheduled Jobs */}
      <div class="ht-card ht-mb-4">
        <h2 class="ht-heading-5" data-testid="jobs-heading">
          <IconClock />
          Scheduled Jobs ({jobCount} active)
        </h2>
        {jobs.error.value && <p class="ht-text-danger">{jobs.error.value}</p>}
        <JobList jobs={jobs.data.value} />
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
