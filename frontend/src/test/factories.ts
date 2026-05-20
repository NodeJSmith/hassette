/**
 * Shared factory functions for test data objects.
 *
 * Each factory:
 * - Uses `satisfies` against the generated TypeScript type so missing required
 *   fields are caught by tsc at compile time, not silently left as undefined.
 * - Accepts `Partial<T>` overrides for flexible per-test customization.
 *
 * Use these instead of per-file factory functions to avoid duplication.
 */

import type { components } from "../api/generated-types";
import type { WsInvocationCompletedPayload, WsExecutionCompletedPayload } from "../api/ws-types";

type AppManifestResponse = components["schemas"]["AppManifestResponse"];
type ConfigResponse = components["schemas"]["ConfigResponse"];
type AppManifestListResponse = components["schemas"]["AppManifestListResponse"];
type DashboardAppGridEntry = components["schemas"]["DashboardAppGridEntry"];
type ListenerWithSummary = components["schemas"]["ListenerWithSummary"];
type JobSummary = components["schemas"]["JobSummary"];
type AppHealthResponse = components["schemas"]["AppHealthResponse"];
type LogEntryResponse = components["schemas"]["LogEntryResponse"];
type TelemetryStatusResponse = components["schemas"]["TelemetryStatusResponse"];
type AppInstanceResponse = components["schemas"]["AppInstanceResponse"];
type HandlerInvocation = components["schemas"]["HandlerInvocation"];
type JobExecution = components["schemas"]["JobExecution"];

// ---- Individual object factories ----

export function createInstance(overrides: Partial<AppInstanceResponse> = {}): AppInstanceResponse {
  return {
    app_key: "test_app",
    index: 0,
    instance_name: "inst_0",
    class_name: "TestApp",
    status: "running",
    error_message: null,
    error_traceback: null,
    owner_id: null,
    ...overrides,
  } satisfies AppInstanceResponse;
}

export function createManifest(overrides: Partial<AppManifestResponse> = {}): AppManifestResponse {
  return {
    app_key: "test_app",
    class_name: "TestApp",
    display_name: "Test App",
    filename: "test_app.py",
    enabled: true,
    auto_loaded: true,
    status: "running",
    block_reason: null,
    instance_count: 1,
    instances: [],
    error_message: null,
    error_traceback: null,
    recent_invocations_1h: 0,
    ...overrides,
  } satisfies AppManifestResponse;
}

export function createManifestList(overrides: Partial<AppManifestListResponse> = {}): AppManifestListResponse {
  return {
    total: 1,
    running: 1,
    failed: 0,
    stopped: 0,
    disabled: 0,
    blocked: 0,
    manifests: [createManifest()],
    only_app: null,
    ...overrides,
  } satisfies AppManifestListResponse;
}

export function createAppGridEntry(overrides: Partial<DashboardAppGridEntry> = {}): DashboardAppGridEntry {
  return {
    app_key: "test_app",
    status: "running",
    display_name: "Test App",
    instance_count: 1,
    handler_count: 3,
    job_count: 2,
    total_invocations: 10,
    total_errors: 0,
    total_timed_out: 0,
    total_executions: 5,
    total_job_errors: 0,
    total_job_timed_out: 0,
    avg_duration_ms: 50,
    last_activity_ts: 1700000000,
    health_status: "good",
    error_rate: 0,
    error_rate_class: "good",
    activity_buckets: [],
    last_error_message: null,
    last_error_type: null,
    last_error_ts: null,
    ...overrides,
  } satisfies DashboardAppGridEntry;
}

export function createListener(overrides: Partial<ListenerWithSummary> = {}): ListenerWithSummary {
  return {
    listener_id: 1,
    app_key: "test_app",
    instance_index: 0,
    topic: "state_changed",
    listener_kind: "state change",
    handler_method: "on_state_change",
    total_invocations: 0,
    successful: 0,
    failed: 0,
    di_failures: 0,
    cancelled: 0,
    timed_out: 0,
    avg_duration_ms: 0,
    min_duration_ms: null,
    max_duration_ms: null,
    total_duration_ms: 0,
    predicate_description: null,
    human_description: null,
    debounce: null,
    throttle: null,
    once: 0,
    priority: 0,
    last_invoked_at: null,
    last_error_message: null,
    last_error_type: null,
    source_location: "test_app.py:10",
    registration_source: null,
    handler_summary: "on_state_change()",
    source_tier: "app",
    immediate: 0,
    duration: null,
    entity_id: null,
    last_error_traceback: null,
    ...overrides,
  } satisfies ListenerWithSummary;
}

