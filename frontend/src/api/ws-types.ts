/* @generated from ws-schema.json — do not edit by hand.
 * Regenerate: node scripts/generate-ws-types.cjs
 * Or: uv run python scripts/export_schemas.py --types
 */

export type WsServerMessage =
  | AppStatusChangedWsMessage
  | LogHintWsMessage
  | ConnectedWsMessage
  | ConnectivityWsMessage
  | ServiceStatusWsMessage
  | ExecutionCompletedWsMessage
  | AppsChangedWsMessage;
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
 * The kind of framework component a status or service entry describes.
 */
export type ResourceRole = "core" | "base" | "service" | "resource" | "app" | "unknown";
/**
 * How a handler invocation or job execution ended.
 */
export type ExecutionStatus = "success" | "error" | "cancelled" | "timed_out" | "skipped";

/**
 * Envelope for ``AppStatusChangedData``.
 */
export interface AppStatusChangedWsMessage {
  type: "app_status_changed";
  data: AppStatusChangedData;
  timestamp: number;
}
/**
 * An app instance changed lifecycle status.
 *
 * The ``exception*`` fields describe the error that caused the change, and are ``None`` when no error did.
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
/**
 * New log records exist; refetch them over HTTP.
 *
 * Carries no records. Sent only to clients that subscribed to logs.
 */
export interface LogHintWsMessage {
  type: "log_hint";
  timestamp: number;
}
/**
 * Envelope for ``ConnectedData``.
 */
export interface ConnectedWsMessage {
  type: "connected";
  data: ConnectedData;
  timestamp: number;
}
/**
 * Server state sent once, as the first message after a WebSocket connection opens.
 *
 * ``version`` is the server's hassette version; a client can compare it with its own to detect an upgrade.
 */
export interface ConnectedData {
  uptime_seconds: number;
  entity_count: number;
  app_count: number;
  version?: string;
}
/**
 * Envelope for ``ConnectivityData``.
 */
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
/**
 * Envelope for ``ServiceStatusData``.
 */
export interface ServiceStatusWsMessage {
  type: "service_status";
  data: ServiceStatusData;
  timestamp: number;
}
/**
 * A framework service changed lifecycle status.
 *
 * The ``exception*`` fields describe the error that caused the change, and are ``None`` when no error did.
 */
export interface ServiceStatusData {
  resource_name: string;
  role: ResourceRole;
  status: ResourceStatus;
  previous_status?: ResourceStatus | null;
  exception?: string | null;
  exception_type?: string | null;
  exception_traceback?: string | null;
  /**
   * Unix timestamp when the next restart will be attempted.
   *
   * Populated for ``EXHAUSTED_COOLING`` events (the service is in a long cooldown
   * and will retry at this time). ``None`` for ``EXHAUSTED_DEAD`` and all other
   * statuses. The frontend uses this to display a live countdown timer.
   */
  retry_at?: number | null;
  /**
   * Whether the service had signalled readiness at the time of this status event.
   */
  ready?: boolean;
  /**
   * Human-readable description of the current readiness phase, or None if not available.
   */
  ready_phase?: string | null;
}
/**
 * Envelope for a batch of ``ExecutionCompletedData``.
 */
export interface ExecutionCompletedWsMessage {
  type: "execution_completed";
  /**
   * App-tier executions persisted since the previous message, delivered together in one batch.
   */
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
/**
 * Envelope for ``AppsChangedData``.
 */
export interface AppsChangedWsMessage {
  type: "apps_changed";
  data: AppsChangedData;
  timestamp: number;
}
/**
 * Payload for an app-list refresh broadcast over WebSocket.
 *
 * Carries no fields and does not identify which apps changed — it is a refetch
 * signal, not a diff. Clients should treat receipt as "app status may be
 * stale, refetch" rather than inspect the payload.
 */
export type AppsChangedData = Record<string, never>;

export type WsExecutionCompletedPayload = ExecutionCompletedData;

// ExecutionStatus is also defined in generated-types.ts (from OpenAPI).
// Both are generated from the same Python enum via export_schemas.py --types.
// CI enforces freshness of both files atomically.
