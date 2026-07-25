import { useLocation, useSearch } from "wouter";

import { getAppJobs, getAppListeners, type JobData, type ListenerData } from "../api/endpoints";
import type { Crumb } from "../components/shared/breadcrumbs";
import { queryKeys } from "../lib/query-keys";
import { type HandlerKind, parseInstanceParam } from "../utils/app-routes";
import { buildTrail } from "../utils/breadcrumb-trail";
import { lastDotSegment } from "../utils/format";
import { useScopedQuery } from "./use-scoped-query";

/**
 * Ancestor trail for the current route, with handler ids resolved to their names.
 *
 * The handler lists are fetched through the same `useScopedQuery` the handlers tab uses,
 * against the same key, so the two share one cache entry and one request. That sharing is
 * the point: a non-reactive read (`getQueryData`, or a `skipToken` observer — which does
 * not re-render on cache writes) leaves the crumb stuck on its cold-cache fallback
 * ("listener 42") until something unrelated happens to re-render the status bar.
 *
 * Deriving the trail from the URL rather than having pages publish it keeps the trail a
 * pure function of the route, so it can never go stale mid-navigation.
 */
export function useBreadcrumbs(): Crumb[] {
  const [location] = useLocation();
  const searchString = useSearch();

  const pathname = location.split("?")[0];
  const instanceIndex = parseInstanceParam(new URLSearchParams(searchString).get("instance"));

  const segments = pathname.split("/").filter(Boolean);
  const appKey = segments[0] === "apps" ? segments[1] : undefined;
  const onHandlerRoute = appKey !== undefined && segments[2] === "handlers" && segments[3] !== undefined;

  // Hooks cannot be conditional, so both are always declared and gated by `enabled`.
  // appKey is only ever read when onHandlerRoute is true, which implies it is defined.
  const key = appKey ?? "";
  // The queries need a concrete instance, but the crumb hrefs must only carry ?instance=
  // when the user actually chose one — hence `idx` here and raw `instanceIndex` below.
  const idx = instanceIndex ?? 0;

  const { data: listeners } = useScopedQuery<ListenerData[]>(
    queryKeys.appListeners.base(key, idx),
    (since, signal) => getAppListeners(key, idx, since, signal),
    { enabled: onHandlerRoute },
  );

  const { data: jobs } = useScopedQuery<JobData[]>(
    queryKeys.appJobs.base(key, idx),
    (since, signal) => getAppJobs(key, idx, since, signal),
    { enabled: onHandlerRoute },
  );

  const resolveHandlerName = (kind: HandlerKind, id: number): string | undefined => {
    if (kind === "listener") {
      const match = listeners?.find((l) => l.listener_id === id);

      return match?.handler_method ? lastDotSegment(match.handler_method) : undefined;
    }

    return jobs?.find((j) => j.job_id === id)?.job_name;
  };

  return buildTrail(pathname, instanceIndex, resolveHandlerName);
}
