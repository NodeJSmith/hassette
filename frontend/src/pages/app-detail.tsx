import { keepPreviousData } from "@tanstack/react-query";
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { useEffect } from "react";
import { Link, useLocation } from "wouter";

import { cn } from "@/lib/utils";

import { type AppManifest, getAppJobs, getAppListeners } from "../api/endpoints";
import { AppDetailHeader } from "../components/app-detail/app-detail-header";
import { AppLogsPanel } from "../components/app-detail/app-logs-panel";
import { CodeTab } from "../components/app-detail/code-tab";
import { ConfigTab } from "../components/app-detail/config-tab";
import { HandlersTab } from "../components/app-detail/handlers-tab";
import { InstanceSwitcher, MultiInstanceOverview } from "../components/app-detail/multi-instance";
import { OverviewTab } from "../components/app-detail/overview-tab";
import { ErrorAlert } from "../components/shared/error-alert";
import { Spinner } from "../components/shared/spinner";
import { useCorrectUrl } from "../hooks/use-correct-url";
import { useDocumentTitle } from "../hooks/use-document-title";
import { useManifest } from "../hooks/use-manifest";
import { useQueryInvalidator } from "../hooks/use-query-invalidator";
import { useQueryParams } from "../hooks/use-query-params";
import { isExecutionDefined, useAppExecution } from "../hooks/use-scoped-execution";
import { useScopedQuery } from "../hooks/use-scoped-query";
import { queryKeys } from "../lib/query-keys";
import { appStatusKey, useAppStore } from "../state/store";
import { appLiveStatus } from "../utils/app-data";
import { appDetailPath, type AppDetailTab, parseInstanceParam } from "../utils/app-routes";

const PAGE_CLASS = "flex flex-1 flex-col gap-8 p-8 max-mobile:p-3 max-small-mobile:p-2";

export type TabId = AppDetailTab;

interface Props {
  params: { key: string; tab?: TabId; handler?: string; execId?: string };
}

// An `?instance=` value is addressable when the manifest lists that name. Orphans (tracked but no
// longer configured) are listed too, so the page offering an orphan's Stop control stays reachable.
function isAddressableInstance(manifest: AppManifest, instanceName: string): boolean {
  return manifest.instances?.some((i) => i.instance_name === instanceName) ?? false;
}

// A stale `?instance=` (an old numeric bookmark, a renamed or removed name) drops the param rather
// than picking an instance by position, so the corrected URL never depends on config order.
function instanceCorrectionUrl(appKey: string, activeTab: TabId, lineParam: string | null): string {
  return appDetailPath(appKey, activeTab, {
    line: activeTab === "code" ? lineParam : null,
  });
}

function Tab({
  id,
  label,
  badge,
  appKey,
  instanceName,
  activeTab,
}: {
  id: TabId;
  label: string;
  badge?: number;
  appKey: string;
  instanceName?: string;
  activeTab: TabId;
}) {
  const isActive = activeTab === id;
  const href = appDetailPath(appKey, id, { instance: instanceName });
  return (
    <Link
      href={href}
      role="tab"
      id={`tab-${id}`}
      tabIndex={isActive ? 0 : -1}
      aria-selected={isActive}
      aria-controls={`tabpanel-${id}`}
      className={cn(
        "inline-block whitespace-nowrap px-4 py-2 font-sans text-[length:var(--text-mono-md)] font-medium text-muted-foreground no-underline transition-colors hover:bg-muted hover:text-foreground focus-visible:rounded-sm max-sidebar:min-h-[var(--sz-touch)] max-sidebar:px-3 max-small-mobile:px-1.5 max-small-mobile:text-xs",
        isActive && "bg-[linear-gradient(to_bottom,transparent,var(--primary-soft))] text-foreground",
      )}
    >
      {label}
      {badge !== undefined && <span className="ml-1 text-xs font-normal text-muted-foreground">{badge}</span>}
    </Link>
  );
}

function TabPanel({ id, children, className }: { id: TabId; children: ReactNode; className?: string }) {
  return (
    <div className={className} role="tabpanel" id={`tabpanel-${id}`} aria-labelledby={`tab-${id}`}>
      {children}
    </div>
  );
}

