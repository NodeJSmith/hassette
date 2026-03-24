/** Typed API endpoint functions for all Hassette REST endpoints. */

import { apiFetch, apiPost } from "./client";

// ---- App management ----

export interface AppManifest {
  app_key: string;
  class_name: string;
  display_name: string;
  filename: string;
  enabled: boolean;
  auto_loaded: boolean;
  status: string;
  block_reason: string | null;
  instance_count: number;
  instances: AppInstance[];
  error_message: string | null;
  error_traceback: string | null;
}

export interface AppInstance {
  app_key: string;
  index: number;
  instance_name: string;
  class_name: string;
  status: string;
  error_message: string | null;
  error_traceback: string | null;
}

export interface ManifestListResponse {
  total: number;
  running: number;
  failed: number;
  stopped: number;
  disabled: number;
  blocked: number;
  manifests: AppManifest[];
  only_app: string | null;
}

export const getManifests = () => apiFetch<ManifestListResponse>("/apps/manifests");

export const startApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/start`);
export const stopApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/stop`);
export const reloadApp = (appKey: string) => apiPost<{ status: string }>(`/apps/${appKey}/reload`);

// ---- Telemetry ----

export interface AppHealthData {
  error_rate: number;
  error_rate_class: string;
  handler_avg_duration: number;
  job_avg_duration: number;
  last_activity_ts: number | null;
  health_status: string;
}

export interface ListenerData {
  listener_id: number;
  app_key: string;
  instance_index: number;
  topic: string;
  handler_method: string;
  total_invocations: number;
  successful: number;
  failed: number;
  di_failures: number;
  cancelled: number;
  avg_duration_ms: number;
  min_duration_ms: number;
  max_duration_ms: number;
  total_duration_ms: number;
  predicate_description: string | null;
  human_description: string | null;
  debounce: number | null;
  throttle: number | null;
  once: number;
  priority: number;
  last_invoked_at: number | null;
  last_error_message: string | null;
  last_error_type: string | null;
  handler_summary: string;
  source_location: string;
  registration_source: string | null;
}

export interface DashboardKpis {
  total_handlers: number;
  total_jobs: number;
  total_invocations: number;
  total_executions: number;
  total_errors: number;
  total_job_errors: number;
  avg_handler_duration_ms: number;
  avg_job_duration_ms: number;
  error_rate: number;
  error_rate_class: string;
  uptime_seconds: number | null;
}

export interface DashboardAppGridEntry {
  app_key: string;
  status: string;
  display_name: string;
  handler_count: number;
  job_count: number;
  total_invocations: number;
  total_errors: number;
  total_executions: number;
  total_job_errors: number;
  avg_duration_ms: number;
  health_status: string;
  last_activity_ts: number | null;
}

export interface DashboardErrorEntry {
  kind: "handler" | "job";
  error_message: string;
  error_type: string;
  timestamp: number;
  app_key: string;
  listener_id?: number;
  topic?: string;
  handler_method?: string;
  job_id?: number;
  job_name?: string;
}

export const getAppHealth = (appKey: string, instanceIndex = 0) =>
  apiFetch<AppHealthData>(`/telemetry/app/${appKey}/health?instance_index=${instanceIndex}`);

export const getAppListeners = (appKey: string, instanceIndex = 0) =>
  apiFetch<ListenerData[]>(`/telemetry/app/${appKey}/listeners?instance_index=${instanceIndex}`);

/** Matches backend `JobSummary` Pydantic model from `telemetry_models.py`. */
export interface JobData {
  job_id: number;
  app_key: string;
  instance_index: number;
  job_name: string;
  handler_method: string;
  trigger_type: string | null;
  trigger_value: string | null;
  repeat: number;
  args_json: string;
  kwargs_json: string;
  source_location: string;
  registration_source: string | null;
  total_executions: number;
  successful: number;
  failed: number;
  last_executed_at: number | null;
  total_duration_ms: number;
  avg_duration_ms: number;
}

/** Matches backend `HandlerInvocation` Pydantic model from `telemetry_models.py`. */
export interface HandlerInvocationData {
  execution_start_ts: number;
  duration_ms: number;
  status: string;
  error_type: string | null;
  error_message: string | null;
  error_traceback: string | null;
}

/** Matches backend `JobExecution` Pydantic model from `telemetry_models.py`. */
export interface JobExecutionData {
  execution_start_ts: number;
  duration_ms: number;
  status: string;
  error_type: string | null;
  error_message: string | null;
}

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

// ---- Logs ----

export interface LogEntry {
  seq: number;
  timestamp: number;
  level: string;
  logger_name: string;
  func_name: string;
  lineno: number;
  message: string;
  exc_info: string | null;
  app_key: string | null;
}

export const getRecentLogs = (params?: { level?: string; app_key?: string; limit?: number }) => {
  const search = new URLSearchParams();
  if (params?.level) search.set("level", params.level);
  if (params?.app_key) search.set("app_key", params.app_key);
  if (params?.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  return apiFetch<LogEntry[]>(`/logs/recent${qs ? `?${qs}` : ""}`);
};
