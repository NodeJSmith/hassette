export type AppDetailTab = "overview" | "handlers" | "code" | "logs" | "config";

type QueryValue = string | number | null | undefined;

interface RouteQuery {
  instance?: QueryValue;
  line?: QueryValue;
}

function buildQuery(query?: RouteQuery): string {
  if (!query) return "";

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  }

  const queryString = params.toString();
  return queryString ? `?${queryString}` : "";
}

// ---------------------------------------------------------------------------
// Top-level page metadata
// ---------------------------------------------------------------------------

export interface NavPage {
  path: string;
  label: string;
  testId: string;
}

export const NAV_PAGES: readonly NavPage[] = [
  { path: "/apps", label: "apps", testId: "nav-apps" },
  { path: "/handlers", label: "handlers", testId: "nav-handlers" },
  { path: "/logs", label: "logs", testId: "nav-logs" },
  { path: "/config", label: "config", testId: "nav-config" },
  { path: "/diagnostics", label: "diagnostics", testId: "nav-diagnostics" },
];

export const HOME_PATH = "/apps";

// ---------------------------------------------------------------------------
// App-level paths
// ---------------------------------------------------------------------------

export function appDetailPath(appKey: string, tab?: AppDetailTab, query?: RouteQuery): string {
  const path = tab ? `/apps/${appKey}/${tab}` : `/apps/${appKey}`;
  return path + buildQuery(query);
}

export function appHandlersPath(appKey: string, query?: RouteQuery): string {
  return `/apps/${appKey}/handlers` + buildQuery(query);
}

// ---------------------------------------------------------------------------
// Handler-level paths
// ---------------------------------------------------------------------------

export type HandlerKind = "listener" | "job";

export function handlerPath(appKey: string, kind: HandlerKind, handlerId: number | string, query?: RouteQuery): string {
  return `/apps/${appKey}/handlers/${kind}/${handlerId}` + buildQuery(query);
}

// ---------------------------------------------------------------------------
// Execution-level paths
// ---------------------------------------------------------------------------

export function executionPath(
  appKey: string,
  kind: HandlerKind,
  handlerId: number | string,
  executionId: string,
  query?: RouteQuery,
): string {
  return `/apps/${appKey}/handlers/${kind}/${handlerId}/exec/${executionId}` + buildQuery(query);
}

// execution_kind uses "handler"/"job", but URL segments use the DB entity name "listener"/"job".
export function logEntryExecutionHref(entry: {
  app_key?: string | null;
  execution_kind?: string | null;
  listener_id?: number | null;
  job_id?: number | null;
  execution_id?: string | null;
  instance_index?: number | null;
}): string | null {
  if (!entry.app_key || !entry.execution_id || !entry.execution_kind) return null;
  if (entry.execution_kind === "handler" && entry.listener_id !== null && entry.listener_id !== undefined) {
    return executionPath(entry.app_key, "listener", entry.listener_id, entry.execution_id, {
      instance: entry.instance_index,
    });
  }
  if (entry.execution_kind === "job" && entry.job_id !== null && entry.job_id !== undefined) {
    return executionPath(entry.app_key, "job", entry.job_id, entry.execution_id, {
      instance: entry.instance_index,
    });
  }
  return null;
}
