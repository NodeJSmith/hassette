// dup-ignore-file: endpoint functions share apiFetch + buildUrl call shape by design
/** Typed API endpoint functions for all Hassette REST endpoints. */

import { DETAIL_FETCH_LIMIT } from "../utils/constants";
import { apiFetch, apiPost } from "./client";
import type { ConfigRecord, SchemaNode } from "./config-view-types";
import type { components } from "./generated-types";

export type AppStatus = components["schemas"]["AppStatus"];
export type ResourceStatus = components["schemas"]["ResourceStatus"];
export type AppManifest = components["schemas"]["AppSummary"];
export type AppInstance = components["schemas"]["AppInstanceResponse"];
export type ManifestListResponse = components["schemas"]["AppListResponse"];
export type ListenerData = components["schemas"]["ListenerWithSummary"];
export type AppGridEntry = components["schemas"]["AppGridEntry"];
export type AppActivity = components["schemas"]["AppActivity"];
export type AppGridResponse = components["schemas"]["AppGridResponse"];
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
export type AppHealthData = components["schemas"]["AppHealth"];
export type ActionResponse = components["schemas"]["ActionResponse"];
export type JobTriggerResponse = components["schemas"]["JobTriggerResponse"];
export type SystemConfig = Omit<components["schemas"]["ConfigSchemaResponse"], "config_schema" | "config_values"> & {
  config_schema: SchemaNode;
  config_values: ConfigRecord;
};
export type SystemStatus = components["schemas"]["SystemStatusResponse"];
export type BootIssue = components["schemas"]["BootIssueResponse"];
export type BlockingFindingsData = components["schemas"]["BlockingFindingsResponse"];
export type BlockingFinding = components["schemas"]["BlockingFinding"];
export type StackFrame = components["schemas"]["StackFrame"];
export type BlockingFrameRef = components["schemas"]["BlockingFrameRef"];
export type UnattributedBlockingData = components["schemas"]["UnattributedBlockingResponse"];
export type UnattributedStall = components["schemas"]["UnattributedStall"];

export const WS_PATH = "/api/ws";

function buildUrl(path: string, params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined) search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

const appPath = (appKey: string) => `/apps/${encodeURIComponent(appKey)}`;
const telemetryAppPath = (appKey: string) => `/telemetry/app/${encodeURIComponent(appKey)}`;

export const getAppManifests = () => apiFetch<ManifestListResponse>("/apps");

export const getAppManifest = (appKey: string) => apiFetch<AppManifest>(appPath(appKey));

export const startApp = (appKey: string) => apiPost<ActionResponse>(`${appPath(appKey)}/start`);
export const stopApp = (appKey: string) => apiPost<ActionResponse>(`${appPath(appKey)}/stop`);
export const reloadApp = (appKey: string) => apiPost<ActionResponse>(`${appPath(appKey)}/reload`);

export const startInstance = (appKey: string, index: number) =>
  apiPost<ActionResponse>(`${appPath(appKey)}/instances/${index}/start`);
export const stopInstance = (appKey: string, index: number) =>
  apiPost<ActionResponse>(`${appPath(appKey)}/instances/${index}/stop`);
export const reloadInstance = (appKey: string, index: number) =>
  apiPost<ActionResponse>(`${appPath(appKey)}/instances/${index}/reload`);

export const getAppConfig = (appKey: string, signal?: AbortSignal) =>
  apiFetch<AppConfigData>(`${appPath(appKey)}/config`, { signal });

export const getAppSource = (appKey: string, signal?: AbortSignal) =>
  apiFetch<AppSourceData>(`${appPath(appKey)}/source`, { signal });

export const getAppListeners = (appKey: string, instanceIndex = 0, since?: number | null, signal?: AbortSignal) =>
  apiFetch<ListenerData[]>(
    buildUrl(`${telemetryAppPath(appKey)}/listeners`, { instance_index: instanceIndex, since }),
    { signal },
  );

export const getAppJobs = (appKey: string, instanceIndex = 0, since?: number | null, signal?: AbortSignal) =>
  apiFetch<JobData[]>(buildUrl(`${telemetryAppPath(appKey)}/jobs`, { instance_index: instanceIndex, since }), {
    signal,
  });

/** Omit `instanceIndex` for findings across every instance (the multi-instance parent overview). */
export const getAppBlockingFindings = (
  appKey: string,
  instanceIndex: number | undefined,
  since?: number | null,
  signal?: AbortSignal,
) =>
  apiFetch<BlockingFindingsData>(
    buildUrl(`${telemetryAppPath(appKey)}/blocking`, { instance_index: instanceIndex, since }),
    { signal },
  );

export const getUnattributedBlocking = (since?: number | null, signal?: AbortSignal) =>
  apiFetch<UnattributedBlockingData>(buildUrl("/telemetry/blocking/unattributed", { since }), { signal });

export const getAppActivity = (
  appKey: string,
  instanceIndex = 0,
  limit = DETAIL_FETCH_LIMIT,
  since?: number | null,
  signal?: AbortSignal,
) =>
  apiFetch<ActivityFeedEntryData[]>(
    buildUrl(`${telemetryAppPath(appKey)}/activity`, { instance_index: instanceIndex, limit, since }),
    { signal },
  );

export const getAppHealth = (appKey: string, instanceIndex = 0, since?: number | null, signal?: AbortSignal) =>
  apiFetch<AppHealthData>(buildUrl(`${telemetryAppPath(appKey)}/health`, { instance_index: instanceIndex, since }), {
    signal,
  });

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

export const getExecutionById = (executionId: string, signal?: AbortSignal) =>
  apiFetch<ExecutionData | null>(`/telemetry/execution/${executionId}`, { signal });

export const getAppGrid = (since?: number | null, signal?: AbortSignal) =>
  apiFetch<AppGridResponse>(buildUrl("/telemetry/app-grid", { since }), { signal });

export const getTelemetryStatus = (signal?: AbortSignal) => apiFetch<TelemetryStatus>("/telemetry/status", { signal });

export const getConfig = () => apiFetch<SystemConfig>("/config");

interface LogFilterParams {
  level?: string;
  appKey?: string;
  limit?: number;
  since?: number | null;
  executionId?: string | null;
  sourceTier?: string | null;
}

const buildLogFilterParams = (params?: LogFilterParams) => ({
  level: params?.level,
  app_key: params?.appKey,
  limit: params?.limit,
  since: params?.since,
  execution_id: params?.executionId,
  source_tier: params?.sourceTier,
});

export const getRecentLogs = (params?: LogFilterParams, signal?: AbortSignal) =>
  apiFetch<LogEntry[]>(buildUrl("/logs/recent", buildLogFilterParams(params)), { signal });

export const getAllListeners = (since?: number | null, signal?: AbortSignal) =>
  apiFetch<ListenerData[]>(buildUrl("/bus/listeners", { since }), { signal });

export const getAllJobs = (since?: number | null, signal?: AbortSignal) =>
  apiFetch<JobData[]>(buildUrl("/scheduler/jobs", { since }), { signal });

export const triggerJob = (jobId: number) => apiPost<JobTriggerResponse>(`/scheduler/jobs/${jobId}/trigger`);

export const getSystemStatus = (signal?: AbortSignal) => apiFetch<SystemStatus>("/health", { signal });
