/**
 * Hand-authored TypeScript types for WebSocket messages.
 *
 * These mirror the Pydantic models in hassette.web.models (WsServerMessage
 * discriminated union). A CI conformance test validates these match the
 * exported ws-schema.json.
 *
 * All messages use a consistent { type, data, timestamp } envelope.
 */

export interface WsAppStatusChangedPayload {
  app_key: string;
  index: number;
  status: string;
  previous_status: string | null;
  instance_name: string | null;
  class_name: string | null;
  exception: string | null;
  exception_type: string | null;
  exception_traceback: string | null;
}

export interface WsConnectedPayload {
  uptime_seconds: number;
  entity_count: number;
  app_count: number;
}

export interface WsConnectivityPayload {
  connected: boolean;
}

export interface WsStateChangedPayload {
  entity_id: string;
  new_state: Record<string, unknown> | null;
  old_state: Record<string, unknown> | null;
}

export interface WsServiceStatusPayload {
  resource_name: string;
  role: string;
  status: string;
  previous_status: string | null;
  exception: string | null;
  exception_type: string | null;
  exception_traceback: string | null;
  /** Unix timestamp when next restart will be attempted. Populated for
   * EXHAUSTED_COOLING, null for EXHAUSTED_DEAD and all other statuses. */
  retry_at: number | null;
  /** Whether the service has called mark_ready(). False during startup phases. */
  ready: boolean;
  /** Human-readable description of the current readiness or startup phase, or null if not available. */
  ready_phase: string | null;
}

export interface WsLogPayload {
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

export interface WsInvocationCompletedPayload {
  listener_id: number;
  app_key: string;
  instance_index: number;
  status: string;
  duration_ms: number;
  error_type: string | null;
}

export interface WsExecutionCompletedPayload {
  job_id: number;
  app_key: string;
  instance_index: number;
  status: string;
  duration_ms: number;
  error_type: string | null;
}

// Discriminated union of all server-to-client messages

export interface AppStatusChangedMessage {
  type: "app_status_changed";
  data: WsAppStatusChangedPayload;
  timestamp: number;
}

export interface LogMessage {
  type: "log";
  data: WsLogPayload;
  timestamp: number;
}

export interface ConnectedMessage {
  type: "connected";
  data: WsConnectedPayload;
  timestamp: number;
}

export interface ConnectivityMessage {
  type: "connectivity";
  data: WsConnectivityPayload;
  timestamp: number;
}

export interface StateChangedMessage {
  type: "state_changed";
  data: WsStateChangedPayload;
  timestamp: number;
}

export interface ServiceStatusMessage {
  type: "service_status";
  data: WsServiceStatusPayload;
  timestamp: number;
}

export interface InvocationCompletedMessage {
  type: "invocation_completed";
  /** Per-drain batch: all invocations persisted in one _drain_and_persist() cycle. */
  data: WsInvocationCompletedPayload[];
  timestamp: number;
}

export interface ExecutionCompletedMessage {
  type: "execution_completed";
  /** Per-drain batch: all executions persisted in one _drain_and_persist() cycle. */
  data: WsExecutionCompletedPayload[];
  timestamp: number;
}

export type WsServerMessage =
  | AppStatusChangedMessage
  | LogMessage
  | ConnectedMessage
  | ConnectivityMessage
  | StateChangedMessage
  | ServiceStatusMessage
  | InvocationCompletedMessage
  | ExecutionCompletedMessage;
