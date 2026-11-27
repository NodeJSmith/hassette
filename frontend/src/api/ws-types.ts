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
  | AppsChangedWsMessage
  | EntityStateChangedWsMessage;
/**
 * Enumeration for resource status.
 */
export type ResourceStatus = "not_started" | "starting" | "running" | "stopping" | "stopped" | "failed" | "crashed";
/**
 * The app's rollup status after this change, equal to the ``AppSummary.status`` read at ``status_revision``.
 */
export type AppStatus =
  "disabled" | "blocked" | "degraded" | "failed" | "starting" | "stopping" | "running" | "stopped";
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
 * Apply it only when ``status_revision`` is strictly greater than the ``AppSummary.status_revision`` of the row it
 * updates; on a tie the summary wins. The ``exception*`` fields describe the error that caused the change, and
 * are ``None`` when no error did.
 */
export interface AppStatusChangedData {
  app_key: string;
  instance_name: string;
  status: ResourceStatus;
  /**
   * The app-status revision this change was written at; comparable with ``AppSummary.status_revision``.
   */
  status_revision: number;
  /**
   * Identifies the hassette boot that sent the message; a new value means the server restarted. Ordering doesn't
   * need it, since ``status_revision`` keeps increasing across restarts; it lets a client reset state it keeps per
   * server process.
   */
  boot_id: string;
  app_status: AppStatus;
  previous_status?: ResourceStatus | null;
  class_name?: string | null;
  exception?: string | null;
  exception_type?: string | null;
  exception_traceback?: string | null;
  /**
   * Set when this change flagged the instance needs-restart (only a ``failed`` change can), so a client can show
   * it with the status.
   */
  needs_restart?: NeedsRestart | null;
}
/**
 * Why an app instance needs a hassette restart: a teardown left work that may still be running.
 *
 * Python can't stop a coroutine that ignores cancellation, so the only recovery is restarting hassette. Until
 * then the instance reports ``failed``. Nested in ``AppInstance`` and in the ``app_status_changed`` WS event.
 */
export interface NeedsRestart {
  /**
   * What the teardown left behind, such as the tasks still pending or why its evidence is incomplete.
   */
  reason: string;
  /**
   * Names of the tasks still running when the teardown ended, including an initializer that hadn't stopped
   * (``resource:initialize:<unique name>``). Can be empty when the evidence is incomplete (the instance was
   * force-terminated, or its shutdown raised); ``reason`` says which.
   */
  pending_tasks?: string[];
  /**
   * When the instance was flagged, in epoch seconds. The first flag stands until restart.
   */
  flagged_at: number;
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
  /**
   * Number of app instances currently tracked (starting, running, or failed), not the number of configured apps.
   *
   * Same meaning as ``SystemStatusResponse.app_count``.
   */
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
  status: ResourceStatus;
  previous_status?: ResourceStatus | null;
  exception?: string | null;
  exception_type?: string | null;
  exception_traceback?: string | null;
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
/**
 * Envelope for ``EntityStateChangedData``.
 */
export interface EntityStateChangedWsMessage {
  type: "entity_state_changed";
  data: EntityStateChangedData;
  timestamp: number;
}
/**
 * One app-declared entity's committed state changed.
 *
 * ``boot_id`` and ``entity_revision`` are the same counters ``GET /api/apps`` reports. Apply this message only
 * when its ``entity_revision`` is newer than the last one applied for the same ``boot_id``; revisions skip values,
 * and a lost message is repaired only by the next listing fetch. Declaration commits send no message: entities
 * appear and disappear only through the listing.
 */
export interface EntityStateChangedData {
  /**
   * Identifies the hassette boot that sent the message; a new value means the server restarted.
   */
  boot_id: string;
  /**
   * The hassette-wide entity revision this change was committed at.
   */
  entity_revision: number;
  app_key: string;
  instance_name: string;
  entity: DeclaredEntity;
}
/**
 * The entity's full description and new state, as the listing reports it.
 */
export interface DeclaredEntity {
  /**
   * The entity's key: lowercase letters, digits and ``_``, unique within its instance.
   */
  key: string;
  /**
   * ``button``, ``switch`` or ``sensor``.
   */
  platform: "button" | "switch" | "sensor";
  /**
   * The entity's display name.
   */
  name: string;
  /**
   * The entity id the app suggests, applied only when the entity is first created in Home Assistant.
   */
  default_entity_id?: string | null;
  /**
   * ``config`` or ``diagnostic``: where Home Assistant files the entity on its device page. ``None`` for a
   * primary entity.
   */
  entity_category?: string | null;
  /**
   * The entity's icon, such as ``mdi:cat``. ``None`` for Home Assistant's default icon. An icon set by hand in
   * Home Assistant's entity registry takes precedence.
   */
  icon?: string | null;
  /**
   * A sensor's unit of measurement.
   */
  unit?: string | null;
  /**
   * A sensor's Home Assistant device class.
   */
  device_class?: string | null;
  /**
   * A sensor's Home Assistant state class.
   */
  state_class?: string | null;
  /**
   * An enum sensor's allowed values.
   */
  options?: string[] | null;
  /**
   * A switch's on/off state or a sensor's value; ``None`` for a button and for a sensor that is unknown. A
   * timestamp sensor's value is an ISO 8601 string with offset, a date sensor's an ISO 8601 date.
   */
  value?: number | string | boolean | null;
  /**
   * The state attributes the app last set with the value.
   */
  attributes?: {
    [k: string]: unknown;
  };
}

// ExecutionStatus is also defined in generated-types.ts (from OpenAPI).
// Both are generated from the same Python enum via export_schemas.py --types.
// CI enforces freshness of both files atomically.
