export type StatusVariant = "success" | "danger" | "warning" | "neutral";

export type AppStatus = "running" | "failed" | "stopped" | "disabled" | "blocked" | "starting" | "shutting_down";

/** Statuses that represent intentionally non-active apps (not failures). */
export const INACTIVE_STATUSES: ReadonlySet<string> = new Set<AppStatus>(["stopped", "disabled", "shutting_down"]);
export type ErrorRateClass = "good" | "warn" | "bad";

const APP_STATUS_MAP: ReadonlyMap<string, StatusVariant> = new Map<string, StatusVariant>([
  ["running", "success"],
  ["failed", "danger"],
  ["crashed", "danger"],
  ["stopped", "warning"],
  ["disabled", "neutral"],
  ["blocked", "warning"],  // Intentional: blocked = needs attention (matches small badge behavior)
  ["not_started", "neutral"],
  ["starting", "neutral"],
  ["stopping", "neutral"],
  ["shutting_down", "neutral"],
  // Service exhaustion statuses
  ["exhausted_dead", "danger"],     // Permanent failure — budget exhausted, no further restarts
  ["exhausted_cooling", "warning"], // Long cooldown in progress — will retry after cooldown period
  // Session statuses (shared map so StatusBadge works for both apps and sessions)
  ["success", "success"],
  ["failure", "danger"],
  ["unknown", "neutral"],
]);

const ERROR_RATE_MAP: ReadonlyMap<string, StatusVariant> = new Map<string, StatusVariant>([
  ["good", "success"],
  ["warn", "warning"],
  ["bad", "danger"],
]);

export const APP_STATUSES: ReadonlySet<string> = new Set(APP_STATUS_MAP.keys());
export const ERROR_RATE_CLASSES: ReadonlySet<string> = new Set(ERROR_RATE_MAP.keys());

/** Map a status string to a StatusVariant. Unknown values return "neutral" with a console.warn. */
export function statusToVariant(status: string): StatusVariant {
  const variant = APP_STATUS_MAP.get(status);
  if (variant !== undefined) return variant;
  console.warn(`Unknown status: "${status}"`);
  return "neutral";
}

/** Map an error rate class string to a StatusVariant. Unknown values return "neutral" with a console.warn. */
export function errorRateToVariant(cls: string): StatusVariant {
  const variant = ERROR_RATE_MAP.get(cls);
  if (variant !== undefined) return variant;
  console.warn(`Unknown error rate class: "${cls}"`);
  return "neutral";
}

/** Map a job/handler execution status to a StatusVariant.
 * "success" → "success", "timed_out" → "warning", everything else → "danger".
 */
export function executionStatusVariant(status: string): StatusVariant {
  if (status === "success") return "success";
  if (status === "timed_out") return "warning";
  return "danger";
}

const LOG_LEVEL_MAP: ReadonlyMap<string, StatusVariant> = new Map<string, StatusVariant>([
  ["DEBUG", "neutral"],
  ["INFO", "success"],
  ["WARNING", "warning"],
  ["ERROR", "danger"],
  ["CRITICAL", "danger"],
]);

/** Map a log level string to a StatusVariant. Unknown values return "neutral" silently
 * (no console.warn — unlike sibling functions, custom log levels from the wire are expected). */
export function levelToVariant(level: string): StatusVariant {
  return LOG_LEVEL_MAP.get(level) ?? "neutral";
}

export type StatusKind = "ok" | "warn" | "err" | "mute";

const LOG_LEVEL_KIND_MAP: ReadonlyMap<string, StatusKind> = new Map<string, StatusKind>([
  ["DEBUG", "mute"],
  ["INFO", "ok"],
  ["WARNING", "warn"],
  ["ERROR", "err"],
  ["CRITICAL", "err"],
]);

/** Map a log level string to a StatusKind for use with StatusShape.
 * Unknown levels return "mute". */
export function levelToKind(level: string): StatusKind {
  return LOG_LEVEL_KIND_MAP.get(level) ?? "mute";
}

const STATUS_KIND_MAP: ReadonlyMap<string, StatusKind> = new Map<string, StatusKind>([
  ["running", "ok"],
  ["starting", "ok"],
  ["failed", "err"],
  ["crashed", "err"],
  ["exhausted_dead", "err"],
  ["blocked", "warn"],
  ["stopping", "warn"],
  ["shutting_down", "warn"],
  ["exhausted_cooling", "warn"],
  ["stopped", "mute"],
  ["disabled", "mute"],
  ["not_started", "mute"],
]);

export function statusToKind(status: string): StatusKind {
  return STATUS_KIND_MAP.get(status) ?? "mute";
}

/**
 * Map a status + readiness pair to a StatusVariant.
 *
 * A RUNNING service that is not yet ready is treated as a warning state
 * (amber "Starting"). All other status+ready combinations delegate to
 * statusToVariant.
 */
export function readinessVariant(status: string, ready: boolean): StatusVariant {
  if (status === "running" && !ready) return "warning";
  return statusToVariant(status);
}
