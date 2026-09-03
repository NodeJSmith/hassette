import type { components } from "../api/generated-types";

export type StatusVariant = "success" | "danger" | "warning" | "neutral";

type ManifestStatus = components["schemas"]["ManifestStatus"];
type ResourceStatus = components["schemas"]["ResourceStatus"];
type ExecutionStatus = components["schemas"]["ExecutionStatus"];

/** Legacy frontend-only status value, not present in either backend enum — kept for
 * `INACTIVE_STATUSES` and the maps below that accept it. See `INACTIVE_STATUSES`. */
type ShuttingDownStatus = "shutting_down";

/** Defensive placeholder used while a live status hasn't loaded yet (e.g. `AppDetailPage`'s
 * `liveStatus` selector, `ActionButtons`' `status` prop) — not a backend enum value. */
type UnknownStatus = "unknown";

/**
 * True for statuses that represent an app-level failure and should surface in the
 * `FailedAppsAlert` failure banner. Typed as a `Record` over the full
 * `ManifestStatus | ResourceStatus` union (rather than an ad hoc `===`/`||` chain) so a future
 * status variant that should trigger the alert is a compile-time error if omitted here.
 */
export const IS_FAILURE_STATUS = {
  disabled: false,
  blocked: false,
  degraded: true,
  running: false,
  failed: true,
  stopped: false,
  not_started: false,
  starting: false,
  stopping: false,
  crashed: true,
  // These two are only reachable via restart_spec exhaustion supervision, which today applies
  // to Service subclasses only — App extends Resource directly and never carries restart_spec,
  // so these values are correct by construction, not by design. If restart_spec supervision is
  // ever extended to App, revisit whether these should be `true` for app-level failure reporting.
  exhausted_dead: false,
  exhausted_cooling: false,
} satisfies Record<ManifestStatus | ResourceStatus, boolean>;

export function isFailureStatus(status: ManifestStatus | ResourceStatus): boolean {
  return IS_FAILURE_STATUS[status] ?? false;
}

/** Status key type for the per-app Start/Stop action-enablement maps below, and for
 * `ActionButtons`' own `status` prop. */
export type ActionButtonStatusKey = ManifestStatus | ResourceStatus | UnknownStatus;

/**
 * True for statuses from which "Start" is a valid action. Record/satisfies instead of an ad hoc
 * `===` chain so a future status variant that should enable Start is a compile-time error if
 * omitted here, matching `IS_FAILURE_STATUS`'s pattern above.
 */
export const CAN_START: Record<ActionButtonStatusKey, boolean> = {
  stopped: true,
  failed: true,
  disabled: true,
  blocked: false,
  degraded: false,
  running: false,
  not_started: false,
  starting: false,
  stopping: false,
  crashed: false,
  exhausted_dead: false,
  exhausted_cooling: false,
  unknown: false,
} satisfies Record<ActionButtonStatusKey, boolean>;

/**
 * True for statuses from which "Stop" is a valid action. Degraded means "some instances still
 * running" — stop/reload remain meaningful recovery actions; start does not (nothing about a
 * degraded app implies a fully-stopped instance).
 */
export const CAN_STOP: Record<ActionButtonStatusKey, boolean> = {
  running: true,
  degraded: true,
  disabled: false,
  blocked: false,
  failed: false,
  stopped: false,
  not_started: false,
  starting: false,
  stopping: false,
  crashed: false,
  exhausted_dead: false,
  exhausted_cooling: false,
  unknown: false,
} satisfies Record<ActionButtonStatusKey, boolean>;

/** Statuses that represent intentionally non-active apps (not failures).
 * Typed against `ManifestStatus | ResourceStatus | ShuttingDownStatus | UnknownStatus` (wider
 * than just the 3 contained values) so callers passing `appLiveStatus()`'s full return union —
 * which can legitimately hold any `ResourceStatus` value, or the app-detail page's "unknown"
 * placeholder — can query membership without a cast. */
export const INACTIVE_STATUSES: ReadonlySet<ManifestStatus | ResourceStatus | ShuttingDownStatus | UnknownStatus> =
  new Set<ManifestStatus | ResourceStatus | ShuttingDownStatus | UnknownStatus>([
    "stopped",
    "disabled",
    "shutting_down",
  ]);

