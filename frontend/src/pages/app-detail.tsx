import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { useSearch, useLocation } from "wouter";
import { getAppJobs, getAppListeners, getManifests } from "../api/endpoints";
import type { AppInstance } from "../api/endpoints";
import { ActionButtons } from "../components/apps/action-buttons";
import { CodeTab } from "../components/app-detail/code-tab";
import { ConfigTab } from "../components/app-detail/config-tab";
import { ErrorDisplay } from "../components/app-detail/error-display";
import { HandlersTab } from "../components/app-detail/handlers-tab";
import { LogTable } from "../components/shared/log-table";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";
import { useScopedApi } from "../hooks/use-scoped-api";
import { useAppState } from "../state/context";
import { statusToKind, statusToVariant } from "../utils/status";
import { StatusShape } from "../components/shared/status-shape";

type TabId = "handlers" | "code" | "logs" | "config";

interface Props {
  params: { key: string; index?: string };
}


/** Instance switcher: horizontal tab strip showing siblings with status dots. */
function InstanceSwitcher({
  instances,
  currentIndex,
  onNavigate,
}: {
  instances: AppInstance[];
  currentIndex: number;
  onNavigate: (index: number) => void;
}) {
  return (
    <div class="ht-instance-switcher" data-testid="instance-switcher" role="tablist" aria-label="Instance">
      {instances.map((inst) => {
        const isActive = inst.index === currentIndex;
        return (
          <button
            key={inst.index}
            type="button"
            role="tab"
            aria-selected={isActive}
            class={`ht-instance-switcher__btn${isActive ? " ht-instance-switcher__btn--active" : ""}`}
            data-testid={`switcher-instance-${inst.index}`}
            onClick={() => { if (!isActive) onNavigate(inst.index); }}
          >
            <StatusShape kind={statusToKind(inst.status)} size={8} />
            <span class="ht-instance-switcher__label">{inst.instance_name}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Single instance card for the multi-instance parent overview grid. */
function InstanceCard({
  instance,
  onNavigate,
}: {
  instance: AppInstance;
  onNavigate: (index: number) => void;
}) {
  return (
    <button
      type="button"
      class="ht-instance-card"
      data-testid={`instance-card-${instance.index}`}
      onClick={() => { onNavigate(instance.index); }}
      aria-label={`View ${instance.instance_name}`}
    >
      <div class="ht-instance-card__header">
        <StatusShape kind={statusToKind(instance.status)} size={10} />
        <span class="ht-instance-card__name">{instance.instance_name}</span>
        <span class={`ht-badge ht-badge--sm ht-instance-card__status-badge ht-badge--${statusToVariant(instance.status)}`}>
          {instance.status}
        </span>
      </div>
      {instance.error_message && (
        <p class="ht-instance-card__error-preview">{instance.error_message}</p>
      )}
    </button>
  );
}

/** Multi-instance parent overview: shows instance grid. */
function MultiInstanceOverview({
  appKey,
  displayName,
  instances,
  instanceCount,
  onNavigate,
}: {
  appKey: string;
  displayName: string;
  instances: AppInstance[];
  instanceCount: number;
  onNavigate: (index: number) => void;
}) {
  return (
    <div class="ht-multi-overview" data-testid="multi-instance-overview">
      <div class="ht-level ht-mb-4">
        <div class="ht-level-start">
          <h2 class="ht-heading-4">{displayName}</h2>
          <span class="ht-badge ht-badge--neutral" data-testid="instance-count-badge">
            ×{instanceCount} instances
          </span>
        </div>
      </div>
      <code class="ht-text-mono ht-text-sm ht-mb-4 ht-block">{appKey}</code>
      <div class="ht-instance-grid" data-testid="instance-grid">
        {instances.map((inst) => (
          <InstanceCard
            key={inst.index}
            instance={inst}
            onNavigate={onNavigate}
          />
        ))}
      </div>
    </div>
  );
}

export function AppDetailPage({ params }: Props) {
  const appKey = params.key;
  const parsed = params.index !== undefined ? parseInt(params.index, 10) : undefined;
  const instanceIndex = parsed !== undefined && Number.isFinite(parsed) ? parsed : undefined;
  const { appStatus } = useAppState();
  const [, navigate] = useLocation();
  const searchString = useSearch();

  const activeTab = useRef(signal<TabId>("handlers")).current;

  // Parse focus query param for auto-selecting a handler (strip from URL once read)
  const focusMethod = useRef<string | null>(null);
  useEffect(() => {
    if (focusMethod.current !== null) return;
    const params_ = new URLSearchParams(searchString);
    focusMethod.current = params_.get("focus");
    if (focusMethod.current) {
      const next = new URLSearchParams(searchString);
      next.delete("focus");
      const cleanPath = next.toString() ? `${window.location.pathname}?${next}` : window.location.pathname;
      navigate(cleanPath, { replace: true });
    }
  }, []);

  const manifests = useApi(getManifests);

  // For instance detail view: fetch listeners, jobs
  const resolvedInstanceIndex = instanceIndex ?? 0;
  const listeners = useScopedApi(
    (since) => getAppListeners(appKey, resolvedInstanceIndex, since),
    { deps: [appKey, resolvedInstanceIndex] },
  );
  const jobs = useScopedApi(
    (since) => getAppJobs(appKey, resolvedInstanceIndex, since),
    { deps: [appKey, resolvedInstanceIndex] },
  );

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

  // If multi-instance and no instance index in URL → show parent overview
  const showParentOverview = isMultiInstance && instanceIndex === undefined;

  const currentInstance = manifest?.instances?.find((i) => i.index === resolvedInstanceIndex);
  const liveStatus = appStatus.value[appKey]?.status ?? currentInstance?.status ?? manifest?.status ?? "unknown";

  const hasData = manifests.data.value !== null
    && listeners.data.value !== null && jobs.data.value !== null;
  const initialLoading = !hasData && (listeners.loading.value
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

  // Multi-instance parent overview
  if (showParentOverview && manifest) {
    return (
      <div>
        {/* Breadcrumb */}
        <nav class="ht-breadcrumb ht-mb-3" aria-label="Breadcrumb">
          <a href="/apps">Apps</a>
          <span class="ht-breadcrumb__separator" aria-hidden="true">/</span>
          <span class="ht-breadcrumb__current" aria-current="page">
            {manifest.display_name ?? appKey}
          </span>
        </nav>
        <MultiInstanceOverview
          appKey={appKey}
          displayName={manifest.display_name ?? appKey}
          instances={manifest.instances ?? []}
          instanceCount={manifest.instance_count}
          onNavigate={(idx) => { navigate(`/apps/${appKey}/${idx}`); }}
        />
      </div>
    );
  }

  return (
    <div>
      {/* Breadcrumb */}
      <nav class="ht-breadcrumb ht-mb-3" aria-label="Breadcrumb">
        {isMultiInstance ? (
          <>
            <a href="/apps">Apps</a>
            <span class="ht-breadcrumb__separator" aria-hidden="true">/</span>
            <a
              href={`/apps/${appKey}`}
              data-testid="breadcrumb-parent"
              onClick={(e) => {
                e.preventDefault();
                navigate(`/apps/${appKey}`);
              }}
            >
              {manifest?.display_name ?? appKey}
            </a>
            <span class="ht-breadcrumb__separator" aria-hidden="true">/</span>
            <span class="ht-breadcrumb__current" aria-current="page">
              {currentInstance?.instance_name ?? `Instance ${resolvedInstanceIndex}`}
            </span>
          </>
        ) : (
          <>
            <a href="/apps">Apps</a>
            <span class="ht-breadcrumb__separator" aria-hidden="true">/</span>
            <span class="ht-breadcrumb__current" aria-current="page">
              {manifest?.display_name ?? appKey}
            </span>
          </>
        )}
      </nav>

      {/* Instance switcher (multi-instance detail view only) */}
      {isMultiInstance && manifest?.instances && manifest.instances.length > 0 && (
        <div class="ht-mb-3">
          <InstanceSwitcher
            instances={manifest.instances}
            currentIndex={resolvedInstanceIndex}
            onNavigate={(idx) => { navigate(`/apps/${appKey}/${idx}`); }}
          />
        </div>
      )}

      {/* App header */}
      <div class="ht-level ht-mb-2">
        <div class="ht-level-start">
          <div class="ht-level-item">
            <h2 class="ht-heading-4" data-testid="app-title">
              <StatusShape kind={statusToKind(liveStatus)} size={14} />
              <span class="ht-ml-2">{manifest?.display_name ?? appKey}</span>
            </h2>
          </div>
        </div>
        <div class="ht-level-end">
          <ActionButtons appKey={appKey} status={liveStatus} variant="text" confirmStop />
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
          Instance {resolvedInstanceIndex}
          {currentInstance?.owner_id && <> &middot; PID {currentInstance.owner_id}</>}
        </p>
      )}

      {/* Error banner for failed/crashed apps */}
      {(currentInstance?.error_message ?? manifest?.error_message) && (
        <ErrorDisplay
          errorMessage={(currentInstance?.error_message ?? manifest?.error_message)!}
          errorTraceback={manifest?.error_traceback ?? null}
        />
      )}

      {/* Block reason banner for blocked apps */}
      {manifest?.block_reason && (
        <div class="ht-alert ht-alert--warning ht-mb-4" role="alert" data-testid="block-reason-banner">
          <strong>Blocked:</strong> {manifest.block_reason}
        </div>
      )}

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
          listeners={listeners.data.value ?? []}
          jobs={jobs.data.value ?? []}
          focusMethod={focusMethod.current}
          onSwitchToCode={() => { activeTab.value = "code"; }}
        />
      )}
      {activeTab.value === "code" && (
        <CodeTab
          appKey={appKey}
          listeners={listeners.data.value ?? []}
        />
      )}
      {activeTab.value === "logs" && (
        <div class="ht-card" data-testid="logs-section">
          <LogTable showAppColumn={false} appKey={appKey} />
        </div>
      )}
      {activeTab.value === "config" && (
        <ConfigTab appKey={appKey} />
      )}
    </div>
  );
}
