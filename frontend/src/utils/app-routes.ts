export type AppDetailTab = "overview" | "handlers" | "code" | "logs" | "config";

type QueryValue = string | number | null | undefined;

interface AppRouteQuery {
  instance?: QueryValue;
  line?: QueryValue;
}

function appendQuery(path: string, queryString: string): string {
  if (!queryString) return path;
  return `${path}${queryString.startsWith("?") ? queryString : `?${queryString}`}`;
}

function buildQuery(query?: AppRouteQuery): string {
  if (!query) return "";

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  }

  const queryString = params.toString();
  return queryString ? `?${queryString}` : "";
}

export function appDetailPath(appKey: string, tab?: AppDetailTab, query?: AppRouteQuery): string {
  const path = tab ? `/apps/${appKey}/${tab}` : `/apps/${appKey}`;
  return appendQuery(path, buildQuery(query));
}

export function appHandlersPath(appKey: string, query?: AppRouteQuery): string {
  return appendQuery(`/apps/${appKey}/handlers`, buildQuery(query));
}

export function appHandlerDetailPath(appKey: string, handlerSegment: string, query?: AppRouteQuery): string {
  return appendQuery(`/apps/${appKey}/handlers/${handlerSegment}`, buildQuery(query));
}
