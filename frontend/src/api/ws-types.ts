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
  session_id: number | null;
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
}

export interface WsLogPayload {
  timestamp: number;
  level: string;
  logger_name: string;
  func_name: string;
  lineno: number;
  message: string;
  exc_info: string | null;
  app_key: string | null;
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

export type WsServerMessage =
  | AppStatusChangedMessage
  | LogMessage
  | ConnectedMessage
  | ConnectivityMessage
  | StateChangedMessage
  | ServiceStatusMessage;
