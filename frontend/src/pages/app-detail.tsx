import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { useSearch, useLocation } from "wouter";
import { getAppHealth, getAppJobs, getAppListeners, getManifests, reloadApp, startApp, stopApp } from "../api/endpoints";
import { ErrorDisplay } from "../components/app-detail/error-display";
import { HandlersTab } from "../components/app-detail/handlers-tab";
import { HealthStrip } from "../components/app-detail/health-strip";
import { ConfirmDialog } from "../components/shared/confirm-dialog";
import { LogTable } from "../components/shared/log-table";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";
import { useScopedApi } from "../hooks/use-scoped-api";
import { useAppState } from "../state/context";
import { statusToKind } from "../utils/status";
import { StatusShape } from "../components/shared/status-shape";

type TabId = "handlers" | "code" | "logs" | "config";

interface Props {
  params: { key: string; index?: string };
}

function ActionButtons({ appKey, status }: { appKey: string; status: string }) {
  const loading = useRef(signal(false)).current;
  const error = useRef(signal<string | null>(null)).current;
  const showStopConfirm = useRef(signal(false)).current;

  const exec = async (action: (key: string) => Promise<unknown>) => {
    if (loading.value) return;
    error.value = null;
    loading.value = true;
    try {
      await action(appKey);
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  };

  useEffect(() => { error.value = null; }, [status, error]);

  const canStart = status === "stopped" || status === "failed" || status === "disabled";
  const canStop = status === "running";
  const canReload = status === "running";

  return (
    <>
      <div class="ht-btn-group" data-testid="action-buttons">
        {canStart && (
          <button
            class="ht-btn ht-btn--sm ht-btn--success"
            data-testid={`btn-start-${appKey}`}
            disabled={loading.value}
            onClick={() => void exec(startApp)}
            aria-label="Start app"
          >
            Start
          </button>
        )}
        {canReload && (
          <button
            class="ht-btn ht-btn--sm"
            data-testid={`btn-reload-${appKey}`}
            disabled={loading.value}
            onClick={() => void exec(reloadApp)}
            aria-label="Reload app"
          >
            Reload
          </button>
        )}
        {canStop && (
          <button
            class="ht-btn ht-btn--sm ht-btn--warning"
            data-testid={`btn-stop-${appKey}`}
            disabled={loading.value}
            onClick={() => { showStopConfirm.value = true; }}
            aria-label="Stop app"
          >
            Stop
          </button>
        )}
      </div>
      {showStopConfirm.value && (
        <ConfirmDialog
          title="Stop app?"
          body={`Stop "${appKey}"? It will stop processing events until restarted.`}
          confirmLabel="Stop"
          tone="danger"
          onConfirm={() => {
            showStopConfirm.value = false;
            void exec(stopApp);
          }}
          onCancel={() => { showStopConfirm.value = false; }}
        />
      )}
      {error.value && <p class="ht-text-danger ht-text-sm">{error.value}</p>}
    </>
  );
}

export function AppDetailPage({ params }: Props) {
  const appKey = params.key;
  const parsed = params.index !== undefined ? parseInt(params.index, 10) : 0;
  const instanceIndex = Number.isFinite(parsed) ? parsed : 0;
  const { appStatus } = useAppState();
  const [, navigate] = useLocation();
  const searchString = useSearch();

  const activeTab = useRef(signal<TabId>("handlers")).current;

  // Parse focus query param for auto-selecting a handler
  const focusMethod = useRef<string | null>(null);
  if (focusMethod.current === null) {
    const params_ = new URLSearchParams(searchString);
    focusMethod.current = params_.get("focus");
    // Clear focus param from URL to avoid stale auto-select on re-navigation
    if (focusMethod.current) {
      const next = new URLSearchParams(searchString);
      next.delete("focus");
      const newSearch = next.toString();
      history.replaceState(null, "", newSearch ? `?${newSearch}` : window.location.pathname);
    }
  }

  const manifests = useApi(getManifests);
  const health = useScopedApi((since) => getAppHealth(appKey, instanceIndex, since), { deps: [appKey, instanceIndex] });
  const listeners = useScopedApi(
    (since) => getAppListeners(appKey, instanceIndex, since), { deps: [appKey, instanceIndex] },
  );
  const jobs = useScopedApi((since) => getAppJobs(appKey, instanceIndex, since), { deps: [appKey, instanceIndex] });

  // Immediate fallback title on mount
  useEffect(() => { document.title = "App - Hassette"; }, []);

  const manifest = manifests.data.value?.manifests.find((m) => m.app_key === appKey);

  // Update title when manifest loads; reset on unmount
  const displayName = manifest?.display_name;
  useEffect(() => {
    if (displayName) document.title = `${displayName} - Hassette`;
    return () => { document.title = "Hassette"; };
  }, [displayName]);

  const isMultiInstance = (manifest?.instance_count ?? 0) > 1;
  const currentInstance = manifest?.instances?.find((i) => i.index === instanceIndex);
  const liveStatus = appStatus.value[appKey]?.status ?? currentInstance?.status ?? manifest?.status ?? "unknown";

  const hasData = manifests.data.value !== null && health.data.value !== null
    && listeners.data.value !== null && jobs.data.value !== null;
  const initialLoading = !hasData && (health.loading.value || listeners.loading.value
    || jobs.loading.value || manifests.loading.value);
  if (initialLoading) return <Spinner />;

  const Tab = ({ id, label }: { id: TabId; label: string }) => (
    <button
      type="button"
      role="tab"
      aria-selected={activeTab.value === id}
      class={`ht-tab-btn${activeTab.value === id ? " ht-tab-btn--active" : ""}`}
      onClick={() => { activeTab.value = id; }}
    >
      {label}
    </button>
  );

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
      <div class="ht-level ht-mb-2">
        <div class="ht-level-start">
          <div class="ht-level-item">
            <h1 class="ht-heading-4" data-testid="app-title">
              <StatusShape kind={statusToKind(liveStatus)} size={14} />
              <span style="margin-left:0.5rem">{manifest?.display_name ?? appKey}</span>
            </h1>
          </div>
        </div>
        <div class="ht-level-end">
          <ActionButtons appKey={appKey} status={liveStatus} />
        </div>
      </div>

      {/* App key + auto-loaded badge */}
      <div class="ht-level ht-mb-3">
        <code class="ht-text-mono ht-text-sm" data-testid="app-key-mono">{appKey}</code>
        {manifest?.auto_loaded && (
          <span class="ht-badge ht-badge--neutral" data-testid="auto-loaded-badge">auto</span>
        )}
      </div>

      {/* Instance metadata */}
      {manifest && (
        <p class="ht-text-muted ht-text-sm ht-mb-3" data-testid="instance-meta">
          Instance {instanceIndex}
          {currentInstance?.owner_id && <> &middot; PID {currentInstance.owner_id}</>}
        </p>
      )}

      {/* Instance switcher (multi-instance only) */}
      {isMultiInstance && manifest?.instances && (
        <div class="ht-mb-4">
          <label class="ht-detail-label ht-mr-2" htmlFor="instance-select">Instance</label>
          <div class="ht-select ht-select--sm ht-select--inline">
            <select
              id="instance-select"
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

      {/* Error banner for failed/crashed apps */}
      {manifest?.error_message && (
        <ErrorDisplay
          errorMessage={manifest.error_message}
          errorTraceback={manifest.error_traceback ?? null}
        />
      )}

      {/* Health strip */}
      <div class="ht-mb-6">
        <HealthStrip health={health.data.value} />
      </div>

      {/* Tab strip */}
      <div class="ht-tab-strip ht-mb-4" role="tablist" aria-label="App sections">
        <Tab id="handlers" label="Handlers" />
        <Tab id="code" label="Code" />
        <Tab id="logs" label="Logs" />
        <Tab id="config" label="Config" />
      </div>

      {/* Tab content */}
      {activeTab.value === "handlers" && (
        <HandlersTab
          appKey={appKey}
          instanceIndex={instanceIndex}
          listeners={listeners.data.value ?? []}
          jobs={jobs.data.value ?? []}
          focusMethod={focusMethod.current}
        />
      )}
      {activeTab.value === "code" && (
        <div class="ht-card ht-text-muted ht-text-sm" data-testid="code-tab-placeholder">
          Code viewer — coming in WP08.
        </div>
      )}
      {activeTab.value === "logs" && (
        <div class="ht-card" data-testid="logs-section">
          <LogTable showAppColumn={false} appKey={appKey} />
        </div>
      )}
      {activeTab.value === "config" && (
        <div class="ht-card ht-text-muted ht-text-sm" data-testid="config-tab-placeholder">
          Config editor — coming in WP08.
        </div>
      )}
    </div>
  );
}
