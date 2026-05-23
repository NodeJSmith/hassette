export const queryKeys = {
  config: () => ["config"] as const,
  systemStatus: () => ["system-status"] as const,
  manifests: () => ["manifests"] as const,
  allListenersPalette: () => ["all-listeners-palette"] as const,
  recentLogs: (appKey?: string, executionId?: string | null) =>
    ["recent-logs", appKey ?? null, executionId ?? null] as const,
  allListeners: {
    base: () => ["all-listeners"] as const,
    prefix: () => ["all-listeners"] as const,
  },
  allJobs: {
    base: () => ["all-jobs"] as const,
    prefix: () => ["all-jobs"] as const,
  },
  dashboardGrid: {
    base: () => ["dashboard-grid"] as const,
    prefix: () => ["dashboard-grid"] as const,
  },
  appListeners: {
    base: (appKey: string, idx: number) => ["app-listeners", appKey, idx] as const,
    prefix: (appKey: string) => ["app-listeners", appKey] as const,
  },
  appJobs: {
    base: (appKey: string, idx: number) => ["app-jobs", appKey, idx] as const,
    prefix: (appKey: string) => ["app-jobs", appKey] as const,
  },
  handlerInvocations: {
    base: (listenerId: number) => ["handler-invocations", listenerId] as const,
    prefix: (listenerId: number) => ["handler-invocations", listenerId] as const,
  },
  jobExecutions: {
    base: (jobId: number) => ["job-executions", jobId] as const,
    prefix: (jobId: number) => ["job-executions", jobId] as const,
  },
  appActivity: {
    base: (appKey: string, idx: number) => ["app-activity", appKey, idx] as const,
    prefix: (appKey: string) => ["app-activity", appKey] as const,
  },
};
