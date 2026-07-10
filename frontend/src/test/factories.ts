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
import type { WsExecutionCompletedPayload } from "../api/ws-types";

type AppManifestResponse = components["schemas"]["AppManifestResponse"];
type ConfigSchemaResponse = components["schemas"]["ConfigSchemaResponse"];
type AppManifestListResponse = components["schemas"]["AppManifestListResponse"];
type DashboardAppGridEntry = components["schemas"]["DashboardAppGridEntry"];
type ListenerWithSummary = components["schemas"]["ListenerWithSummary"];
type JobSummary = components["schemas"]["JobSummary"];
type AppHealthResponse = components["schemas"]["AppHealthResponse"];
type LogEntryResponse = components["schemas"]["LogEntryResponse"];
type TelemetryStatusResponse = components["schemas"]["TelemetryStatusResponse"];
type AppInstanceResponse = components["schemas"]["AppInstanceResponse"];
type Execution = components["schemas"]["Execution"];

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
    autostart: true,
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
    thread_leaked: 0,
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
    mode: "single",
    backpressure: "block",
    suppressed_count: 0,
    dropped_count: 0,
    backpressure_dropped_count: 0,
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
    predicate_description: null,
    human_description: null,
    total_executions: 0,
    successful: 0,
    failed: 0,
    cancelled: 0,
    timed_out: 0,
    skipped: 0,
    thread_leaked: 0,
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
    mode: "single",
    suppressed_count: 0,
    dropped_count: 0,
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

export function createExecutionCompletedPayload(
  overrides: Partial<WsExecutionCompletedPayload> = {},
): WsExecutionCompletedPayload {
  return {
    kind: "job",
    job_id: 1,
    app_key: "test_app",
    instance_index: 0,
    status: "success",
    duration_ms: 75,
    error_type: null,
    thread_leaked: false,
    ...overrides,
  } satisfies WsExecutionCompletedPayload;
}

export function createTelemetryStatus(overrides: Partial<TelemetryStatusResponse> = {}): TelemetryStatusResponse {
  return {
    degraded: false,
    dropped_overflow: 0,
    dropped_exhausted: 0,
    dropped_shutdown: 0,
    error_handler_failures: 0,
    ...overrides,
  } satisfies TelemetryStatusResponse;
}

export function createExecution(kind: "handler" | "job", overrides: Partial<Execution> = {}): Execution {
  const kindFields =
    kind === "handler"
      ? { kind: "handler" as const, listener_id: 1, job_id: null, duration_ms: 50 }
      : { kind: "job" as const, listener_id: null, job_id: 1, duration_ms: 75 };
  return {
    ...kindFields,
    execution_start_ts: 1700000000,
    status: "success",
    source_tier: "app",
    error_type: null,
    error_message: null,
    execution_id: null,
    trigger_context_id: null,
    trigger_origin: null,
    retry_count: 0,
    attempt_number: 1,
    args_json: "[]",
    kwargs_json: "{}",
    thread_leaked: false,
    ...overrides,
  } satisfies Execution;
}

/**
 * Minimal schema used in tests — mirrors the shape produced by the backend's
 * build_config_view for a small HassetteConfig subset.  Only the fields that
 * individual tests assert on need to appear here.
 */
const MINIMAL_CONFIG_SCHEMA = {
  type: "object",
  title: "HassetteConfig",
  properties: {
    dev_mode: { type: "boolean", title: "Dev Mode" },
    base_url: { type: "string", title: "Base Url", ui: { label: "Base URL" } },
    asyncio_debug_mode: { type: "boolean", title: "Asyncio Debug Mode" },
    allow_reload_in_prod: { type: "boolean", title: "Allow Reload In Prod" },
    data_dir: { type: "string", title: "Data Dir", format: "path" },
    config_dir: { type: "string", title: "Config Dir", format: "path" },
    token: {
      anyOf: [{ type: "string", writeOnly: true, format: "password" }, { type: "null" }],
      title: "Token",
    },
    web_api: {
      type: "object",
      title: "Web Api",
      ui: { group_label: "Web API" },
      properties: {
        run: { type: "boolean", title: "Run" },
        run_ui: { type: "boolean", title: "Run Ui", ui: { label: "Run UI" } },
        ui_hot_reload: { type: "boolean", title: "Ui Hot Reload", ui: { label: "UI Hot Reload" } },
        host: { type: "string", title: "Host" },
        port: { type: "integer", title: "Port" },
        cors_origins: {
          type: "array",
          title: "Cors Origins",
          ui: { label: "CORS Origins" },
          items: { type: "string" },
        },
        log_buffer_size: { type: "integer", title: "Log Buffer Size" },
        job_history_size: { type: "integer", title: "Job History Size" },
      },
    },
    logging: {
      type: "object",
      title: "Logging",
      properties: {
        log_level: { type: "string", title: "Log Level" },
        web_api: { type: "string", title: "Web Api" },
      },
    },
    lifecycle: {
      type: "object",
      title: "Lifecycle",
      properties: {
        startup_timeout_seconds: { type: "integer", title: "Startup Timeout Seconds" },
        app_startup_timeout_seconds: { type: "integer", title: "App Startup Timeout Seconds" },
        app_shutdown_timeout_seconds: { type: "integer", title: "App Shutdown Timeout Seconds" },
      },
    },
    apps: {
      type: "object",
      title: "Apps",
      properties: {
        autodetect: { type: "boolean", title: "Autodetect" },
        directory: { type: "string", title: "Directory", format: "path" },
      },
    },
    scheduler: {
      type: "object",
      title: "Scheduler",
      properties: {
        min_delay_seconds: { type: "number", title: "Min Delay Seconds" },
        max_delay_seconds: { type: "number", title: "Max Delay Seconds" },
        default_delay_seconds: { type: "number", title: "Default Delay Seconds" },
      },
    },
    file_watcher: {
      type: "object",
      title: "File Watcher",
      properties: {
        watch_files: { type: "boolean", title: "Watch Files" },
        debounce_milliseconds: { type: "integer", title: "Debounce Milliseconds" },
      },
    },
  },
};

/** Default config values to use in test fixtures. */
const DEFAULT_CONFIG_VALUES: Record<string, unknown> = {
  dev_mode: false,
  base_url: "",
  asyncio_debug_mode: false,
  allow_reload_in_prod: false,
  data_dir: "/home/user/.hassette/data",
  config_dir: "/home/user/.hassette",
  token: null,
  web_api: {
    run: true,
    run_ui: true,
    ui_hot_reload: false,
    host: "0.0.0.0",
    port: 8126,
    cors_origins: [],
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
};

/**
 * Build a ConfigSchemaResponse test fixture.
 *
 * Pass value-level overrides as a partial Record to merge into config_values.
 * Pass schemaOverrides to replace the entire config_schema.
 */
export function createSystemConfig(
  valueOverrides: Record<string, unknown> = {},
  schemaOverrides?: Record<string, unknown>,
): ConfigSchemaResponse {
  const config_values = { ...DEFAULT_CONFIG_VALUES, ...valueOverrides };
  const config_schema = schemaOverrides ?? MINIMAL_CONFIG_SCHEMA;
  return { config_schema, config_values } satisfies ConfigSchemaResponse;
}
