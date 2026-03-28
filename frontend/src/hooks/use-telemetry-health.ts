import { useEffect, useRef } from "preact/hooks";
import { useLocation } from "wouter";
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
 */
export function useTelemetryHealth(appState: AppState): void {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const currentIntervalMs = useRef(BASE_INTERVAL_MS);
  const [location] = useLocation();

  const poll = useRef(async () => {
    try {
      const result = await getTelemetryStatus();
      appState.telemetryDegraded.value = result.degraded;
      // Reset backoff on success
      if (currentIntervalMs.current !== BASE_INTERVAL_MS) {
        currentIntervalMs.current = BASE_INTERVAL_MS;
        restartInterval();
      }
    } catch {
      appState.telemetryDegraded.value = true;
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
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  // On page navigation: poll immediately and reset backoff
  const prevLocation = useRef(location);
  useEffect(() => {
    if (prevLocation.current !== location) {
      prevLocation.current = location;
      currentIntervalMs.current = BASE_INTERVAL_MS;
      restartInterval();
      void poll();
    }
  }, [location]);
}
