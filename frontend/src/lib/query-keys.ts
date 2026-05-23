export const queryKeys = {
  config: () => ["config"] as const,
  systemStatus: () => ["system-status"] as const,
  manifests: () => ["manifests"] as const,
  allListenersPalette: () => ["all-listeners-palette"] as const,
  recentLogs: (appKey?: string, executionId?: string | null) =>
    ["recent-logs", appKey ?? null, executionId ?? null] as const,
  allListeners: () => ["all-listeners"] as const,
  allJobs: () => ["all-jobs"] as const,
  dashboardGrid: () => ["dashboard-grid"] as const,
  handlerInvocations: (listenerId: number) => ["handler-invocations", listenerId] as const,
  jobExecutions: (jobId: number) => ["job-executions", jobId] as const,
  appListeners: {
    base: (appKey: string, idx: number) => ["app-listeners", appKey, idx] as const,
    prefix: (appKey: string) => ["app-listeners", appKey] as const,
  },
  appJobs: {
    base: (appKey: string, idx: number) => ["app-jobs", appKey, idx] as const,
    prefix: (appKey: string) => ["app-jobs", appKey] as const,
  },
  appActivity: {
    base: (appKey: string, idx: number) => ["app-activity", appKey, idx] as const,
    prefix: (appKey: string) => ["app-activity", appKey] as const,
  },
};
