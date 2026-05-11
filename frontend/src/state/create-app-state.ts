import { batch, computed, signal, type Signal } from "@preact/signals";
import { RingBuffer } from "../utils/ring-buffer";
import { getStoredValue } from "../utils/local-storage";
import { isTheme } from "../utils/theme";
import type { AppManifest } from "../api/endpoints";
import type { WsLogPayload, WsInvocationCompletedPayload, WsExecutionCompletedPayload } from "../api/ws-types";

export type ConnectionStatus = "connecting" | "connected" | "reconnecting" | "disconnected";

/** Time-window presets for telemetry queries. */
export type TimePreset = "since-restart" | "1h" | "24h" | "7d";

/** Type guard for TimePreset values (localStorage and URL ?window= param). */
export function isTimePreset(v: unknown): v is TimePreset {
  return v === "since-restart" || v === "1h" || v === "24h" || v === "7d";
}

export interface AppStatusEntry {
  status: string;
  index: number;
  previous_status?: string | null;
  instance_name?: string | null;
  class_name?: string | null;
  exception?: string | null;
}

export interface ServiceStatusEntry {
  resource_name: string;
  role: string;
  status: string;
  previous_status?: string | null;
  exception?: string | null;
  retry_at: number | null;
  /** Whether the service has called mark_ready(). False during startup phases. */
  ready: boolean;
  /** Human-readable description of the current readiness or startup phase, or null if not available. */
  ready_phase: string | null;
}

export interface LogStore {
  push(entry: WsLogPayload): void;
  toArray(): WsLogPayload[];
  clear(): void;
  version: Signal<number>;
}

export function createLogStore(): LogStore {
  const buffer = new RingBuffer<WsLogPayload>(1000);
  const version = signal(0);

  return {
    push(entry: WsLogPayload): void {
      batch(() => {
        buffer.push(entry);
        version.value++;
      });
    },
    toArray(): WsLogPayload[] {
      return buffer.toArray();
    },
    clear(): void {
      batch(() => {
        buffer.clear();
        version.value++;
      });
    },
    version,
  };
}

