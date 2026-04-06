export type StatusVariant = "success" | "danger" | "warning" | "neutral";

export type AppStatus = "running" | "failed" | "stopped" | "disabled" | "blocked" | "starting" | "shutting_down";

/** Statuses that represent intentionally non-active apps (not failures). */
export const INACTIVE_STATUSES: ReadonlySet<string> = new Set<AppStatus>(["stopped", "disabled", "shutting_down"]);
export type ErrorRateClass = "good" | "warn" | "bad";

const APP_STATUS_MAP: ReadonlyMap<string, StatusVariant> = new Map<string, StatusVariant>([
  ["running", "success"],
  ["failed", "danger"],
  ["stopped", "warning"],
  ["disabled", "neutral"],
  ["blocked", "warning"],  // Intentional: blocked = needs attention (matches small badge behavior)
  ["starting", "neutral"],
  ["shutting_down", "neutral"],
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
