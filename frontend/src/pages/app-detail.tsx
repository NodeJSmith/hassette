import { useEffect, useRef } from "preact/hooks";
import { Link, useLocation } from "wouter";
import clsx from "clsx";

import { useDocumentTitle } from "../hooks/use-document-title";
import { useCorrectUrl } from "../hooks/use-correct-url";
import { useQueryParams } from "../hooks/use-query-params";
import { getAppJobs, getAppListeners } from "../api/endpoints";
import { CodeTab } from "../components/app-detail/code-tab";
import { ConfigTab } from "../components/app-detail/config-tab";
import { HandlersTab } from "../components/app-detail/handlers-tab";
import { OverviewTab } from "../components/app-detail/overview-tab";
import { Spinner } from "../components/shared/spinner";
import { useScopedApi } from "../hooks/use-scoped-api";
import { useAppState } from "../state/context";
import { useFilteredSignalRefetch, WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS } from "../hooks/use-filtered-signal-refetch";
import { InstanceSwitcher, MultiInstanceOverview } from "../components/app-detail/multi-instance";
import { AppLogsPanel } from "../components/app-detail/app-logs-panel";
import { AppDetailBreadcrumb } from "../components/app-detail/app-detail-breadcrumb";
import { AppDetailHeader } from "../components/app-detail/app-detail-header";
import styles from "./app-detail.module.css";

export type TabId = "overview" | "handlers" | "code" | "logs" | "config";

interface Props {
  params: { key: string; tab?: TabId; handler?: string };
}

function Tab({ id, label, badge, appKey, instanceQs, activeTab }: {
  id: TabId;
  label: string;
  badge?: number;
  appKey: string;
  instanceQs: string;
  activeTab: TabId;
}) {
  const isActive = activeTab === id;
  const href = `/apps/${appKey}/${id}${instanceQs}`;
  return (
    <Link
      href={href}
      role="tab"
      id={`tab-${id}`}
      aria-selected={isActive}
      aria-controls={`tabpanel-${id}`}
      class={clsx(styles.tabBtn, isActive && styles.tabBtnActive)}
    >
      {label}
      {badge !== undefined && <span class={styles.tabBtnBadge}>{badge}</span>}
    </Link>
  );
}