export function createJob(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: 1,
    app_key: "test_app",
    instance_index: 0,
    job_name: "test_job",
    handler_method: "run_task",
    trigger_type: "interval",
    trigger_label: "every 60s",
    trigger_detail: null,
    args_json: "[]",
    kwargs_json: "{}",
    source_location: "test_app.py:20",
    registration_source: null,
    source_tier: "app",
    total_executions: 0,
    successful: 0,
    failed: 0,
    timed_out: 0,
    last_executed_at: null,
    total_duration_ms: 0,
    avg_duration_ms: 0,
    group: null,
    next_run: null,
    fire_at: null,
    jitter: null,
    name_auto: false,
    last_error_message: null,
    last_error_type: null,
    last_error_ts: null,
    last_error_traceback: null,
    min_duration_ms: null,
    max_duration_ms: null,
    ...overrides,
  } satisfies JobSummary;
}

export function createHealthData(overrides: Partial<AppHealthResponse> = {}): AppHealthResponse {
  return {
    error_rate: 0,
    error_rate_class: "good",
    handler_avg_duration: 0,
    job_avg_duration: 0,
    last_activity_ts: null,
    health_status: "good",
    ...overrides,
  } satisfies AppHealthResponse;
}

export function createLogEntry(overrides: Partial<LogEntryResponse> = {}): LogEntryResponse {
  return {
    seq: 1,
    timestamp: 1700000000,
    level: "INFO",
    logger_name: "hassette.test",
    func_name: "test_func",
    lineno: 1,
    message: "test log message",
    exc_info: null,
    app_key: null,
    ...overrides,
  } satisfies LogEntryResponse;
}

export function createInvocationCompletedPayload(
  overrides: Partial<WsInvocationCompletedPayload> = {},
): WsInvocationCompletedPayload {
  return {
    listener_id: 1,
    app_key: "test_app",
    instance_index: 0,
    status: "success",
    duration_ms: 42,
    error_type: null,
    ...overrides,
  };
}

export function createExecutionCompletedPayload(
  overrides: Partial<WsExecutionCompletedPayload> = {},
): WsExecutionCompletedPayload {
  return {
    job_id: 1,
    app_key: "test_app",
    instance_index: 0,
    status: "success",
    duration_ms: 75,
    error_type: null,
    ...overrides,
  };
}

export function createTelemetryStatus(overrides: Partial<TelemetryStatusResponse> = {}): TelemetryStatusResponse {
  return {
    degraded: false,
    dropped_overflow: 0,
    dropped_exhausted: 0,
    dropped_no_session: 0,
    dropped_shutdown: 0,
    error_handler_failures: 0,
    ...overrides,
  } satisfies TelemetryStatusResponse;
}

export function createInvocation(overrides: Partial<HandlerInvocation> = {}): HandlerInvocation {
  return {
    execution_start_ts: 1700000000,
    duration_ms: 50,
    status: "success",
    source_tier: "app",
    error_type: null,
    error_message: null,
    execution_id: null,
    trigger_context_id: null,
    trigger_origin: null,
    ...overrides,
  } satisfies HandlerInvocation;
}

export function createExecution(overrides: Partial<JobExecution> = {}): JobExecution {
  return {
    execution_start_ts: 1700000000,
    duration_ms: 75,
    status: "success",
    source_tier: "app",
    error_type: null,
    error_message: null,
    execution_id: null,
    ...overrides,
  } satisfies JobExecution;
}

export function createSystemConfig(overrides: Partial<ConfigResponse> = {}): ConfigResponse {
  return {
    dev_mode: false,
    base_url: "",
    asyncio_debug_mode: false,
    allow_reload_in_prod: false,
    data_dir: "/home/user/.hassette/data",
    config_dir: "/home/user/.hassette",
    web_api: {
      run: true,
      run_ui: true,
      ui_hot_reload: false,
      host: "0.0.0.0",
      port: 8126,
      cors_origins: [],
      event_buffer_size: 500,
      log_buffer_size: 2000,
      job_history_size: 1000,
    },
    logging: {
      log_level: "INFO",
      web_api: "INFO",
    },
    lifecycle: {
      startup_timeout_seconds: 30,
      app_startup_timeout_seconds: 20,
      app_shutdown_timeout_seconds: 10,
    },
    apps: {
      autodetect: true,
      directory: "/home/user/apps",
    },
    scheduler: {
      min_delay_seconds: 1,
      max_delay_seconds: 30,
      default_delay_seconds: 15,
    },
    file_watcher: {
      watch_files: true,
      debounce_milliseconds: 3000,
    },
    ...overrides,
  } satisfies ConfigResponse;
}
