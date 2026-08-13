import { keepPreviousData } from "@tanstack/react-query";
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { useEffect } from "react";
import { Link, useLocation } from "wouter";

import { cn } from "@/lib/utils";

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
import { useAppExecution } from "../hooks/use-scoped-execution";
import { useScopedQuery } from "../hooks/use-scoped-query";
import { queryKeys } from "../lib/query-keys";
import { appStatusKey, useAppStore } from "../state/store";
import { appLiveStatus } from "../utils/app-data";
import { appDetailPath, type AppDetailTab, parseInstanceParam } from "../utils/app-routes";

const PAGE_CLASS = "flex flex-1 flex-col gap-8 p-8 max-mobile:p-3 max-small-mobile:p-2";
const ALERT_CLASS =
  "flex items-start gap-3 rounded-md border border-destructive bg-[var(--destructive-bg)] px-4 py-3 text-sm text-foreground";

export type TabId = AppDetailTab;

interface Props {
  params: { key: string; tab?: TabId; handler?: string; execId?: string };
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
      className={cn(
        "inline-block whitespace-nowrap px-4 py-2 font-sans text-[length:var(--text-mono-md)] font-medium text-muted-foreground no-underline transition-colors hover:bg-muted hover:text-foreground focus-visible:rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary max-sidebar:min-h-[var(--sz-touch)] max-sidebar:px-3 max-small-mobile:px-1.5 max-small-mobile:text-xs",
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

  useQueryInvalidator(handlerExecution, (exec) => exec !== undefined, queryKeys.appListeners.prefix(appKey));
  useQueryInvalidator(jobExecution, (exec) => exec !== undefined, queryKeys.appJobs.prefix(appKey));

  const displayListeners = listenersData ?? [];
  const displayJobs = jobsData ?? [];

  useDocumentTitle(manifest?.display_name ?? "App");

  const isMultiInstance = (manifest?.instance_count ?? 0) > 1;
  const showParentOverview = isMultiInstance && instanceIndex === undefined;

  const currentInstance = !showParentOverview
    ? manifest?.instances?.find((i) => i.index === resolvedInstanceIndex)
    : undefined;
  // Resolving the status inside the selector — instead of subscribing to the whole `appStatus`
  // map — means this page only re-renders when its own app's status actually changes. The
  // selector must keep returning a primitive for that to hold; a fresh object would compare
  // unequal on every store write.
  const liveStatus = useAppStore((s) => {
    if (showParentOverview) return manifest ? appLiveStatus(s.appStatus, manifest) : "unknown";
    const wsStatus = s.appStatus[appStatusKey(appKey, resolvedInstanceIndex)]?.status;
    return wsStatus ?? currentInstance?.status ?? manifest?.status ?? "unknown";
  });

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
      <div className={ALERT_CLASS} role="alert">
        {(manifestError ?? listenersError ?? jobsError)!.message}
      </div>
    );
  }

  const instanceQueryString = instanceIndex !== undefined ? `?instance=${instanceIndex}` : "";
  const tabProps = { appKey, instanceIndex, activeTab };
  const handlerCount = (listenersData?.length ?? 0) + (jobsData?.length ?? 0);

  return (
    <div className={PAGE_CLASS}>
      <div className="flex flex-col gap-3">
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
              onNavigate={(idx) => {
                navigate(appDetailPath(appKey, "overview", { instance: idx }));
              }}
            />
          ) : (
            <OverviewTab
              listeners={displayListeners}
              jobs={displayJobs}
              appKey={appKey}
              instanceQs={instanceQueryString}
              resolvedInstanceIndex={resolvedInstanceIndex}
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
            instanceIndex={instanceIndex}
            onSwitchToCode={(line) => {
              navigate(appDetailPath(appKey, "code", { line, instance: instanceIndex }));
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