export function AppDetailPage({ params }: Props) {
  const appKey = params.key;
  const activeTab: TabId = params.tab ?? "overview";
  const { appStatus, manifests, manifestsLoading, invocationCompleted, executionCompleted } = useAppState();
  const [, navigate] = useLocation();
  const queryParams = useQueryParams();
  const correctUrl = useCorrectUrl();

  const instanceParam = queryParams.get("instance");
  const parsedInstance = instanceParam !== null ? parseInt(instanceParam, 10) : undefined;
  const instanceIndex = parsedInstance !== undefined && Number.isFinite(parsedInstance) ? parsedInstance : undefined;

  const resolvedInstanceIndex = instanceIndex ?? 0;
  const listeners = useScopedApi(
    (since) => getAppListeners(appKey, resolvedInstanceIndex, since),
    { deps: [appKey, resolvedInstanceIndex] },
  );
  const jobs = useScopedApi(
    (since) => getAppJobs(appKey, resolvedInstanceIndex, since),
    { deps: [appKey, resolvedInstanceIndex] },
  );

  useFilteredSignalRefetch(
    invocationCompleted,
    (events) => events?.some((e) => e.app_key === appKey) ?? false,
    () => { void listeners.refetch(); void jobs.refetch(); },
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );
  useFilteredSignalRefetch(
    executionCompleted,
    (events) => events?.some((e) => e.app_key === appKey) ?? false,
    () => { void listeners.refetch(); void jobs.refetch(); },
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  const staleListeners = useRef<typeof listeners.data.value>(null);
  const staleJobs = useRef<typeof jobs.data.value>(null);
  if (listeners.data.value) staleListeners.current = listeners.data.value;
  if (jobs.data.value) staleJobs.current = jobs.data.value;
  const displayListeners = listeners.data.value ?? staleListeners.current ?? [];
  const displayJobs = jobs.data.value ?? staleJobs.current ?? [];

  const manifest = manifests.value.find((m) => m.app_key === appKey);
  useDocumentTitle(manifest?.display_name ?? "App");

  const isMultiInstance = (manifest?.instance_count ?? 0) > 1;
  const showParentOverview = isMultiInstance && instanceIndex === undefined;

  const currentInstance = !showParentOverview
    ? manifest?.instances?.find((i) => i.index === resolvedInstanceIndex)
    : undefined;
  const wsStatus = appStatus.value[appKey]?.status;
  const liveStatus = showParentOverview
    ? manifest?.status ?? "unknown"
    : wsStatus ?? currentInstance?.status ?? manifest?.status ?? "unknown";

  const hasData = !manifestsLoading.value
    && listeners.data.value !== null && jobs.data.value !== null;
  const initialLoading = !hasData && (listeners.loading.value
    || jobs.loading.value || manifestsLoading.value);

  useEffect(() => {
    if (initialLoading) return;
    if (manifest && instanceIndex !== undefined && instanceIndex >= manifest.instance_count) {
      correctUrl(`/apps/${appKey}/${activeTab}?instance=0`);
    }
  }, [initialLoading, manifest, instanceIndex, appKey, activeTab, correctUrl]);

  useEffect(() => {
    if (showParentOverview && activeTab === "handlers") {
      correctUrl(`/apps/${appKey}/overview`);
    }
  }, [showParentOverview, activeTab, appKey, correctUrl]);

  if (initialLoading) return <Spinner />;

  const instanceQs = instanceParam !== null && instanceParam !== "" ? `?instance=${instanceParam}` : "";
  const tabProps = { appKey, instanceQs, activeTab };
  const handlerCount = (listeners.data.value?.length ?? 0) + (jobs.data.value?.length ?? 0);

  return (
    <div class="ht-page">
      <AppDetailBreadcrumb
        appKey={appKey}
        isMultiInstance={isMultiInstance}
        showParentOverview={showParentOverview}
        instanceName={currentInstance?.instance_name ?? `Instance ${resolvedInstanceIndex}`}
      />

      {isMultiInstance && !showParentOverview && manifest?.instances && manifest.instances.length > 0 && (
        <div class="ht-mb-3">
          <InstanceSwitcher
            instances={manifest.instances}
            currentIndex={resolvedInstanceIndex}
            onNavigate={(idx) => { navigate(`/apps/${appKey}/${activeTab}?instance=${idx}`); }}
          />
        </div>
      )}

      <AppDetailHeader
        appKey={appKey}
        liveStatus={liveStatus}
        manifest={manifest}
        currentInstance={currentInstance}
        resolvedInstanceIndex={resolvedInstanceIndex}
        showParentOverview={showParentOverview}
      />

      <div class={clsx(styles.tabStrip, "ht-mb-4")} role="tablist" aria-label="App sections">
        <Tab id="overview" label="overview" {...tabProps} />
        {!showParentOverview && <Tab id="handlers" label="handlers" badge={handlerCount} {...tabProps} />}
        <Tab id="code" label="code" {...tabProps} />
        <Tab id="logs" label="logs" {...tabProps} />
        <Tab id="config" label="config" {...tabProps} />
      </div>

      {activeTab === "overview" && (
        <div role="tabpanel" id="tabpanel-overview" aria-labelledby="tab-overview">
          {showParentOverview && manifest ? (
            <MultiInstanceOverview
              appKey={appKey}
              displayName={manifest.display_name ?? appKey}
              instances={manifest.instances ?? []}
              instanceCount={manifest.instance_count}
              onNavigate={(idx) => { navigate(`/apps/${appKey}/overview?instance=${idx}`); }}
            />
          ) : (
            <OverviewTab
              listeners={displayListeners}
              jobs={displayJobs}
              appKey={appKey}
              instanceQs={instanceQs}
              resolvedInstanceIndex={resolvedInstanceIndex}
              appStatus={liveStatus}
            />
          )}
        </div>
      )}
      {activeTab === "handlers" && (
        <div role="tabpanel" id="tabpanel-handlers" aria-labelledby="tab-handlers">
          <HandlersTab
            listeners={displayListeners}
            jobs={displayJobs}
            selectedHandler={params.handler ?? null}
            appKey={appKey}
            instanceQs={instanceQs}
            onSwitchToCode={(line) => {
              const qs = new URLSearchParams();
              if (line !== undefined) qs.set("line", String(line));
              if (instanceParam) qs.set("instance", instanceParam);
              const query = qs.toString();
              navigate(`/apps/${appKey}/code${query ? `?${query}` : ""}`);
            }}
          />
        </div>
      )}
      {activeTab === "code" && (
        <div role="tabpanel" id="tabpanel-code" aria-labelledby="tab-code">
          <CodeTab appKey={appKey} listeners={displayListeners} />
        </div>
      )}
      {activeTab === "logs" && (
        <div role="tabpanel" id="tabpanel-logs" aria-labelledby="tab-logs">
          <AppLogsPanel appKey={appKey} />
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
