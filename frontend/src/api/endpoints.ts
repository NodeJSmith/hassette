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

export const startApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/start`);
export const stopApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/stop`);
export const reloadApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/reload`);

// ---- Telemetry ----

export const getAppHealth = (appKey: string, instanceIndex = 0, sessionId?: number | null) =>
  apiFetch<AppHealthData>(buildUrl(`/telemetry/app/${appKey}/health`, { instance_index: instanceIndex, session_id: sessionId }));

export const getAppListeners = (appKey: string, instanceIndex = 0, sessionId?: number | null) =>
  apiFetch<ListenerData[]>(buildUrl(`/telemetry/app/${appKey}/listeners`, { instance_index: instanceIndex, session_id: sessionId }));

export const getAppJobs = (appKey: string, instanceIndex = 0, sessionId?: number | null) =>
  apiFetch<JobData[]>(buildUrl(`/telemetry/app/${appKey}/jobs`, { instance_index: instanceIndex, session_id: sessionId }));

export const getHandlerInvocations = (listenerId: number, limit = 50, sessionId?: number | null) =>
  apiFetch<HandlerInvocationData[]>(buildUrl(`/telemetry/handler/${listenerId}/invocations`, { limit, session_id: sessionId }));

export const getJobExecutions = (jobId: number, limit = 50, sessionId?: number | null) =>
  apiFetch<JobExecutionData[]>(buildUrl(`/telemetry/job/${jobId}/executions`, { limit, session_id: sessionId }));

export type SourceTier = "app" | "framework" | "all";

export const getDashboardKpis = (sessionId?: number | null, sourceTier?: SourceTier) =>
  apiFetch<DashboardKpis>(buildUrl("/telemetry/dashboard/kpis", {
    session_id: sessionId,
    source_tier: sourceTier && sourceTier !== "all" ? sourceTier : undefined,
  }));

export const getDashboardAppGrid = (sessionId?: number | null) =>
  apiFetch<{ apps: DashboardAppGridEntry[] }>(buildUrl("/telemetry/dashboard/app-grid", { session_id: sessionId }));

export type FrameworkSummary = components["schemas"]["FrameworkSummaryResponse"];

export const getFrameworkSummary = (sessionId?: number | null) =>
  apiFetch<FrameworkSummary>(buildUrl("/telemetry/dashboard/framework-summary", { session_id: sessionId }));

export const getDashboardErrors = (sessionId?: number | null, sourceTier?: SourceTier) =>
  apiFetch<{ errors: DashboardErrorEntry[] }>(buildUrl("/telemetry/dashboard/errors", {
    session_id: sessionId,
    source_tier: sourceTier && sourceTier !== "all" ? sourceTier : undefined,
  }));

export const getTelemetryStatus = (signal?: AbortSignal) =>
  apiFetch<TelemetryStatus>("/telemetry/status", signal ? { signal } : undefined);

// ---- Sessions ----

export const getSessionList = (limit = 50) =>
  apiFetch<SessionListEntry[]>(buildUrl("/telemetry/sessions", { limit }));

// ---- Logs ----

export const getRecentLogs = (params?: { level?: string; app_key?: string; limit?: number }) =>
  apiFetch<LogEntry[]>(buildUrl("/logs/recent", {
    level: params?.level,
    app_key: params?.app_key,
    limit: params?.limit,
  }));
