import { keepPreviousData, useQuery, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";

import { useAppStore } from "@/state/store";
import { resolveSince } from "@/utils/time-window";

export interface UseScopedQueryOptions<T = unknown> {
  placeholderData?: typeof keepPreviousData;
  /** Skip the query entirely (e.g. the current route has no need for this data). */
  enabled?: boolean;
  /**
   * When false, a `since-restart` query fires immediately with an all-time window
   * (`since=null`) instead of blocking until the WS connected message provides
   * `uptimeSeconds`. The query key still includes uptime, so it refetches with the
   * accurate restart-relative window as soon as uptime arrives.
   *
   * Use for views that must render before HA/WS connects (e.g. the apps list, which
   * degrades gracefully with an all-time window). Leave at the default `true` for
   * views where an all-time fallback would be misleading. Default true.
   */
  waitForUptime?: boolean;
  /**
   * Forwarded to `useQuery`'s own `refetchInterval` — a fixed cadence, or a function of the query
   * that returns a cadence or `false`, so a caller can poll only while its data calls for it (the
   * Apps grid polls while an enrichment failure is on screen). TanStack stops interval refetches
   * automatically once the query is disabled (e.g. by `waitForUptime`'s gate), so callers don't
   * need to guard this themselves.
   */
  refetchInterval?: UseQueryOptions<T>["refetchInterval"];
  /**
   * Forwarded to `useQuery`'s own `refetchOnMount`. TanStack's default (`true`) only refetches
   * on mount if the cached entry is past `staleTime` — a remount inside that window silently
   * serves stale cached data with no network request. Pass `"always"` for a query whose
   * mount-time freshness matters more than avoiding a redundant fetch (e.g. one that tracks
   * external notifications that can arrive while unmounted, where a skipped fetch means those
   * notifications are lost, not just delayed).
   */
  refetchOnMount?: boolean | "always";
}

/**
 * Wraps `useQuery` with time-window scoping.
 *
 * Reads `effectiveTimePreset` and `uptimeSeconds` from AppState, computes the
 * `since` timestamp using `resolveSince`, and gates fetching via `enabled`.
 *
 * Query key strategy:
 * - For `since-restart`: `[...baseKey, preset, uptimeSeconds]` — uptime defines the window
 *   boundary and must be in the key so a new fetch fires when uptime changes.
 * - For fixed-window presets: `[...baseKey, preset]` — uptime is irrelevant; omitting it
 *   preserves cache entries across reconnects.
 *
 * @param baseKey  Stable query key prefix (e.g., `["app-listeners", appKey]`).
 * @param fetcher  Function accepting a `since` epoch-seconds timestamp.
 * @param options  Optional; see `UseScopedQueryOptions` for details. `placeholderData` for
 *   stale-while-revalidate behavior, `enabled` to skip the query, `waitForUptime` to opt out of the
 *   since-restart blocking gate, and `refetchInterval` / `refetchOnMount`, forwarded to `useQuery`.
 * @returns The usual `useQuery` result, plus the fully-resolved `queryKey` (baseKey + preset +
 *   uptime-if-since-restart). This is the single source of truth for "what scope is this query
 *   currently showing" — a caller that needs to detect a scope change (e.g. to invalidate a
 *   derived snapshot) should compare this key, not re-derive its own copy of the preset/uptime
 *   logic above. Two independent copies of that logic drift apart silently; see
 *   use-log-filters.ts's `scopeKey`-based tracking for the pattern.
 */
export function useScopedQuery<T>(
  baseKey: readonly unknown[],
  fetcher: (since: number | null, signal: AbortSignal) => Promise<T>,
  options?: UseScopedQueryOptions<T>,
): UseQueryResult<T> & { queryKey: readonly unknown[] } {
  const timePreset = useAppStore((s) => s.timePreset);
  const urlWindowParam = useAppStore((s) => s.urlWindowParam);
  const uptimeSeconds = useAppStore((s) => s.uptimeSeconds);

  const preset = urlWindowParam ?? timePreset;
  const waitForUptime = options?.waitForUptime ?? true;

  // Block fetches for since-restart until the WS connected message provides uptime_seconds,
  // unless the caller opted out via waitForUptime: false.
  const waitingForUptime = waitForUptime && preset === "since-restart" && uptimeSeconds === null;

  // Include uptime in the key only for since-restart (where it defines the window boundary).
  // Fixed-window presets omit uptime so cache entries survive reconnects.
  const queryKey = [...baseKey, preset, ...(preset === "since-restart" ? [uptimeSeconds] : [])] as const;

  const result = useQuery<T>({
    queryKey,
    queryFn: ({ signal }) => {
      // Falls back to an all-time window (since=null) when waitForUptime opted out of the blocking
      // gate above and uptime hasn't arrived yet.
      const since = resolveSince(preset, uptimeSeconds) ?? null;
      return fetcher(since, signal);
    },
    // Picked individually rather than `...options` — a blind spread would also forward
    // waitForUptime, which useQuery doesn't recognize. Add new UseScopedQueryOptions fields here too.
    placeholderData: options?.placeholderData,
    enabled: !waitingForUptime && (options?.enabled ?? true),
    refetchInterval: options?.refetchInterval,
    refetchOnMount: options?.refetchOnMount,
  });

  return { ...result, queryKey };
}
