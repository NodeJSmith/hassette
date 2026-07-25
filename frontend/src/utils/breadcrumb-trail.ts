import type { Crumb } from "../components/shared/breadcrumbs";
import { appDetailPath, type AppDetailTab, type HandlerKind, handlerPath } from "./app-routes";
import { truncateId } from "./format";

/**
 * Resolves a handler's display name from already-cached data.
 * Returns undefined when the cache is cold, which is the caller's cue to fall back to the id.
 */
export type HandlerNameResolver = (kind: HandlerKind, id: number) => string | undefined;

const APP_TABS = new Set<string>(["overview", "handlers", "code", "logs", "config"] satisfies AppDetailTab[]);

const HANDLER_KINDS = new Set<string>(["listener", "job"] satisfies HandlerKind[]);

/** Routes with no ancestors — their crumb is just the page itself. */
const TOP_LEVEL_LABELS: Record<string, string> = {
  apps: "apps",
  handlers: "handlers",
  logs: "logs",
  config: "config",
  diagnostics: "diagnostics",
  design: "design",
};

/** The page you are already on is not a link. */
function markLastAsCurrent(crumbs: Crumb[]): Crumb[] {
  if (crumbs.length === 0) return crumbs;

  return crumbs.map((crumb, i) => (i === crumbs.length - 1 ? { label: crumb.label } : crumb));
}

/**
 * Derives the ancestor trail from the current path.
 *
 * Structure comes from the route — the hierarchy the URL already encodes. Only the
 * handler crumb needs outside help: the URL carries a numeric id, and users navigated
 * there by name, so `resolveHandlerName` supplies the label from cached handler data.
 * A cold cache degrades to `listener 42` and upgrades on its own once the query lands.
 *
 * @param pathname       Location with any query string already stripped.
 * @param instanceIndex  Active `?instance=` value, carried onto ancestor links so
 *                       navigating up stays on the same app instance.
 */
export function buildTrail(
  pathname: string,
  instanceIndex: number | undefined,
  resolveHandlerName: HandlerNameResolver,
): Crumb[] {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return [];

  const [root, ...rest] = segments;

  if (root !== "apps") {
    const label = TOP_LEVEL_LABELS[root];
    return label ? [{ label }] : [];
  }

  const query = { instance: instanceIndex };
  const crumbs: Crumb[] = [{ label: "apps", href: "/apps" }];

  const appKey = rest[0];
  if (appKey === undefined) return markLastAsCurrent(crumbs);
  crumbs.push({ label: appKey, href: appDetailPath(appKey, undefined, query) });

  const tab = rest[1];
  if (tab === undefined || !APP_TABS.has(tab)) return markLastAsCurrent(crumbs);
  crumbs.push({ label: tab, href: appDetailPath(appKey, tab as AppDetailTab, query) });

  const kind = rest[2];
  const handlerId = rest[3];
  if (tab !== "handlers" || kind === undefined || handlerId === undefined || !HANDLER_KINDS.has(kind)) {
    return markLastAsCurrent(crumbs);
  }

  const parsedId = Number(handlerId);
  const name = Number.isInteger(parsedId) ? resolveHandlerName(kind as HandlerKind, parsedId) : undefined;
  crumbs.push({
    label: name ?? `${kind} ${handlerId}`,
    href: handlerPath(appKey, kind as HandlerKind, handlerId, query),
  });

  const execId = rest[4] === "exec" ? rest[5] : undefined;
  if (execId !== undefined) crumbs.push({ label: truncateId(execId) });

  return markLastAsCurrent(crumbs);
}
