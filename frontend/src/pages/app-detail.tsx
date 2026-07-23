import { keepPreviousData } from "@tanstack/preact-query";
import clsx from "clsx";
import { useEffect } from "preact/hooks";
import { Link, useLocation } from "wouter";

import { getAppJobs, getAppListeners } from "../api/endpoints";
import { AppDetailHeader } from "../components/app-detail/app-detail-header";
import { AppLogsPanel } from "../components/app-detail/app-logs-panel";
import { CodeTab } from "../components/app-detail/code-tab";
import { ConfigTab } from "../components/app-detail/config-tab";
import { HandlersTab } from "../components/app-detail/handlers-tab";
import { InstanceSwitcher, MultiInstanceOverview } from "../components/app-detail/multi-instance";
import { OverviewTab } from "../components/app-detail/overview-tab";
import { Spinner } from "../components/shared/spinner";
import { useCorrectUrl } from "../hooks/use-correct-url";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useManifest } from "../hooks/use-manifest";
import { useQueryInvalidator } from "../hooks/use-query-invalidator";
import { useQueryParams } from "../hooks/use-query-params";
import { useScopedQuery } from "../hooks/use-scoped-query";
import { queryKeys } from "../lib/query-keys";
import { useAppState } from "../state/context";
import { appStatusKey } from "../state/create-app-state";
import { appLiveStatus } from "../utils/app-data";
import { appDetailPath, type AppDetailTab } from "../utils/app-routes";
import styles from "./app-detail.module.css";

export type TabId = AppDetailTab;

const DECIMAL_INSTANCE_PARAM_RE = /^\d+$/;

interface Props {
  params: { key: string; tab?: TabId; handler?: string; execId?: string };
}

function parseInstanceParam(param: string | null): number | undefined {
  if (param === null) return undefined;
  const trimmed = param.trim();
  return DECIMAL_INSTANCE_PARAM_RE.test(trimmed) ? Number(trimmed) : undefined;
}

function instanceCorrectionUrl(appKey: string, activeTab: TabId, lineParam: string | null): string {
  return appDetailPath(appKey, activeTab, {
    line: activeTab === "code" ? lineParam : null,
    instance: 0,
  });
}

