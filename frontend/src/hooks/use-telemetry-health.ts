import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useLocation } from "wouter";

import { ApiError } from "../api/client";
import { getTelemetryStatus, type TelemetryStatus } from "../api/endpoints";
import { queryKeys } from "../lib/query-keys";
import { useAppStore } from "../state/store";

export const BASE_INTERVAL_MS = 30_000;
export const MAX_INTERVAL_MS = 120_000;
export const REQUEST_TIMEOUT_MS = 10_000;
const SERVICE_UNAVAILABLE_STATUS = 503;

/**
 * Fetches telemetry status and mirrors it into the app store's telemetry health fields.
 *
 * Only HTTP 503 means the server reported its DB as degraded, so only a 503 flips
 * `telemetryDegraded` on. Network errors and other statuses (e.g. during a rolling restart)
 * leave it unchanged: a prior 503 keeps it true, a fresh start keeps it false, and the next
 * successful poll clears it.
 */
async function fetchTelemetryHealth({ signal }: { signal: AbortSignal }): Promise<TelemetryStatus> {
  const { setTelemetryHealth } = useAppStore.getState();
  try {
    const status = await getTelemetryStatus(signal);
    // A response that settles after navigation cancelled the query must not overwrite the store.
    if (signal.aborted) return status;
    setTelemetryHealth({
      telemetryDegraded: status.degraded,
      droppedOverflow: status.dropped_overflow ?? 0,
      droppedExhausted: status.dropped_exhausted ?? 0,
      droppedShutdown: status.dropped_shutdown ?? 0,
      errorHandlerFailures: status.error_handler_failures ?? 0,
    });
    return status;
  } catch (err) {
    if (!signal.aborted && err instanceof ApiError && err.status === SERVICE_UNAVAILABLE_STATUS) {
      setTelemetryHealth({ telemetryDegraded: true });
    }
    throw err;
  }
}

/**
 * Polls `/api/telemetry/status` to keep the app store's telemetry health fields current.
 *
 * - Runs regardless of which page is active (wired in app shell).
 * - Polls every 30s while healthy, including in background tabs. A failure starts a retry chain
 *   with exponential backoff (60s, then 120s cap) that retries every error indefinitely, as the
 *   indicator should recover on its own; the fixed interval pauses during the chain so the two
 *   never overlap, and resumes once a fetch succeeds. TanStack pauses a retry chain while the
 *   tab is hidden and resumes it immediately when the tab regains focus.
 * - Page navigation cancels any in-flight fetch or pending retry and polls immediately,
 *   resetting the backoff.
 */
export function useTelemetryHealth(): void {
  const queryClient = useQueryClient();
  const [location] = useLocation();

  // Consumers read telemetry health from the app store (written by `fetchTelemetryHealth`), so the
  // query result itself is unused; the query owns scheduling, backoff, and cancellation. The
  // effect below resets it on navigation.
  useQuery({
    queryKey: queryKeys.telemetryStatus(),
    queryFn: fetchTelemetryHealth,
    refetchInterval: (query) => (query.state.fetchFailureCount > 0 ? false : BASE_INTERVAL_MS),
    refetchIntervalInBackground: true,
    retry: true, // retry indefinitely; retryDelay spaces the attempts out
    // `failureCount` is the number of failures before this one, so the first retry waits 60s.
    retryDelay: (failureCount) => Math.min(BASE_INTERVAL_MS * 2 ** (failureCount + 1), MAX_INTERVAL_MS),
  });

  const prevLocation = useRef(location);
  useEffect(() => {
    if (prevLocation.current === location) return;
    prevLocation.current = location;
    const queryKey = queryKeys.telemetryStatus();
    // Cancelling first drops a pending retry chain; a plain refetch would join it instead.
    void queryClient.cancelQueries({ queryKey }).then(() => queryClient.refetchQueries({ queryKey }));
  }, [location, queryClient]);
}
