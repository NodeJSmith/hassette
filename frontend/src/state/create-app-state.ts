import { batch, signal, type Signal } from "@preact/signals";
import { RingBuffer } from "../utils/ring-buffer";
import { getStoredValue } from "../utils/local-storage";
import { isSessionScope } from "../utils/session-scope";
import { isTheme } from "../utils/theme";
import type { WsLogPayload } from "../api/ws-types";

export type ConnectionStatus = "connecting" | "connected" | "reconnecting" | "disconnected";

export interface AppStatusEntry {
  status: string;
  index: number;
  previous_status?: string | null;
  instance_name?: string | null;
  class_name?: string | null;
  exception?: string | null;
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

  return {
    /**
     * Per-app status keyed by app_key, updated via WS.
     *
     * INVARIANT: appStatus changes trigger *debounced* page-level refetches
     * (via useDebouncedEffect in dashboard.tsx). This is intentionally separate
     * from reconnectVersion, which triggers *immediate* refetches (via useApi's
     * useSignalEffect). These two signals must remain independent code paths —
     * routing reconnection through appStatus would silently eat the reconnect
     * refetch behind the debounce timer.
     */
    appStatus: signal<Record<string, AppStatusEntry>>({}),

    /** WebSocket connection state machine. */
    connection: signal<ConnectionStatus>("connecting"),

    /** Log entries in a ring buffer with a version signal for efficient rendering. */
    logs: createLogStore(),

    /** Dark/light theme (initialized from localStorage via local-storage utility). */
    theme: signal<"dark" | "light">(
      getStoredValue<"dark" | "light">("theme", "dark", isTheme)
    ),

    /** Current Hassette session ID (from WS connected message). */
    sessionId: signal<number | null>(null),

    /** Session scope for telemetry queries (initialized from localStorage). */
    sessionScope: signal<"current" | "all">(
      getStoredValue<"current" | "all">("sessionScope", "current", isSessionScope)
    ),

    /**
     * Incremented on WS reconnection (not first connect). useApi reads this
     * to auto-refetch immediately via useSignalEffect.
     *
     * INVARIANT: reconnectVersion refetches must bypass debounce. See the
     * appStatus comment above for why these two signals must stay independent.
     */
    reconnectVersion: signal(0),

    /** Monotonic counter incremented every 30s to trigger relative-time re-renders. */
    tick: signal(0),

    /**
     * Telemetry database health status, polled by useTelemetryHealth.
     * True when /api/telemetry/status reports degradation or is unreachable.
     * Single source of truth — only the poller writes this signal.
     */
    telemetryDegraded: signal(false),

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

export type AppState = ReturnType<typeof createAppState>;