/**
 * True for statuses that still have live instances worth reloading — a degraded app has some
 * failed instances but isn't fully down, so reload remains a meaningful recovery action.
 *
 * Shared by the per-app ActionButtons reload control and the "Reload all apps" bulk command so
 * the two selection sets can't silently diverge (they did once, for "degraded").
 */
export function isReloadableStatus(status: ManifestStatus | ResourceStatus): boolean {
  return status === "running" || status === "degraded";
}

/**
 * `StatusMapKey` covers both `ResourceStatus` and `ManifestStatus` values plus service-health
 * values (`"success"`, `"failure"`).
 */
type StatusMapKey = ResourceStatus | ManifestStatus | "success" | "failure" | UnknownStatus | ShuttingDownStatus;

const APP_STATUS_MAP: Record<StatusMapKey, StatusVariant> = {
  running: "success",
  failed: "danger",
  crashed: "danger",
  stopped: "warning",
  disabled: "neutral",
  blocked: "warning", // Intentional: blocked = needs attention (matches small badge behavior)
  degraded: "warning",
  not_started: "neutral",
  starting: "neutral",
  stopping: "neutral",
  shutting_down: "neutral",
  // Service exhaustion statuses
  exhausted_dead: "danger", // Permanent failure — budget exhausted, no further restarts
  exhausted_cooling: "warning", // Long cooldown in progress — will retry after cooldown period
  success: "success",
  failure: "danger",
  unknown: "neutral",
} satisfies Record<StatusMapKey, StatusVariant>;

export function statusToVariant(status: StatusMapKey): StatusVariant {
  return APP_STATUS_MAP[status] ?? "neutral";
}

const EXECUTION_STATUS_KIND: Record<ExecutionStatus, StatusKind> = {
  success: "ok",
  timed_out: "warn",
  cancelled: "cancel",
  error: "err",
  skipped: "mute",
} satisfies Record<ExecutionStatus, StatusKind>;

export function executionStatusKind(status: ExecutionStatus): StatusKind {
  return EXECUTION_STATUS_KIND[status] ?? "err";
}

/**
 * StatusKind: semantic shape/color for StatusShape SVG indicators.
 * Use StatusKind (via statusToKind) for shape indicators (dots, triangles, squares).
 * Use StatusVariant (via statusToVariant) for text badges and CSS class suffixes.
 *
 * These two systems intentionally diverge for some statuses:
 * - "stopped": warning badge (needs attention) vs mute shape (inactive)
 * - "starting": neutral badge vs ok shape (healthy progress)
 * - "stopping"/"shutting_down": neutral badge vs warn shape (transitional)
 *
 * APP_STATUS_MAP covers both ResourceStatus and ManifestStatus values plus
 * service-health values ("success", "failure", "unknown"). STATUS_KIND_MAP
 * covers both ResourceStatus and ManifestStatus plus the legacy "shutting_down"
 * value and the "unknown" placeholder — use executionStatusKind() for
 * execution results. Log levels are not mapped here at all: they carry their own
 * styling via LOG_LEVEL_STYLES in components/shared/log-table/constants.ts.
 * New ResourceStatus or ManifestStatus variants must be added to both maps.
 */
export type StatusKind = "ok" | "warn" | "err" | "cancel" | "mute";

type StatusKindMapKey = ResourceStatus | ManifestStatus | ShuttingDownStatus | UnknownStatus;

const STATUS_KIND_MAP: Record<StatusKindMapKey, StatusKind> = {
  running: "ok",
  starting: "ok",
  failed: "err",
  crashed: "err",
  exhausted_dead: "err",
  blocked: "warn",
  degraded: "warn",
  stopping: "warn",
  shutting_down: "warn",
  exhausted_cooling: "warn",
  stopped: "mute",
  disabled: "mute",
  not_started: "mute",
  unknown: "mute",
} satisfies Record<StatusKindMapKey, StatusKind>;

export function statusToKind(status: StatusKindMapKey): StatusKind {
  return STATUS_KIND_MAP[status] ?? "mute";
}

/** Derive a display chip label from handler/job metadata.
 * Listeners use backend-provided `listener_kind`; jobs use trigger_type.
 */
export function handlerKindLabel(
  kind: "listener" | "job",
  listenerKind: string | null | undefined,
  triggerType: string | null | undefined = null,
): string {
  if (kind === "job") {
    return triggerType?.toLowerCase() || "schedule";
  }
  return listenerKind || "event";
}
