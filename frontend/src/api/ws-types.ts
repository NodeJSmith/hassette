/* @generated from ws-schema.json — do not edit by hand.
 * Regenerate: node scripts/generate-ws-types.cjs
 * Or: uv run python scripts/export_schemas.py --types
 */

export type WsServerMessage =
  | AppStatusChangedWsMessage
  | LogWsMessage
  | ConnectedWsMessage
  | ConnectivityWsMessage
  | StateChangedWsMessage
  | ServiceStatusWsMessage
  | InvocationCompletedWsMessage
  | ExecutionCompletedWsMessage;
/**
 * Status values for handler invocations and job executions.
 *
 * Covers all values allowed by the CHECK constraints in migrations 001 and 005.
 * Pydantic v2 coerces plain strings to enum members on construction and
 * serialises back to plain strings in JSON responses.
 */
export type InvocationStatus = "success" | "error" | "cancelled" | "timed_out";

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
  status: string;
  previous_status?: string | null;
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
export interface StateChangedWsMessage {
  type: "state_changed";
  data: StateChangedData;
  timestamp: number;
}
/**
 * Payload for a Home Assistant ``state_changed`` event broadcast over WebSocket.
 */
export interface StateChangedData {
  entity_id: string;
  new_state?: {
    [k: string]: unknown;
  } | null;
  old_state?: {
    [k: string]: unknown;
  } | null;
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
  status: string;
  previous_status?: string | null;
  exception?: string | null;
  exception_type?: string | null;
  exception_traceback?: string | null;
  retry_at?: number | null;
  ready?: boolean;
  ready_phase?: string | null;
}
export interface InvocationCompletedWsMessage {
  type: "invocation_completed";
  data: InvocationCompletedData[];
  timestamp: number;
}
/**
 * Payload for invocation_completed WebSocket messages.
 */
export interface InvocationCompletedData {
  listener_id: number;
  app_key: string;
  instance_index: number;
  status: InvocationStatus;
  duration_ms: number;
  error_type?: string | null;
}
export interface ExecutionCompletedWsMessage {
  type: "execution_completed";
  data: ExecutionCompletedData[];
  timestamp: number;
}
/**
 * Payload for execution_completed WebSocket messages.
 */
export interface ExecutionCompletedData {
  job_id: number;
  app_key: string;
  instance_index: number;
  status: InvocationStatus;
  duration_ms: number;
  error_type?: string | null;
}

// Backward-compatible aliases for consumers that use the Ws*Payload naming
export type WsLogPayload = LogEntryResponse;
export type WsInvocationCompletedPayload = InvocationCompletedData;
export type WsExecutionCompletedPayload = ExecutionCompletedData;
export type WsAppStatusChangedPayload = AppStatusChangedData;
export type WsConnectedPayload = ConnectedPayload;
export type WsConnectivityPayload = ConnectivityData;
export type WsStateChangedPayload = StateChangedData;
export type WsServiceStatusPayload = ServiceStatusData;

// Note: InvocationStatus is also defined in generated-types.ts (from OpenAPI).
// Both are generated from the same Python enum via export_schemas.py --types.
// CI enforces freshness of both files atomically.
