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

// ---- App management ----

export const getManifests = () => apiFetch<ManifestListResponse>("/apps/manifests");

export const startApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/start`);
export const stopApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/stop`);
export const reloadApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/reload`);

// ---- Telemetry ----

export const getAppHealth = (appKey: string, instanceIndex = 0) =>
  apiFetch<AppHealthData>(`/telemetry/app/${appKey}/health?instance_index=${instanceIndex}`);

export const getAppListeners = (appKey: string, instanceIndex = 0) =>
  apiFetch<ListenerData[]>(`/telemetry/app/${appKey}/listeners?instance_index=${instanceIndex}`);

export const getAppJobs = (appKey: string, instanceIndex = 0) =>
  apiFetch<JobData[]>(`/telemetry/app/${appKey}/jobs?instance_index=${instanceIndex}`);

export const getHandlerInvocations = (listenerId: number, limit = 50) =>
  apiFetch<HandlerInvocationData[]>(`/telemetry/handler/${listenerId}/invocations?limit=${limit}`);

export const getJobExecutions = (jobId: number, limit = 50) =>
  apiFetch<JobExecutionData[]>(`/telemetry/job/${jobId}/executions?limit=${limit}`);

export const getDashboardKpis = () => apiFetch<DashboardKpis>("/telemetry/dashboard/kpis");

export const getDashboardAppGrid = () =>
  apiFetch<{ apps: DashboardAppGridEntry[] }>("/telemetry/dashboard/app-grid");

export const getDashboardErrors = () =>
  apiFetch<{ errors: DashboardErrorEntry[] }>("/telemetry/dashboard/errors");

export const getTelemetryStatus = (signal?: AbortSignal) =>
  apiFetch<TelemetryStatus>("/telemetry/status", signal ? { signal } : undefined);

// ---- Logs ----

export const getRecentLogs = (params?: { level?: string; app_key?: string; limit?: number }) => {
  const search = new URLSearchParams();
  if (params?.level) search.set("level", params.level);
  if (params?.app_key) search.set("app_key", params.app_key);
  if (params?.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  return apiFetch<LogEntry[]>(`/logs/recent${qs ? `?${qs}` : ""}`);
};
