/**
 * Default MSW request handlers for all Hassette API endpoints.
 *
 * Each handler returns a minimal, realistic response shape that satisfies the
 * generated TypeScript types. Tests that need different data should use
 * `server.use(http.get(...))` to override individual handlers for that test.
 */

import { http, HttpResponse } from "msw";

import type { components } from "../api/generated-types";
import { createSystemConfig } from "./factories";

// ---- Type aliases (keep in sync with endpoints.ts) ----

type SystemStatusResponse = components["schemas"]["SystemStatusResponse"];
type ManifestListResponse = components["schemas"]["AppManifestListResponse"];
type ConfigSchemaResponse = components["schemas"]["ConfigSchemaResponse"];
type AppHealthResponse = components["schemas"]["AppHealthResponse"];
type ListenerWithSummary = components["schemas"]["ListenerWithSummary"];
type JobSummary = components["schemas"]["JobSummary"];
type Execution = components["schemas"]["Execution"];
type DashboardAppGridResponse = components["schemas"]["DashboardAppGridResponse"];
type TelemetryStatusResponse = components["schemas"]["TelemetryStatusResponse"];
type LogEntryResponse = components["schemas"]["LogEntryResponse"];
type LogsByExecutionResponse = components["schemas"]["LogsByExecutionResponse"];
type ActionResponse = components["schemas"]["ActionResponse"];
type ActivityFeedEntry = components["schemas"]["ActivityFeedEntry"];
type JobTriggerResponse = components["schemas"]["JobTriggerResponse"];

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
      status: "accepted",
      app_key: String(params["app_key"]),
      action: "start",
    });
  }),

  // POST /api/apps/:app_key/stop
  http.post("/api/apps/:app_key/stop", ({ params }) => {
    return HttpResponse.json<ActionResponse>({
      status: "accepted",
      app_key: String(params["app_key"]),
      action: "stop",
    });
  }),

  // POST /api/apps/:app_key/reload
  http.post("/api/apps/:app_key/reload", ({ params }) => {
    return HttpResponse.json<ActionResponse>({
      status: "accepted",
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

  // GET /api/telemetry/app/:app_key/activity
  http.get("/api/telemetry/app/:app_key/activity", () => {
    return HttpResponse.json<ActivityFeedEntry[]>([]);
  }),

  // GET /api/telemetry/listener/:listener_id/executions
  http.get("/api/telemetry/listener/:listener_id/executions", () => {
    return HttpResponse.json<Execution[]>([]);
  }),

  // GET /api/telemetry/job/:job_id/executions
  http.get("/api/telemetry/job/:job_id/executions", () => {
    return HttpResponse.json<Execution[]>([]);
  }),

  // GET /api/scheduler/jobs
  http.get("/api/scheduler/jobs", () => {
    return HttpResponse.json<JobSummary[]>([]);
  }),

  // POST /api/scheduler/jobs/:id/trigger
  http.post("/api/scheduler/jobs/:id/trigger", ({ params }) => {
    return HttpResponse.json<JobTriggerResponse>(
      {
        status: "accepted",
        job_id: Number(params["id"]),
        job_name: "test-job",
      },
      { status: 202 },
    );
  }),

  // GET /api/telemetry/dashboard/app-grid
  http.get("/api/telemetry/dashboard/app-grid", () => {
    return HttpResponse.json<DashboardAppGridResponse>({ apps: [] });
  }),

  // GET /api/telemetry/status
  http.get("/api/telemetry/status", () => {
    return HttpResponse.json<TelemetryStatusResponse>({
      degraded: false,
      dropped_overflow: 0,
      dropped_exhausted: 0,
      dropped_shutdown: 0,
      error_handler_failures: 0,
    });
  }),

  // GET /api/logs/recent
  http.get("/api/logs/recent", () => {
    return HttpResponse.json<LogEntryResponse[]>([]);
  }),

  // GET /api/executions/:execution_id
  http.get("/api/executions/:execution_id", () => {
    return HttpResponse.json<LogsByExecutionResponse>({
      records: [],
      truncated: false,
      retention_expired: false,
    });
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

  // GET /api/bus/listeners
  http.get("/api/bus/listeners", () => {
    return HttpResponse.json<ListenerWithSummary[]>([]);
  }),

  // GET /api/config
  http.get("/api/config", () => {
    return HttpResponse.json<ConfigSchemaResponse>(createSystemConfig());
  }),

  // GET /api/health
  http.get("/api/health", () => {
    return HttpResponse.json<SystemStatusResponse>({
      status: "ok",
      websocket_connected: true,
      uptime_seconds: 120,
      entity_count: 10,
      app_count: 2,
      services_running: ["bus", "scheduler"],
      services: [],
      version: "1.0.0",
      boot_issues: [],
      log_records_dropped: 0,
    });
  }),
];
