import { useEffect, useRef } from "preact/hooks";
import { Link, useLocation } from "wouter";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useCorrectUrl } from "../hooks/use-correct-url";
import { useQueryParams } from "../hooks/use-query-params";
import { getAppJobs, getAppListeners, getManifests } from "../api/endpoints";
import type { AppInstance } from "../api/endpoints";
import { ActionButtons } from "../components/shared/action-buttons";
import { CodeTab } from "../components/app-detail/code-tab";
import { ConfigTab } from "../components/app-detail/config-tab";
import { ErrorBanner } from "../components/shared/error-banner";
import { HandlersTab } from "../components/app-detail/handlers-tab";
import { LogTable } from "../components/shared/log-table";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";
import { useScopedApi } from "../hooks/use-scoped-api";
import { useAppState } from "../state/context";
import { statusToKind, statusToVariant } from "../utils/status";
import { StatusShape } from "../components/shared/status-shape";
import { signal } from "@preact/signals";

export type TabId = "handlers" | "code" | "logs" | "config";

interface Props {
  params: { key: string; tab?: TabId; handler?: string };
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
          <h1 class="ht-heading-4">{displayName}</h1>
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

function Tab({ id, label, badge, appKey: appKey_, instanceQs: qs, activeTab: active, navigate: nav }: {
  id: TabId; label: string; badge?: number;
  appKey: string; instanceQs: string; activeTab: TabId; navigate: (to: string, opts?: { replace?: boolean }) => void;
}) {
  const isActive = active === id;
  const href = `/apps/${appKey_}/${id}${qs}`;
  return (
    <Link
      href={href}
      role="tab"
      id={`tab-${id}`}
      aria-selected={isActive}
      aria-controls={`tabpanel-${id}`}
      class={`ht-tab-btn${isActive ? " ht-tab-btn--active" : ""}`}
      onKeyDown={(e: KeyboardEvent) => {
        if (e.key === " ") {
          e.preventDefault();
          nav(href);
        }
      }}
    >
      {label}{badge !== undefined && <span class="ht-tab-btn__badge">{badge}</span>}
    </Link>
  );
}

export function AppDetailPage({ params }: Props) {
  const appKey = params.key;
  const activeTab: TabId = params.tab ?? "handlers";
  const { appStatus } = useAppState();
  const [, navigate] = useLocation();
  const queryParams = useQueryParams();
  const correctUrl = useCorrectUrl();

  // Read instance from ?instance=N query param
  const instanceParam = queryParams.get("instance");
  const parsedInstance = instanceParam !== null ? parseInt(instanceParam, 10) : undefined;
  const instanceIndex = parsedInstance !== undefined && Number.isFinite(parsedInstance) ? parsedInstance : undefined;

  // codeFocusLine signal still used temporarily until T03 replaces it with ?line=
  const codeFocusLine = useRef(signal<number | undefined>(undefined)).current;

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

  // Preserve stale handler/job data during refetch to avoid losing selection
  const staleListeners = useRef<typeof listeners.data.value>(null);
  const staleJobs = useRef<typeof jobs.data.value>(null);
  if (listeners.data.value) staleListeners.current = listeners.data.value;
  if (jobs.data.value) staleJobs.current = jobs.data.value;
  const displayListeners = listeners.data.value ?? staleListeners.current ?? [];
  const displayJobs = jobs.data.value ?? staleJobs.current ?? [];

  const manifest = manifests.data.value?.manifests.find((m) => m.app_key === appKey);
  useDocumentTitle(manifest?.display_name ?? "App");

  const isMultiInstance = (manifest?.instance_count ?? 0) > 1;

  // If multi-instance and no instance index in URL → show parent overview
  const showParentOverview = isMultiInstance && instanceIndex === undefined;

  const currentInstance = manifest?.instances?.find((i) => i.index === resolvedInstanceIndex);
  const liveStatus = appStatus.value[appKey]?.status ?? currentInstance?.status ?? manifest?.status ?? "unknown";

  const hasData = manifests.data.value !== null
    && listeners.data.value !== null && jobs.data.value !== null;
  const initialLoading = !hasData && (listeners.loading.value
    || jobs.loading.value || manifests.loading.value);

  // Correct out-of-range instance index (FR#16, AC#14)
  // Guarded: only fires when data is fully loaded and confirms instance is invalid
  useEffect(() => {
    if (initialLoading) return;
    if (manifest && instanceIndex !== undefined && instanceIndex >= manifest.instance_count) {
      correctUrl(`/apps/${appKey}/${activeTab}?instance=0`, `instance ${instanceIndex} out of range, using 0`);
    }
  }, [initialLoading, manifest, instanceIndex, appKey, activeTab, correctUrl]);

  if (initialLoading) return <Spinner />;

  // Build instance query string for tab links — preserve ?instance=N, omit if not set
  const instanceQs = instanceParam !== null && instanceParam !== "" ? `?instance=${instanceParam}` : "";

  const tabProps = { appKey, instanceQs, activeTab, navigate };

  const handlerCount = (listeners.data.value?.length ?? 0) + (jobs.data.value?.length ?? 0);

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
          onNavigate={(idx) => { navigate(`/apps/${appKey}?instance=${idx}`); }}
        />
      </div>
    );
  }

  return (
    <div class="ht-page">
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
              {appKey}
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
              {appKey}
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
            onNavigate={(idx) => { navigate(`/apps/${appKey}/${activeTab}?instance=${idx}`); }}
          />
        </div>
      )}

      {/* App header */}
      <div class="ht-level ht-mb-2">
        <div class="ht-level-start">
          <div class="ht-level-item">
            <h1 class="ht-heading-4" data-testid="app-title">
              <StatusShape kind={statusToKind(liveStatus)} size={14} />
              <span class="ht-ml-2">{appKey}</span>
            </h1>
          </div>
        </div>
        <div class="ht-level-end">
          {liveStatus !== "running" && liveStatus !== "starting" && (
            <span
              class={`ht-badge ht-badge--sm ht-badge--${statusToVariant(liveStatus)}`}
              data-testid="app-status-pill"
            >
              <StatusShape kind={statusToKind(liveStatus)} size={8} /> {liveStatus}
            </span>
          )}
          <ActionButtons appKey={appKey} status={liveStatus} variant="text" confirmStop />
        </div>
      </div>

      {/* Subtitle meta line */}
      <p class="ht-text-mono ht-text-sm ht-text-muted ht-mb-3" data-testid="app-subtitle-meta">
        {manifest?.filename ?? appKey}
        {manifest?.class_name && manifest.class_name !== appKey && (
          <> &middot; {manifest.class_name}</>
        )}
        {manifest && manifest.instance_count > 1 && <> &middot; instance {resolvedInstanceIndex}</>}
        {manifest?.auto_loaded && (
          <> &middot; <span class="ht-chip ht-chip--auto" data-testid="auto-loaded-badge">auto</span></>
        )}
      </p>

      {/* Error banner for failed/crashed apps */}
      {(currentInstance?.error_message ?? manifest?.error_message) && (
        <ErrorBanner
          errorMessage={(currentInstance?.error_message ?? manifest?.error_message)!}
          traceback={manifest?.error_traceback ?? null}
          data-testid="error-display"
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
        <Tab id="handlers" label="handlers" badge={handlerCount} {...tabProps} />
        <Tab id="code" label="code" {...tabProps} />
        <Tab id="logs" label="logs" {...tabProps} />
        <Tab id="config" label="config" {...tabProps} />
      </div>

      {/* Tab content */}
      {activeTab === "handlers" && (
        <div role="tabpanel" id="tabpanel-handlers" aria-labelledby="tab-handlers">
        <HandlersTab
          listeners={displayListeners}
          jobs={displayJobs}
          focusMethod={null}
          onSwitchToCode={(line) => { codeFocusLine.value = line; navigate(`/apps/${appKey}/code${instanceQs}`); }}
        />
        </div>
      )}
      {activeTab === "code" && (
        <div role="tabpanel" id="tabpanel-code" aria-labelledby="tab-code">
          <CodeTab
            appKey={appKey}
            listeners={displayListeners}
            focusLine={codeFocusLine.value}
          />
        </div>
      )}
      {activeTab === "logs" && (
        <div role="tabpanel" id="tabpanel-logs" aria-labelledby="tab-logs">
          <div class="ht-card" data-testid="logs-section">
            <LogTable showAppColumn={false} appKey={appKey} />
          </div>
        </div>
      )}
      {activeTab === "config" && (
        <div role="tabpanel" id="tabpanel-config" aria-labelledby="tab-config">
          <ConfigTab appKey={appKey} />
        </div>
      )}
    </div>
  );
}
