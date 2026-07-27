import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/preact-query";

import { useAppState } from "../state/context";
import { resolveSince } from "../utils/time-window";

export interface UseScopedQueryOptions {
  placeholderData?: typeof keepPreviousData;
  /** Skip the query entirely (e.g. the current route has no need for this data). */
  enabled?: boolean;
  /**
   * When false, a `since-restart` query fires immediately with an all-time window
   * (`since=0`) instead of blocking until the WS connected message provides
   * `uptimeSeconds`. The query key still includes uptime, so it refetches with the
   * accurate restart-relative window as soon as uptime arrives.
   *
   * Use for views that must render before HA/WS connects (e.g. the apps list, which
   * degrades gracefully with an all-time window). Leave at the default `true` for
   * views where an all-time fallback would be misleading. Default true.
   */
  waitForUptime?: boolean;
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
 * @param options  Optional: `placeholderData` for stale-while-revalidate behavior, `waitForUptime`
 *   to opt out of the since-restart blocking gate.
 */
export function useScopedQuery<T>(
  baseKey: readonly unknown[],
  fetcher: (since: number, signal: AbortSignal) => Promise<T>,
  options?: UseScopedQueryOptions,
): UseQueryResult<T> {
  const { effectiveTimePreset, uptimeSeconds } = useAppState();

  const preset = effectiveTimePreset.value;
  const uptime = uptimeSeconds.value;
  const waitForUptime = options?.waitForUptime ?? true;

  // Block fetches for since-restart until the WS connected message provides uptime_seconds,
  // unless the caller opted out via waitForUptime: false.
  const waitingForUptime = waitForUptime && preset === "since-restart" && uptime === null;

  // Include uptime in the key only for since-restart (where it defines the window boundary).
  // Fixed-window presets omit uptime so cache entries survive reconnects.
  const queryKey = [...baseKey, preset, ...(preset === "since-restart" ? [uptime] : [])] as const;

  return useQuery<T>({
    queryKey,
    queryFn: ({ signal }) => {
      // Falls back to an all-time window (since=0) when waitForUptime opted out of the
      // blocking gate above and uptime hasn't arrived yet.
      const since = resolveSince(preset, uptime) ?? 0;
      return fetcher(since, signal);
    },
    // Picked individually rather than `...options` — a blind spread would also forward
    // waitForUptime, which useQuery doesn't recognize. Add new UseScopedQueryOptions fields here too.
    placeholderData: options?.placeholderData,
    enabled: !waitingForUptime && (options?.enabled ?? true),
  });
}
