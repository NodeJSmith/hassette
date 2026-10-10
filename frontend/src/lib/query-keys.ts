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
  recentLogs: (appKey?: string, executionId?: string | null) =>
    ["recent-logs", appKey ?? null, executionId ?? null] as const,
  allListeners: () => ["all-listeners"] as const,
  allJobs: () => ["all-jobs"] as const,
  appGrid: () => ["app-grid"] as const,
  listenerExecutions: (listenerId: number) => ["listener-executions", listenerId] as const,
  jobExecutions: (jobId: number) => ["job-executions", jobId] as const,
  appListeners: {
    base: (appKey: string, instanceIndex: number) => ["app-listeners", appKey, instanceIndex] as const,
    prefix: (appKey: string) => ["app-listeners", appKey] as const,
  },
  appJobs: {
    base: (appKey: string, instanceIndex: number) => ["app-jobs", appKey, instanceIndex] as const,
    prefix: (appKey: string) => ["app-jobs", appKey] as const,
  },
  appBlocking: {
    // `undefined` is every instance (the multi-instance parent overview), keyed apart from any index.
    base: (appKey: string, instanceIndex: number | undefined) =>
      ["app-blocking", appKey, instanceIndex ?? "all"] as const,
    prefix: (appKey: string) => ["app-blocking", appKey] as const,
  },
  unattributedBlocking: () => ["unattributed-blocking"] as const,
  appActivity: {
    base: (appKey: string, instanceIndex: number) => ["app-activity", appKey, instanceIndex] as const,
    prefix: (appKey: string) => ["app-activity", appKey] as const,
  },
  appHealth: {
    base: (appKey: string, instanceIndex: number) => ["app-health", appKey, instanceIndex] as const,
    prefix: (appKey: string) => ["app-health", appKey] as const,
  },
};
