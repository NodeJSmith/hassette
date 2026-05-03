/**
 * Default MSW request handlers for all Hassette API endpoints.
 *
 * Each handler returns a minimal, realistic response shape that satisfies the
 * generated TypeScript types. Tests that need different data should use
 * `server.use(http.get(...))` to override individual handlers for that test.
 */

import { http, HttpResponse } from "msw";
import type { components } from "../api/generated-types";

// ---- Type aliases (keep in sync with endpoints.ts) ----

type ManifestListResponse = components["schemas"]["AppManifestListResponse"];
type ConfigResponse = components["schemas"]["ConfigResponse"];
type AppHealthResponse = components["schemas"]["AppHealthResponse"];
type ListenerWithSummary = components["schemas"]["ListenerWithSummary"];
type JobSummary = components["schemas"]["JobSummary"];
type HandlerInvocation = components["schemas"]["HandlerInvocation"];
type JobExecution = components["schemas"]["JobExecution"];
type DashboardKpisResponse = components["schemas"]["DashboardKpisResponse"];
type DashboardAppGridResponse = components["schemas"]["DashboardAppGridResponse"];
type DashboardErrorsResponse = components["schemas"]["DashboardErrorsResponse"];
type FrameworkSummaryResponse = components["schemas"]["FrameworkSummaryResponse"];
type TelemetryStatusResponse = components["schemas"]["TelemetryStatusResponse"];
type LogEntryResponse = components["schemas"]["LogEntryResponse"];
type ActionResponse = components["schemas"]["ActionResponse"];

// ---- Default handlers ----

export const handlers = [
  // GET /api/apps/manifests
  http.get("/api/apps/manifests", () => {
    return HttpResponse.json<ManifestListResponse>({
      total: 0,
      running: 0,
      failed: 0,
      stopped: 0,
      disabled: 0,
      blocked: 0,
      manifests: [],
      only_app: null,
    });
  }),

  // POST /api/apps/:app_key/start
  http.post("/api/apps/:app_key/start", ({ params }) => {
    return HttpResponse.json<ActionResponse>({
      status: "ok",
      app_key: String(params["app_key"]),
      action: "start",
    });
  }),

  // POST /api/apps/:app_key/stop
  http.post("/api/apps/:app_key/stop", ({ params }) => {
    return HttpResponse.json<ActionResponse>({
      status: "ok",
      app_key: String(params["app_key"]),
      action: "stop",
    });
  }),

  // POST /api/apps/:app_key/reload
  http.post("/api/apps/:app_key/reload", ({ params }) => {
    return HttpResponse.json<ActionResponse>({
      status: "ok",
      app_key: String(params["app_key"]),
      action: "reload",
    });
  }),

  // GET /api/telemetry/app/:app_key/health
  http.get("/api/telemetry/app/:app_key/health", () => {
    return HttpResponse.json<AppHealthResponse>({
      error_rate: 0,
      error_rate_class: "good",
      handler_avg_duration: 0,
      job_avg_duration: 0,
      last_activity_ts: null,
      health_status: "good",
    });
  }),

  // GET /api/telemetry/app/:app_key/listeners
  http.get("/api/telemetry/app/:app_key/listeners", () => {
    return HttpResponse.json<ListenerWithSummary[]>([]);
  }),

  // GET /api/telemetry/app/:app_key/jobs
  http.get("/api/telemetry/app/:app_key/jobs", () => {
    return HttpResponse.json<JobSummary[]>([]);
  }),

  // GET /api/telemetry/handler/:listener_id/invocations
  http.get("/api/telemetry/handler/:listener_id/invocations", () => {
    return HttpResponse.json<HandlerInvocation[]>([]);
  }),

  // GET /api/telemetry/job/:job_id/executions
  http.get("/api/telemetry/job/:job_id/executions", () => {
    return HttpResponse.json<JobExecution[]>([]);
  }),

  // GET /api/telemetry/dashboard/kpis
  http.get("/api/telemetry/dashboard/kpis", () => {
    return HttpResponse.json<DashboardKpisResponse>({
      total_handlers: 0,
      total_jobs: 0,
      total_invocations: 0,
      total_executions: 0,
      total_errors: 0,
      total_timed_out: 0,
      total_job_errors: 0,
      total_job_timed_out: 0,
      avg_handler_duration_ms: 0,
      avg_job_duration_ms: 0,
      error_rate: 0,
      error_rate_class: "good",
      uptime_seconds: null,
    });
  }),

  // GET /api/telemetry/dashboard/app-grid
  http.get("/api/telemetry/dashboard/app-grid", () => {
    return HttpResponse.json<DashboardAppGridResponse>({ apps: [] });
  }),

  // GET /api/telemetry/dashboard/errors
  http.get("/api/telemetry/dashboard/errors", () => {
    return HttpResponse.json<DashboardErrorsResponse>({ errors: [] });
  }),

  // GET /api/telemetry/dashboard/framework-summary
  http.get("/api/telemetry/dashboard/framework-summary", () => {
    return HttpResponse.json<FrameworkSummaryResponse>({
      total_errors: 0,
      total_job_errors: 0,
    });
  }),

  // GET /api/telemetry/status
  http.get("/api/telemetry/status", () => {
    return HttpResponse.json<TelemetryStatusResponse>({
      degraded: false,
      dropped_overflow: 0,
      dropped_exhausted: 0,
      dropped_no_session: 0,
      dropped_shutdown: 0,
      error_handler_failures: 0,
    });
  }),

  // GET /api/logs/recent
  http.get("/api/logs/recent", () => {
    return HttpResponse.json<LogEntryResponse[]>([]);
  }),

  // GET /api/apps/:app_key/source
  http.get("/api/apps/:app_key/source", ({ params }) => {
    return HttpResponse.json({
      app_key: String(params["app_key"]),
      filename: "test_app.py",
      content: "class TestApp:\n    pass\n",
      line_count: 2,
    });
  }),

  // GET /api/apps/:app_key/config
  http.get("/api/apps/:app_key/config", ({ params }) => {
    return HttpResponse.json({
      app_key: String(params["app_key"]),
      filename: "test_app.py",
      class_name: "TestApp",
      enabled: true,
      app_config: {},
    });
  }),

  // GET /api/config
  http.get("/api/config", () => {
    return HttpResponse.json<ConfigResponse>({
      dev_mode: false,
      log_level: "INFO",
      base_url: "",
      run_web_api: true,
      run_web_ui: true,
      web_api_host: "0.0.0.0",
      web_api_port: 8126,
      web_api_cors_origins: [],
      web_api_event_buffer_size: 500,
      web_api_log_buffer_size: 2000,
      web_api_job_history_size: 1000,
      web_api_log_level: "INFO",
      autodetect_apps: true,
      startup_timeout_seconds: 10,
      app_startup_timeout_seconds: 20,
      app_shutdown_timeout_seconds: 10,
      watch_files: true,
      file_watcher_debounce_milliseconds: 3000,
      scheduler_min_delay_seconds: 1,
      scheduler_max_delay_seconds: 30,
      scheduler_default_delay_seconds: 15,
      asyncio_debug_mode: false,
      allow_reload_in_prod: false,
      web_ui_hot_reload: false,
      app_dir: "/home/user/apps",
      data_dir: "/home/user/.hassette/data",
      config_dir: "/home/user/.hassette",
    });
  }),
];
