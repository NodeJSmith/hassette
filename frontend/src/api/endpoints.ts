/** Typed API endpoint functions for all Hassette REST endpoints. */

import type { components } from "./generated-types";
import { apiFetch, apiPost } from "./client";

// ---- Generated type aliases ----

export type AppManifest = components["schemas"]["AppManifestResponse"];
export type AppInstance = components["schemas"]["AppInstanceResponse"];
export type ManifestListResponse = components["schemas"]["AppManifestListResponse"];
export type AppHealthData = components["schemas"]["AppHealthResponse"];
export type ListenerData = components["schemas"]["ListenerWithSummary"];
export type DashboardAppGridEntry = components["schemas"]["DashboardAppGridEntry"];
export type JobData = components["schemas"]["JobSummary"];
export type HandlerInvocationData = components["schemas"]["HandlerInvocation"];
export type JobExecutionData = components["schemas"]["JobExecution"];
export type TelemetryStatus = components["schemas"]["TelemetryStatusResponse"];
export type LogEntry = components["schemas"]["LogEntryResponse"];
export type AppConfigData = components["schemas"]["AppConfigResponse"];
export type AppSourceData = components["schemas"]["AppSourceResponse"];

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

export const startApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${encodeURIComponent(appKey)}/start`);
export const stopApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${encodeURIComponent(appKey)}/stop`);
export const reloadApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${encodeURIComponent(appKey)}/reload`);

export const getAppConfig = (appKey: string) =>
  apiFetch<AppConfigData>(`/apps/${encodeURIComponent(appKey)}/config`);

export const getAppSource = (appKey: string) =>
  apiFetch<AppSourceData>(`/apps/${encodeURIComponent(appKey)}/source`);

// ---- Telemetry ----

export const getAppHealth = (appKey: string, instanceIndex = 0, since?: number | null) =>
  apiFetch<AppHealthData>(buildUrl(`/telemetry/app/${encodeURIComponent(appKey)}/health`, { instance_index: instanceIndex, since }));

export const getAppListeners = (appKey: string, instanceIndex = 0, since?: number | null) =>
  apiFetch<ListenerData[]>(buildUrl(`/telemetry/app/${encodeURIComponent(appKey)}/listeners`, { instance_index: instanceIndex, since }));

export const getAppJobs = (appKey: string, instanceIndex = 0, since?: number | null) =>
  apiFetch<JobData[]>(buildUrl(`/telemetry/app/${encodeURIComponent(appKey)}/jobs`, { instance_index: instanceIndex, since }));

export const getHandlerInvocations = (listenerId: number, limit = 50, since?: number | null) =>
  apiFetch<HandlerInvocationData[]>(buildUrl(`/telemetry/handler/${listenerId}/invocations`, { limit, since }));

export const getJobExecutions = (jobId: number, limit = 50, since?: number | null) =>
  apiFetch<JobExecutionData[]>(buildUrl(`/telemetry/job/${jobId}/executions`, { limit, since }));

export const getDashboardAppGrid = (since?: number | null) =>
  apiFetch<{ apps: DashboardAppGridEntry[] }>(buildUrl("/telemetry/dashboard/app-grid", { since }));

export const getTelemetryStatus = (signal?: AbortSignal) =>
  apiFetch<TelemetryStatus>("/telemetry/status", signal ? { signal } : undefined);

// ---- System config ----

export type SystemConfig = components["schemas"]["ConfigResponse"];

export const getConfig = () => apiFetch<SystemConfig>("/config");

// ---- Logs ----

export const getRecentLogs = (params?: { level?: string; app_key?: string; limit?: number }) =>
  apiFetch<LogEntry[]>(buildUrl("/logs/recent", {
    level: params?.level,
    app_key: params?.app_key,
    limit: params?.limit,
  }));

// ---- Bus ----

export const getAllListeners = (since?: number | null) =>
  apiFetch<ListenerData[]>(buildUrl("/bus/listeners", { since }));

// ---- Scheduler (global) ----

export const getAllJobs = (since?: number | null) =>
  apiFetch<JobData[]>(buildUrl("/scheduler/jobs", { since }));

// ---- System status ----

export type SystemStatus = components["schemas"]["SystemStatusResponse"];
export type BootIssue = components["schemas"]["BootIssueResponse"];

export const getSystemStatus = () => apiFetch<SystemStatus>("/health");
