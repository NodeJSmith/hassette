/** Typed API endpoint functions for all Hassette REST endpoints. */

import { DETAIL_FETCH_LIMIT } from "../utils/constants";
import { apiFetch, apiPost, apiPut } from "./client";
import type { ConfigRecord, SchemaNode } from "./config-view-types";
import type { components } from "./generated-types";

// ---- Generated type aliases ----

export type AppManifest = components["schemas"]["AppManifestResponse"];
export type AppInstance = components["schemas"]["AppInstanceResponse"];
export type ManifestListResponse = components["schemas"]["AppManifestListResponse"];
export type AppHealthData = components["schemas"]["AppHealthResponse"];
export type ListenerData = components["schemas"]["ListenerWithSummary"];
export type DashboardAppGridEntry = components["schemas"]["DashboardAppGridEntry"];
export type JobData = components["schemas"]["JobSummary"];
export type ExecutionData = components["schemas"]["Execution"];
export type TelemetryStatus = components["schemas"]["TelemetryStatusResponse"];
export type LogEntry = components["schemas"]["LogEntryResponse"];
// The config schema rides in a `dict[str, Any]` field, so the generated type is a bare
// index signature. Narrow it to `SchemaNode` here — the single boundary where the config
// view's shape is asserted — so consumers read typed fields without per-call-site casts.
export type AppConfigData = Omit<components["schemas"]["AppConfigResponse"], "config_schema"> & {
  config_schema?: SchemaNode | null;
};
export type AppSourceData = components["schemas"]["AppSourceResponse"];
export type ActivityFeedEntryData = components["schemas"]["ActivityFeedEntry"];

export const WS_PATH = "/api/ws";

// ---- Query string helpers ----

function buildUrl(path: string, params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, val] of Object.entries(params)) {
    if (val !== null && val !== undefined) search.set(key, String(val));
  }
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

// ---- App management ----

export const getManifests = () => apiFetch<ManifestListResponse>("/apps/manifests");

export const getManifest = (appKey: string) => apiFetch<AppManifest>(`/apps/${encodeURIComponent(appKey)}/manifest`);

export const startApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${encodeURIComponent(appKey)}/start`);
export const stopApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${encodeURIComponent(appKey)}/stop`);
export const reloadApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${encodeURIComponent(appKey)}/reload`);

export const getAppConfig = (appKey: string, signal?: AbortSignal) =>
  apiFetch<AppConfigData>(`/apps/${encodeURIComponent(appKey)}/config`, { signal });

export const getAppSource = (appKey: string, signal?: AbortSignal) =>
  apiFetch<AppSourceData>(`/apps/${encodeURIComponent(appKey)}/source`, { signal });

// ---- Telemetry ----

export const getAppHealth = (appKey: string, instanceIndex = 0, since?: number | null) =>
  apiFetch<AppHealthData>(
    buildUrl(`/telemetry/app/${encodeURIComponent(appKey)}/health`, { instance_index: instanceIndex, since }),
  );

export const getAppListeners = (appKey: string, instanceIndex = 0, since?: number | null, signal?: AbortSignal) =>
  apiFetch<ListenerData[]>(
    buildUrl(`/telemetry/app/${encodeURIComponent(appKey)}/listeners`, { instance_index: instanceIndex, since }),
    { signal },
  );

export const getAppJobs = (appKey: string, instanceIndex = 0, since?: number | null, signal?: AbortSignal) =>
  apiFetch<JobData[]>(
    buildUrl(`/telemetry/app/${encodeURIComponent(appKey)}/jobs`, { instance_index: instanceIndex, since }),
    { signal },
  );

export const getAppActivity = (
  appKey: string,
  instanceIndex?: number | null,
  limit = DETAIL_FETCH_LIMIT,
  since?: number | null,
  signal?: AbortSignal,
) =>
  apiFetch<ActivityFeedEntryData[]>(
    buildUrl(`/telemetry/app/${encodeURIComponent(appKey)}/activity`, { instance_index: instanceIndex, limit, since }),
    { signal },
  );

export const getListenerExecutions = (
  listenerId: number,
  limit = DETAIL_FETCH_LIMIT,
  since?: number | null,
  signal?: AbortSignal,
) =>
  apiFetch<ExecutionData[]>(buildUrl(`/telemetry/listener/${listenerId}/executions`, { limit, since }), {
    signal,
  });

export const getJobExecutions = (
  jobId: number,
  limit = DETAIL_FETCH_LIMIT,
  since?: number | null,
  signal?: AbortSignal,
) => apiFetch<ExecutionData[]>(buildUrl(`/telemetry/job/${jobId}/executions`, { limit, since }), { signal });

export const getExecutions = (
  params?: {
    kind?: "handler" | "job" | null;
    limit?: number | null;
    since?: number | null;
  },
  signal?: AbortSignal,
) =>
  apiFetch<ExecutionData[]>(
    buildUrl("/telemetry/executions", { kind: params?.kind, limit: params?.limit, since: params?.since }),
    { signal },
  );

export const getDashboardAppGrid = (since?: number | null, signal?: AbortSignal) =>
  apiFetch<{ apps: DashboardAppGridEntry[] }>(buildUrl("/telemetry/dashboard/app-grid", { since }), { signal });

export const getTelemetryStatus = (signal?: AbortSignal) => apiFetch<TelemetryStatus>("/telemetry/status", { signal });

// ---- System config ----

export type SystemConfig = Omit<components["schemas"]["ConfigSchemaResponse"], "config_schema" | "config_values"> & {
  config_schema: SchemaNode;
  config_values: ConfigRecord;
};

export const getConfig = () => apiFetch<SystemConfig>("/config");

// ---- Logs ----

export type LogsByExecutionResponse = components["schemas"]["LogsByExecutionResponse"];
export type LogLevelResponse = components["schemas"]["LogLevelResponse"];

export const getRecentLogs = (
  params?: {
    level?: string;
    app_key?: string;
    limit?: number;
    since?: number | null;
    execution_id?: string | null;
    source_tier?: string | null;
  },
  signal?: AbortSignal,
) =>
  apiFetch<LogEntry[]>(
    buildUrl("/logs/recent", {
      level: params?.level,
      app_key: params?.app_key,
      limit: params?.limit,
      since: params?.since,
      execution_id: params?.execution_id,
      source_tier: params?.source_tier,
    }),
    { signal },
  );

export const getLogsByExecution = (executionId: string, limit?: number) =>
  apiFetch<LogsByExecutionResponse>(buildUrl(`/executions/${encodeURIComponent(executionId)}`, { limit }));

export const setLogLevel = (logger: string, level: string) =>
  apiPut<LogLevelResponse>("/logs/level", { logger, level });

// ---- Bus ----

export const getAllListeners = (since?: number | null, signal?: AbortSignal) =>
  apiFetch<ListenerData[]>(buildUrl("/bus/listeners", { since }), { signal });

// ---- Scheduler (global) ----

export const getAllJobs = (since?: number | null, signal?: AbortSignal) =>
  apiFetch<JobData[]>(buildUrl("/scheduler/jobs", { since }), { signal });

// ---- System status ----

export type SystemStatus = components["schemas"]["SystemStatusResponse"];
export type BootIssue = components["schemas"]["BootIssueResponse"];

export const getSystemStatus = () => apiFetch<SystemStatus>("/health");
