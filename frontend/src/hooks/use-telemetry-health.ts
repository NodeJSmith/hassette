import { useEffect, useRef } from "preact/hooks";
import { useLocation } from "wouter";
import { ApiError } from "../api/client";
import { getTelemetryStatus } from "../api/endpoints";
import type { AppState } from "../state/create-app-state";

const BASE_INTERVAL_MS = 30_000;
const MAX_INTERVAL_MS = 120_000;

/**
 * Polls `/api/telemetry/status` to keep `appState.telemetryDegraded` current.
 *
 * - Runs regardless of which page is active (wired in app shell).
 * - Exponential backoff on consecutive failures: 30s -> 60s -> 120s cap.
 * - Resets to 30s on success AND on page navigation.
 * - On fetch failure, sets telemetryDegraded = true (unreachable = degraded).
 * - Uses AbortController to cancel in-flight requests on navigation, preventing
 *   stale completions from clobbering the navigation-reset interval.
 */
export function useTelemetryHealth(appState: AppState): void {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const currentIntervalMs = useRef(BASE_INTERVAL_MS);
  const abortRef = useRef<AbortController | null>(null);
  const [location] = useLocation();

  const poll = useRef(async () => {
    // Abort any in-flight request before starting a new one
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const result = await getTelemetryStatus(controller.signal);
      if (controller.signal.aborted) return; // Navigation cancelled us
      appState.telemetryDegraded.value = result.degraded;
      appState.droppedOverflow.value = result.dropped_overflow ?? 0;
      appState.droppedExhausted.value = result.dropped_exhausted ?? 0;
      appState.droppedNoSession.value = result.dropped_no_session ?? 0;
      appState.droppedShutdown.value = result.dropped_shutdown ?? 0;
      // Reset backoff on success
      if (currentIntervalMs.current !== BASE_INTERVAL_MS) {
        currentIntervalMs.current = BASE_INTERVAL_MS;
        restartInterval();
      }
    } catch (err) {
      // Ignore abort errors — navigation cancels in-flight requests via AbortController.
      if (err instanceof DOMException && err.name === "AbortError") return;

      // Distinguish server-reported DB degradation (HTTP 503) from network
      // unreachability. Only 503 means the DB is actually degraded; network
      // errors during rolling restarts should not show "DB degraded".
      if (err instanceof ApiError && err.status === 503) {
        appState.telemetryDegraded.value = true;
      }
      // Network error or unexpected status — leave telemetryDegraded unchanged.
      // A prior 503 keeps it true; a fresh start keeps it false. The backoff
      // handles retry and the next successful poll will clear it.

      // Apply exponential backoff: double current interval, cap at MAX
      const nextInterval = Math.min(currentIntervalMs.current * 2, MAX_INTERVAL_MS);
      if (nextInterval !== currentIntervalMs.current) {
        currentIntervalMs.current = nextInterval;
        restartInterval();
      }
    }
  }).current;

  function restartInterval() {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
    }
    intervalRef.current = setInterval(poll, currentIntervalMs.current);
  }

  // Start polling on mount, cleanup on unmount
  useEffect(() => {
    void poll();
    intervalRef.current = setInterval(poll, currentIntervalMs.current);
    return () => {
      abortRef.current?.abort();
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  // On page navigation: cancel in-flight, poll immediately, reset backoff
  const prevLocation = useRef(location);
  useEffect(() => {
    if (prevLocation.current !== location) {
      prevLocation.current = location;
      abortRef.current?.abort(); // Cancel stale in-flight request
      currentIntervalMs.current = BASE_INTERVAL_MS;
      restartInterval();
      void poll();
    }
  }, [location]);
}