function handleTabKeyDown(e: ReactKeyboardEvent) {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  e.preventDefault();
  const tabs = (e.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('[role="tab"]');
  const current = Array.from(tabs).findIndex((t) => t.getAttribute("aria-selected") === "true");
  const next = e.key === "ArrowRight" ? (current + 1) % tabs.length : (current - 1 + tabs.length) % tabs.length;
  tabs[next]?.focus();
  tabs[next]?.click();
}

export function AppDetailPage({ params }: Props) {
  const appKey = params.key;
  const activeTab: TabId = params.tab ?? "overview";
  const handlerExecution = useAppExecution(appKey, "handler");
  const jobExecution = useAppExecution(appKey, "job");
  const { data: manifest, isPending: manifestLoading, error: manifestError } = useManifest(appKey);
  const [, navigate] = useLocation();
  const queryParams = useQueryParams();
  const correctUrl = useCorrectUrl();

  const instanceParam = queryParams.get("instance");
  const lineParam = queryParams.get("line");
  const instanceName = parseInstanceParam(instanceParam);

  const {
    data: listenersData,
    isPending: listenersLoading,
    error: listenersError,
  } = useScopedQuery(
    queryKeys.appListeners.base(appKey, instanceName),
    (since, signal) => getAppListeners(appKey, instanceName, since, signal),
    { placeholderData: keepPreviousData },
  );
  const {
    data: jobsData,
    isPending: jobsLoading,
    error: jobsError,
  } = useScopedQuery(
    queryKeys.appJobs.base(appKey, instanceName),
    (since, signal) => getAppJobs(appKey, instanceName, since, signal),
    { placeholderData: keepPreviousData },
  );

  useQueryInvalidator(handlerExecution, isExecutionDefined, queryKeys.appListeners.prefix(appKey));
  useQueryInvalidator(jobExecution, isExecutionDefined, queryKeys.appJobs.prefix(appKey));

  const displayListeners = listenersData ?? [];
  const displayJobs = jobsData ?? [];

  useDocumentTitle(manifest?.display_name ?? "App");

  const isMultiInstance = (manifest?.instance_count ?? 0) > 1;
  const showParentOverview = isMultiInstance && instanceName === undefined;

  // Without an `?instance=`, a single-instance app's only instance is the one to act on.
  const currentInstance = showParentOverview
    ? undefined
    : instanceName !== undefined
      ? manifest?.instances?.find((i) => i.instance_name === instanceName)
      : manifest?.instances?.[0];
  // Resolving the status inside the selector — instead of subscribing to the whole `appStatus`
  // map — means this page only re-renders when its own app's status actually changes. The
  // selector must keep returning a primitive for that to hold; a fresh object would compare
  // unequal on every store write.
  const liveStatus = useAppStore((s) => {
    if (showParentOverview) return manifest ? appLiveStatus(s.appStatus, manifest) : "unknown";
    const wsStatus = currentInstance
      ? s.appStatus[appStatusKey(appKey, currentInstance.instance_name)]?.status
      : undefined;
    return wsStatus ?? currentInstance?.status ?? manifest?.status ?? "unknown";
  });

  const hasData = !manifestLoading && listenersData !== undefined && jobsData !== undefined;
  const initialLoading = !hasData && (listenersLoading || jobsLoading || manifestLoading);

  useEffect(() => {
    if (initialLoading) return;
    if (!manifest || instanceParam === null) return;
    if (instanceName === undefined || !isAddressableInstance(manifest, instanceName)) {
      correctUrl(instanceCorrectionUrl(appKey, activeTab, lineParam));
    }
  }, [initialLoading, manifest, instanceParam, instanceName, appKey, activeTab, lineParam, correctUrl]);

  useEffect(() => {
    if (showParentOverview && activeTab === "handlers" && instanceParam === null) {
      correctUrl(appDetailPath(appKey, "overview"));
    }
  }, [showParentOverview, activeTab, appKey, correctUrl, instanceParam]);

  if (initialLoading) return <Spinner />;

  if (manifestError || listenersError || jobsError) {
    return <ErrorAlert>{(manifestError ?? listenersError ?? jobsError)!.message}</ErrorAlert>;
  }

  const instanceQueryString = instanceName !== undefined ? `?instance=${instanceName}` : "";
  const tabProps = { appKey, instanceName, activeTab };
  const handlerCount = (listenersData?.length ?? 0) + (jobsData?.length ?? 0);

  return (
    <div className={PAGE_CLASS}>
      <div className="flex flex-col gap-3">
        {isMultiInstance && !showParentOverview && manifest?.instances && manifest.instances.length > 0 && (
          <InstanceSwitcher
            appKey={appKey}
            instances={manifest.instances}
            currentInstanceName={instanceName}
            onNavigate={(name) => {
              navigate(appDetailPath(appKey, activeTab, { instance: name }));
            }}
          />
        )}

        <AppDetailHeader
          appKey={appKey}
          liveStatus={liveStatus}
          manifest={manifest}
          currentInstance={currentInstance}
          showParentOverview={showParentOverview}
        />

        <div
          className="flex gap-0 overflow-hidden rounded-sm border border-border bg-card max-mobile:overflow-x-auto"
          role="tablist"
          aria-label="App sections"
          onKeyDown={handleTabKeyDown}
        >
          <Tab id="overview" label="overview" {...tabProps} />
          {!showParentOverview && <Tab id="handlers" label="handlers" badge={handlerCount} {...tabProps} />}
          <Tab id="code" label="code" {...tabProps} />
          <Tab id="logs" label="logs" {...tabProps} />
          <Tab id="config" label="config" {...tabProps} />
        </div>
      </div>

      {activeTab === "overview" && (
        <TabPanel id="overview">
          {showParentOverview && manifest ? (
            <MultiInstanceOverview
              appKey={appKey}
              displayName={manifest.display_name ?? appKey}
              instances={manifest.instances ?? []}
              instanceCount={manifest.instance_count}
              onNavigate={(name) => {
                navigate(appDetailPath(appKey, "overview", { instance: name }));
              }}
            />
          ) : (
            <OverviewTab
              listeners={displayListeners}
              jobs={displayJobs}
              appKey={appKey}
              instanceQs={instanceQueryString}
              instanceName={instanceName}
              appStatus={liveStatus}
            />
          )}
        </TabPanel>
      )}
      {activeTab === "handlers" && (
        <TabPanel id="handlers">
          <HandlersTab
            listeners={displayListeners}
            jobs={displayJobs}
            selectedHandler={params.handler ?? null}
            selectedExecId={params.execId ?? null}
            appKey={appKey}
            instanceName={instanceName}
            onSwitchToCode={(line) => {
              navigate(appDetailPath(appKey, "code", { line, instance: instanceName }));
            }}
          />
        </TabPanel>
      )}
      {activeTab === "code" && (
        <TabPanel id="code">
          <CodeTab appKey={appKey} listeners={displayListeners} />
        </TabPanel>
      )}
      {activeTab === "logs" && (
        <TabPanel id="logs" className="flex flex-col gap-3">
          <AppLogsPanel appKey={appKey} />
        </TabPanel>
      )}
      {activeTab === "config" && (
        <TabPanel id="config">
          <ConfigTab appKey={appKey} />
        </TabPanel>
      )}
    </div>
  );
}
