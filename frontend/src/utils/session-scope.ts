/** Valid session scope values for telemetry queries. */
export type SessionScope = "current" | "all";

const SCOPES: ReadonlySet<string> = new Set<string>(["current", "all"]);

/** Runtime type guard for session scope values stored in localStorage. */
export function isSessionScope(v: unknown): v is SessionScope {
  return typeof v === "string" && SCOPES.has(v);
}
