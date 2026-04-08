/** Typed API endpoint functions for all Hassette REST endpoints. */

import type { components } from "./generated-types";
import { apiFetch, apiPost } from "./client";

// ---- Generated type aliases ----

export type AppManifest = components["schemas"]["AppManifestResponse"];
export type AppInstance = components["schemas"]["AppInstanceResponse"];
export type ManifestListResponse = components["schemas"]["AppManifestListResponse"];
export type AppHealthData = components["schemas"]["AppHealthResponse"];
export type ListenerData = components["schemas"]["ListenerWithSummary"];
export type DashboardKpis = components["schemas"]["DashboardKpisResponse"];
export type DashboardAppGridEntry = components["schemas"]["DashboardAppGridEntry"];
export type HandlerErrorEntry = components["schemas"]["HandlerErrorEntry"];
export type JobErrorEntry = components["schemas"]["JobErrorEntry"];
export type DashboardErrorEntry = HandlerErrorEntry | JobErrorEntry;
export type JobData = components["schemas"]["JobSummary"];
export type HandlerInvocationData = components["schemas"]["HandlerInvocation"];
export type JobExecutionData = components["schemas"]["JobExecution"];
export type TelemetryStatus = components["schemas"]["TelemetryStatusResponse"];
export type LogEntry = components["schemas"]["LogEntryResponse"];
export type SessionListEntry = components["schemas"]["SessionRecord"];

// ---- App management ----

export const getManifests = () => apiFetch<ManifestListResponse>("/apps/manifests");

export const startApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/start`);
export const stopApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/stop`);
export const reloadApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/reload`);

// ---- Telemetry ----

/** Append `&session_id=N` (or `?session_id=N`) to a URL when sessionId is provided. */
function withSession(url: string, sessionId?: number | null): string {
  if (sessionId === null || sessionId === undefined) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}session_id=${sessionId}`;
}

export const getAppHealth = (appKey: string, instanceIndex = 0, sessionId?: number | null) =>
  apiFetch<AppHealthData>(withSession(`/telemetry/app/${appKey}/health?instance_index=${instanceIndex}`, sessionId));

export const getAppListeners = (appKey: string, instanceIndex = 0, sessionId?: number | null) =>
  apiFetch<ListenerData[]>(withSession(`/telemetry/app/${appKey}/listeners?instance_index=${instanceIndex}`, sessionId));

export const getAppJobs = (appKey: string, instanceIndex = 0, sessionId?: number | null) =>
  apiFetch<JobData[]>(withSession(`/telemetry/app/${appKey}/jobs?instance_index=${instanceIndex}`, sessionId));

export const getHandlerInvocations = (listenerId: number, limit = 50, sessionId?: number | null) =>
  apiFetch<HandlerInvocationData[]>(withSession(`/telemetry/handler/${listenerId}/invocations?limit=${limit}`, sessionId));

export const getJobExecutions = (jobId: number, limit = 50, sessionId?: number | null) =>
  apiFetch<JobExecutionData[]>(withSession(`/telemetry/job/${jobId}/executions?limit=${limit}`, sessionId));

export type SourceTier = "app" | "framework" | "all";

export const getDashboardKpis = (sessionId?: number | null, sourceTier?: SourceTier) => {
  let url = withSession("/telemetry/dashboard/kpis", sessionId);
  if (sourceTier) url += (url.includes("?") ? "&" : "?") + `source_tier=${sourceTier}`;
  return apiFetch<DashboardKpis>(url);
};

export const getDashboardAppGrid = (sessionId?: number | null) =>
  apiFetch<{ apps: DashboardAppGridEntry[] }>(withSession("/telemetry/dashboard/app-grid", sessionId));

export const getDashboardErrors = (sessionId?: number | null, sourceTier?: SourceTier) => {
  let url = withSession("/telemetry/dashboard/errors", sessionId);
  if (sourceTier) url += (url.includes("?") ? "&" : "?") + `source_tier=${sourceTier}`;
  return apiFetch<{ errors: DashboardErrorEntry[] }>(url);
};

export const getTelemetryStatus = (signal?: AbortSignal) =>
  apiFetch<TelemetryStatus>("/telemetry/status", signal ? { signal } : undefined);

// ---- Sessions ----

export const getSessionList = (limit = 50) =>
  apiFetch<SessionListEntry[]>(`/telemetry/sessions?limit=${limit}`);

// ---- Logs ----

export const getRecentLogs = (params?: { level?: string; app_key?: string; limit?: number }) => {
  const search = new URLSearchParams();
  if (params?.level) search.set("level", params.level);
  if (params?.app_key) search.set("app_key", params.app_key);
  if (params?.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  return apiFetch<LogEntry[]>(`/logs/recent${qs ? `?${qs}` : ""}`);
};