function Tab({
  id,
  label,
  badge,
  appKey,
  instanceIndex,
  activeTab,
}: {
  id: TabId;
  label: string;
  badge?: number;
  appKey: string;
  instanceIndex?: number;
  activeTab: TabId;
}) {
  const isActive = activeTab === id;
  const href = appDetailPath(appKey, id, { instance: instanceIndex });
  return (
    <Link
      href={href}
      role="tab"
      id={`tab-${id}`}
      tabIndex={isActive ? 0 : -1}
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
  const { appStatus, executionCompleted } = useAppState();
  const { data: manifest, isPending: manifestLoading, error: manifestError } = useManifest(appKey);
  const [, navigate] = useLocation();
  const queryParams = useQueryParams();
  const correctUrl = useCorrectUrl();

  const instanceParam = queryParams.get("instance");
  const lineParam = queryParams.get("line");
  const instanceIndex = parseInstanceParam(instanceParam);

  const resolvedInstanceIndex = instanceIndex ?? 0;

  const {
    data: listenersData,
    isPending: listenersLoading,
    error: listenersError,
  } = useScopedQuery(
    queryKeys.appListeners.base(appKey, resolvedInstanceIndex),
    (since, signal) => getAppListeners(appKey, resolvedInstanceIndex, since, signal),
    { placeholderData: keepPreviousData },
  );
  const {
    data: jobsData,
    isPending: jobsLoading,
    error: jobsError,
  } = useScopedQuery(
    queryKeys.appJobs.base(appKey, resolvedInstanceIndex),
    (since, signal) => getAppJobs(appKey, resolvedInstanceIndex, since, signal),
    { placeholderData: keepPreviousData },
  );

  useQueryInvalidator(
    executionCompleted,
    (events) => events?.some((e) => e.kind === "handler" && e.app_key === appKey) ?? false,
    queryKeys.appListeners.prefix(appKey),
  );
  useQueryInvalidator(
    executionCompleted,
    (events) => events?.some((e) => e.kind === "job" && e.app_key === appKey) ?? false,
    queryKeys.appJobs.prefix(appKey),
  );

  const displayListeners = listenersData ?? [];
  const displayJobs = jobsData ?? [];

  useDocumentTitle(manifest?.display_name ?? "App");

  const isMultiInstance = (manifest?.instance_count ?? 0) > 1;
  const showParentOverview = isMultiInstance && instanceIndex === undefined;

  const currentInstance = !showParentOverview
    ? manifest?.instances?.find((i) => i.index === resolvedInstanceIndex)
    : undefined;
  const wsStatus = appStatus.value[appStatusKey(appKey, resolvedInstanceIndex)]?.status;
  const instanceStatus = wsStatus ?? currentInstance?.status ?? manifest?.status ?? "unknown";
  const liveStatus = showParentOverview
    ? manifest
      ? appLiveStatus(appStatus.value, manifest)
      : "unknown"
    : instanceStatus;

  const hasData = !manifestLoading && listenersData !== undefined && jobsData !== undefined;
  const initialLoading = !hasData && (listenersLoading || jobsLoading || manifestLoading);

  useEffect(() => {
    if (initialLoading) return;
    if (manifest && instanceParam !== null && instanceIndex === undefined) {
      correctUrl(instanceCorrectionUrl(appKey, activeTab, lineParam));
      return;
    }
    if (manifest && instanceIndex !== undefined && instanceIndex >= manifest.instance_count) {
      correctUrl(instanceCorrectionUrl(appKey, activeTab, lineParam));
    }
  }, [initialLoading, manifest, instanceParam, instanceIndex, appKey, activeTab, lineParam, correctUrl]);

  useEffect(() => {
    if (showParentOverview && activeTab === "handlers" && instanceParam === null) {
      correctUrl(appDetailPath(appKey, "overview"));
    }
  }, [showParentOverview, activeTab, appKey, correctUrl, instanceParam]);

  if (initialLoading) return <Spinner />;

  if (manifestError || listenersError || jobsError) {
    return (
      <div class="ht-alert ht-alert--danger" role="alert">
        {(manifestError ?? listenersError ?? jobsError)!.message}
      </div>
    );
  }

  const instanceQs = instanceIndex !== undefined ? `?instance=${instanceIndex}` : "";
  const tabProps = { appKey, instanceIndex, activeTab };
  const handlerCount = (listenersData?.length ?? 0) + (jobsData?.length ?? 0);

  return (
    <div class="ht-page">
      <div class={styles.identity}>
        {isMultiInstance && !showParentOverview && manifest?.instances && manifest.instances.length > 0 && (
          <InstanceSwitcher
            instances={manifest.instances}
            currentIndex={resolvedInstanceIndex}
            onNavigate={(idx) => {
              navigate(appDetailPath(appKey, activeTab, { instance: idx }));
            }}
          />
        )}

        <AppDetailHeader
          appKey={appKey}
          liveStatus={liveStatus}
          manifest={manifest}
          currentInstance={currentInstance}
          resolvedInstanceIndex={resolvedInstanceIndex}
          showParentOverview={showParentOverview}
        />

        <div
          class={styles.tabStrip}
          role="tablist"
          aria-label="App sections"
          onKeyDown={(e: KeyboardEvent) => {
            if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
            e.preventDefault();
            const tabs = (e.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('[role="tab"]');
            const current = Array.from(tabs).findIndex((t) => t.getAttribute("aria-selected") === "true");
            const next =
              e.key === "ArrowRight" ? (current + 1) % tabs.length : (current - 1 + tabs.length) % tabs.length;
            tabs[next]?.focus();
            tabs[next]?.click();
          }}
        >
          <Tab id="overview" label="overview" {...tabProps} />
          {!showParentOverview && <Tab id="handlers" label="handlers" badge={handlerCount} {...tabProps} />}
          <Tab id="code" label="code" {...tabProps} />
          <Tab id="logs" label="logs" {...tabProps} />
          <Tab id="config" label="config" {...tabProps} />
        </div>
      </div>

      {activeTab === "overview" && (
        <div role="tabpanel" id="tabpanel-overview" aria-labelledby="tab-overview">
          {showParentOverview && manifest ? (
            <MultiInstanceOverview
              appKey={appKey}
              displayName={manifest.display_name ?? appKey}
              instances={manifest.instances ?? []}
              instanceCount={manifest.instance_count}
              onNavigate={(idx) => {
                navigate(appDetailPath(appKey, "overview", { instance: idx }));
              }}
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
            selectedExecId={params.execId ?? null}
            appKey={appKey}
            instanceIndex={instanceIndex}
            onSwitchToCode={(line) => {
              navigate(appDetailPath(appKey, "code", { line, instance: instanceIndex }));
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
        <div class={styles.tabPanel} role="tabpanel" id="tabpanel-logs" aria-labelledby="tab-logs">
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
