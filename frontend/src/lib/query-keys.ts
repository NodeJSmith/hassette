import type { LogAuthorQuery } from "@/api/endpoints";

export const queryKeys = {
  config: () => ["config"] as const,
  systemStatus: () => ["system-status"] as const,
  telemetryStatus: () => ["telemetry-status"] as const,
  manifests: () => ["manifests"] as const,
  manifest: {
    base: (appKey: string) => ["manifest", appKey] as const,
    prefix: () => ["manifest"] as const,
  },
  allListenersPalette: () => ["all-listeners-palette"] as const,
  recentLogs: (appKey?: string, executionId?: string | null, author?: LogAuthorQuery) =>
    ["recent-logs", appKey ?? null, executionId ?? null, author ?? null] as const,
  allListeners: () => ["all-listeners"] as const,
  allJobs: () => ["all-jobs"] as const,
  appGrid: () => ["app-grid"] as const,
  listenerExecutions: (listenerId: number) => ["listener-executions", listenerId] as const,
  jobExecutions: (jobId: number) => ["job-executions", jobId] as const,
  // The instance slot is `null` for every instance, which no instance name can collide with.
  appListeners: {
    base: (appKey: string, instanceName: string | undefined) =>
      ["app-listeners", appKey, instanceName ?? null] as const,
    prefix: (appKey: string) => ["app-listeners", appKey] as const,
  },
  appJobs: {
    base: (appKey: string, instanceName: string | undefined) => ["app-jobs", appKey, instanceName ?? null] as const,
    prefix: (appKey: string) => ["app-jobs", appKey] as const,
  },
  appBlocking: {
    base: (appKey: string, instanceName: string | undefined) => ["app-blocking", appKey, instanceName ?? null] as const,
    prefix: (appKey: string) => ["app-blocking", appKey] as const,
  },
  unattributedBlocking: () => ["unattributed-blocking"] as const,
  appActivity: {
    base: (appKey: string, instanceName: string | undefined) => ["app-activity", appKey, instanceName ?? null] as const,
    prefix: (appKey: string) => ["app-activity", appKey] as const,
  },
  appHealth: {
    base: (appKey: string, instanceName: string | undefined) => ["app-health", appKey, instanceName ?? null] as const,
    prefix: (appKey: string) => ["app-health", appKey] as const,
  },
};
