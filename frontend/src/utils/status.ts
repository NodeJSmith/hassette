export type StatusVariant = "success" | "danger" | "warning" | "neutral";

export type AppStatus = "running" | "failed" | "stopped" | "disabled" | "blocked" | "starting" | "shutting_down";
export type HealthGrade = "excellent" | "good" | "warning" | "critical";
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

const HEALTH_GRADE_MAP: ReadonlyMap<string, StatusVariant> = new Map<string, StatusVariant>([
  ["excellent", "success"],
  ["good", "success"],
  ["warning", "warning"],
  ["critical", "danger"],
]);

const ERROR_RATE_MAP: ReadonlyMap<string, StatusVariant> = new Map<string, StatusVariant>([
  ["good", "success"],
  ["warn", "warning"],
  ["bad", "danger"],
]);

export const APP_STATUSES: ReadonlySet<string> = new Set(APP_STATUS_MAP.keys());
export const HEALTH_GRADES: ReadonlySet<string> = new Set(HEALTH_GRADE_MAP.keys());
export const ERROR_RATE_CLASSES: ReadonlySet<string> = new Set(ERROR_RATE_MAP.keys());

/** Map an app status string to a StatusVariant. Unknown values return "neutral" with a console.warn. */
export function statusToVariant(status: string): StatusVariant {
  const variant = APP_STATUS_MAP.get(status);
  if (variant !== undefined) return variant;
  console.warn(`Unknown app status: "${status}"`);
  return "neutral";
}

/** Map a health grade string to a StatusVariant. Unknown values return "neutral" with a console.warn. */
export function healthGradeToVariant(grade: string): StatusVariant {
  const variant = HEALTH_GRADE_MAP.get(grade);
  if (variant !== undefined) return variant;
  console.warn(`Unknown health grade: "${grade}"`);
  return "neutral";
}

/** Map an error rate class string to a StatusVariant. Unknown values return "neutral" with a console.warn. */
export function errorRateToVariant(cls: string): StatusVariant {
  const variant = ERROR_RATE_MAP.get(cls);
  if (variant !== undefined) return variant;
  console.warn(`Unknown error rate class: "${cls}"`);
  return "neutral";
}
