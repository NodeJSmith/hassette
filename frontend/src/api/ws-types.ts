/* @generated from ws-schema.json — do not edit by hand.
 * Regenerate: node scripts/generate-ws-types.cjs
 * Or: uv run python scripts/export_schemas.py --types
 */

export type WsServerMessage =
  | AppStatusChangedWsMessage
  | LogWsMessage
  | ConnectedWsMessage
  | ConnectivityWsMessage
  | ServiceStatusWsMessage
  | ExecutionCompletedWsMessage
  | AppManifestsChangedWsMessage;
/**
 * Enumeration for resource status.
 */
export type ResourceStatus =
  | "not_started"
  | "starting"
  | "running"
  | "stopping"
  | "stopped"
  | "failed"
  | "crashed"
  | "exhausted_dead"
  | "exhausted_cooling";
/**
 * Status values for handler invocations and job executions.
 *
 * Covers all values allowed by the ``executions.status`` CHECK constraint: migration 001
 * introduced the original four values (``success``, ``error``, ``cancelled``, ``timed_out``);
 * migration 009 added ``skipped``.
 * Pydantic v2 coerces plain strings to enum members on construction and
 * serialises back to plain strings in JSON responses.
 */
export type ExecutionStatus = "success" | "error" | "cancelled" | "timed_out" | "skipped";

export interface AppStatusChangedWsMessage {
  type: "app_status_changed";
  data: AppStatusChangedData;
  timestamp: number;
}
/**
 * Payload for an app lifecycle state-change event broadcast over WebSocket.
 *
 * Mirrors ``events.hassette.AppStateChangePayload`` exactly.
 */
export interface AppStatusChangedData {
  app_key: string;
  index: number;
  status: ResourceStatus;
  previous_status?: ResourceStatus | null;
  instance_name?: string | null;
  class_name?: string | null;
  exception?: string | null;
  exception_type?: string | null;
  exception_traceback?: string | null;
}
export interface LogWsMessage {
  type: "log";
  data: LogEntryResponse;
  timestamp: number;
}
export interface LogEntryResponse {
  seq: number;
  timestamp: number;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  logger_name: string;
  func_name?: string | null;
  lineno?: number | null;
  message: string;
  exc_info?: string | null;
  app_key?: string | null;
  execution_id?: string | null;
  instance_name?: string | null;
  instance_index?: number | null;
  source_tier?: ("app" | "framework") | null;
  execution_kind?: ("handler" | "job") | null;
  listener_id?: number | null;
  job_id?: number | null;
}
export interface ConnectedWsMessage {
  type: "connected";
  data: ConnectedPayload;
  timestamp: number;
}
export interface ConnectedPayload {
  uptime_seconds: number;
  entity_count: number;
  app_count: number;
  version?: string;
}
export interface ConnectivityWsMessage {
  type: "connectivity";
  data: ConnectivityData;
  timestamp: number;
}
/**
 * Payload for a Home Assistant WebSocket connectivity event.
 */
export interface ConnectivityData {
  connected: boolean;
}
export interface ServiceStatusWsMessage {
  type: "service_status";
  data: ServiceStatusData;
  timestamp: number;
}
/**
 * Payload for an internal service status-change event broadcast over WebSocket.
 *
 * Mirrors ``events.hassette.ServiceStatusPayload``.
 */
export interface ServiceStatusData {
  resource_name: string;
  role: string;
  status: ResourceStatus;
  previous_status?: ResourceStatus | null;
  exception?: string | null;
  exception_type?: string | null;
  exception_traceback?: string | null;
  retry_at?: number | null;
  ready?: boolean;
  ready_phase?: string | null;
}
export interface ExecutionCompletedWsMessage {
  type: "execution_completed";
  data: ExecutionCompletedData[];
  timestamp: number;
}
/**
 * Payload for execution_completed WebSocket messages.
 *
 * ``kind`` discriminates handler invocations from job executions.
 * ``listener_id`` is set when ``kind='handler'``; ``job_id`` when ``kind='job'``.
 */
export interface ExecutionCompletedData {
  kind: "handler" | "job";
  app_key: string;
  instance_index: number;
  status: ExecutionStatus;
  duration_ms: number;
  error_type?: string | null;
  listener_id?: number | null;
  job_id?: number | null;
  thread_leaked?: boolean;
}
export interface AppManifestsChangedWsMessage {
  type: "app_manifests_changed";
  data: AppManifestsChangedData;
  timestamp: number;
}
/**
 * Payload for a manifest refresh broadcast over WebSocket.
 *
 * Carries no fields — it is a refetch signal, not a diff. The event that triggers it
 * (``HASSETTE_EVENT_APP_LOAD_COMPLETED``) fires after a full bootstrap or reload pass over
 * all apps, and also after a live config edit that only changes manifest metadata (e.g.
 * ``display_name``) with no lifecycle action to take. Either way it does not identify which
 * app(s) changed, so clients should treat receipt as "manifest status may be stale, refetch"
 * rather than inspect the payload for detail.
 */
export type AppManifestsChangedData = Record<string, never>;

export type WsLogPayload = LogEntryResponse;
export type WsExecutionCompletedPayload = ExecutionCompletedData;

// ExecutionStatus is also defined in generated-types.ts (from OpenAPI).
// Both are generated from the same Python enum via export_schemas.py --types.
// CI enforces freshness of both files atomically.