export function createAppState() {
  /** Server-side log level update callback; wired by useWebSocket after connect. */
  let _updateLogSubscription: (level: string) => void = () => {};

  // Pre-create signals that are referenced by computed values.
  const timePreset = signal<TimePreset>(
    getStoredValue<TimePreset>("timePreset", "since-restart", isTimePreset)
  );
  const urlWindowParam = signal<TimePreset | null>(null);

  /**
   * Effective time-window preset: URL `?window=` override takes priority over
   * the localStorage-backed `timePreset` when set. Falls back to `timePreset`
   * when `urlWindowParam` is null.
   *
   * `useScopedApi` reads this instead of `timePreset` directly so that URL
   * overrides reach the data layer without writing to localStorage.
   */
  const effectiveTimePreset = computed<TimePreset>(() => urlWindowParam.value ?? timePreset.value);

  return {
    /**
     * Per-app status keyed by app_key, updated via WS.
     *
     * INVARIANT: appStatus changes trigger *debounced* page-level refetches
     * (via useFilteredSignalRefetch in page components). This is intentionally separate
     * from reconnectVersion, which triggers *immediate* refetches (via useApi's
     * useSignalEffect). These two signals must remain independent code paths —
     * routing reconnection through appStatus would silently eat the reconnect
     * refetch behind the debounce timer.
     */
    appStatus: signal<Record<string, AppStatusEntry>>({}),

    /**
     * Per-service status keyed by resource_name, updated via WS service_status messages.
     *
     * Tracks the latest status of each internal Hassette service, including
     * exhaustion states (EXHAUSTED_DEAD, EXHAUSTED_COOLING) with their retry_at
     * timestamps.
     */
    serviceStatus: signal<Record<string, ServiceStatusEntry>>({}),

    /** WebSocket connection state machine. */
    connection: signal<ConnectionStatus>("connecting"),

    /** Shared manifest data — fetched once by useManifestFetcher, consumed by all pages. */
    manifests: signal<AppManifest[]>([]),
    manifestsLoading: signal(true),
    manifestsError: signal<string | null>(null),

    /** Log entries in a ring buffer with a version signal for efficient rendering. */
    logs: createLogStore(),

    /** Dark/light theme (initialized from localStorage via local-storage utility). */
    theme: signal<"dark" | "light">(
      getStoredValue<"dark" | "light">("theme", "light", isTheme)
    ),

    /**
     * Selected time-window preset for telemetry queries.
     * "since-restart" uses uptime_seconds from the WS connected message as the window boundary.
     * Persisted to localStorage.
     */
    timePreset,

    /**
     * Page-scoped URL time window override. Written by pages when a `?window=`
     * query parameter is present. Not persisted to localStorage.
     *
     * Null when no URL override is active (falls back to `timePreset`).
     * Pages set this on mount when they detect a `?window=` param, and clear it
     * (or leave it) on navigation away.
     */
    urlWindowParam,

    /**
     * Effective time-window preset: URL `?window=` override takes priority.
     * Falls back to `timePreset` (localStorage-backed) when `urlWindowParam` is null.
     * Read by `useScopedApi` instead of `timePreset` directly.
     */
    effectiveTimePreset,

    /**
     * Server uptime in seconds, received from the WS connected message.
     * Null until the first WS connected message is received.
     * Used by useScopedApi to compute the "since-restart" window boundary.
     */
    uptimeSeconds: signal<number | null>(null),

    /**
     * Hassette version string, received from the WS connected message.
     * Null until the first WS connected message is received.
     * Used by the sidebar version display.
     */
    systemVersion: signal<string | null>(null),

    /**
     * Latest batch of invocation_completed WS events.
     * Written by useWebSocket when an invocation_completed message arrives.
     * Consumers subscribe to this signal to trigger debounced refetches.
     */
    invocationCompleted: signal<WsInvocationCompletedPayload[] | null>(null),

    /**
     * Latest batch of execution_completed WS events.
     * Written by useWebSocket when an execution_completed message arrives.
     * Consumers subscribe to this signal to trigger debounced refetches.
     */
    executionCompleted: signal<WsExecutionCompletedPayload[] | null>(null),

    /**
     * Incremented on WS reconnection (not first connect). useApi reads this
     * to auto-refetch immediately via useSignalEffect.
     *
     * INVARIANT: reconnectVersion refetches must bypass debounce. See the
     * appStatus comment above for why these two signals must stay independent.
     */
    reconnectVersion: signal(0),

    /** Monotonic counter incremented every RELATIVE_TIME_TICK_MS to trigger relative-time re-renders. */
    tick: signal(0),

    /**
     * Telemetry database health status, polled by useTelemetryHealth.
     * True when /api/telemetry/status reports degradation or is unreachable.
     * Single source of truth — only the poller writes this signal.
     */
    telemetryDegraded: signal(false),

    /**
     * Count of telemetry events dropped due to queue overflow.
     * Updated by the telemetry health poller from /api/telemetry/status.
     * Non-zero indicates the DB writer is falling behind.
     */
    droppedOverflow: signal(0),

    /**
     * Count of telemetry events dropped due to queue exhaustion (backpressure).
     * Updated by the telemetry health poller from /api/telemetry/status.
     */
    droppedExhausted: signal(0),

    /**
     * Count of telemetry events dropped due to missing write prerequisite at drain time.
     * Startup-transient — typically ignorable unless chronic.
     */
    droppedNoSession: signal(0),

    /**
     * Count of telemetry events dropped during shutdown flush (DB unavailable).
     */
    droppedShutdown: signal(0),

    /**
     * Count of user error handler invocations that raised or timed out.
     * Updated by the telemetry health poller from /api/telemetry/status.
     */
    errorHandlerFailures: signal(0),

    /**
     * Request the server to update the minimum log level for WS log streaming.
     * Wired by useWebSocket once the socket is ready; no-op before that.
     */
    updateLogSubscription(level: string): void {
      _updateLogSubscription(level);
    },

    /**
     * Called by useWebSocket to wire the real implementation.
     * @internal — only for use-websocket.ts
     */
    setUpdateLogSubscription(fn: (level: string) => void): void {
      _updateLogSubscription = fn;
    },
  };
}

export const RELATIVE_TIME_TICK_MS = 30_000;

export type AppState = ReturnType<typeof createAppState>;
