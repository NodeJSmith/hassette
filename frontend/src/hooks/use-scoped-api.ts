/**
 * Session-scoped data-fetching hook.
 *
 * Wraps `useApi` and resolves the effective `sessionId` based on
 * the current session scope signal. When scope is "current" and
 * sessionId is non-null, the fetcher receives the sessionId. When
 * scope is "all", the fetcher receives null (all-time). When scope
 * is "current" but sessionId is still null (not yet connected),
 * the hook returns a loading state without firing any fetch.
 *
 * Changes to `sessionScope` or `sessionId` automatically trigger
 * a refetch by including their values in the deps array.
 */

import { useRef } from "preact/hooks";
import { useApi, type UseApiOptions, type UseApiResult } from "./use-api";
import { useAppState } from "../state/context";

export interface UseScopedApiOptions extends UseApiOptions {
  /** Extra deps beyond scope signals (e.g., route params). */
  deps?: unknown[];
}

/**
 * Resolve the effective sessionId for a telemetry fetch.
 * Returns the sessionId when scope is "current" and it's available,
 * null when scope is "all", and undefined when waiting for sessionId.
 */
function resolveSessionId(
  scope: "current" | "all",
  sessionId: number | null,
): number | null | undefined {
  if (scope === "all") return null;
  // scope === "current" — need a real sessionId
  return sessionId ?? undefined;
}

/**
 * Session-scoped variant of `useApi`.
 *
 * @param fetcher - Function that accepts an optional sessionId and returns a promise.
 * @param options - Additional options (extra deps, lazy mode).
 */
export function useScopedApi<T>(
  fetcher: (sessionId: number | null) => Promise<T>,
  options: UseScopedApiOptions = {},
): UseApiResult<T> {
  const { deps: extraDeps = [], ...apiOptions } = options;
  const { sessionScope, sessionId } = useAppState();

  const scope = sessionScope.value;
  const sid = sessionId.value;
  const effective = resolveSessionId(scope, sid);

  // When scope is "current" but sessionId is not yet available,
  // return a static loading state without firing any fetch.
  const waitingForSession = effective === undefined;

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  // Combine scope signals with caller-provided deps so useApi
  // detects changes and triggers refetches.
  const allDeps = [scope, sid, ...extraDeps];

  return useApi(
    () => fetcherRef.current(effective ?? null),
    allDeps,
    { ...apiOptions, enabled: !waitingForSession },
  );
}
