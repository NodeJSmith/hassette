import { create } from "zustand";

import type { components } from "../api/generated-types";
import type { ConnectedPayload as WsConnectedPayload, WsExecutionCompletedPayload } from "../api/ws-types";
import { getStoredValue, setStoredValue } from "../utils/local-storage";
import { isTheme } from "../utils/theme";

export const RELATIVE_TIME_TICK_MS = 30_000;

export type ConnectionStatus = "connecting" | "connected" | "reconnecting" | "disconnected";

/** Time-window presets for telemetry queries. */
export type TimePreset = "since-restart" | "1h" | "24h" | "7d";

/** Type guard for TimePreset values (localStorage and URL ?window= param). */
export function isTimePreset(v: unknown): v is TimePreset {
  return v === "since-restart" || v === "1h" || v === "24h" || v === "7d";
}

function isBoolean(v: unknown): v is boolean {
  return typeof v === "boolean";
}

type ResourceStatus = components["schemas"]["ResourceStatus"];

export interface AppStatusEntry {
  status: ResourceStatus;
  index: number;
  previous_status?: ResourceStatus | null;
  instance_name?: string | null;
  class_name?: string | null;
  exception?: string | null;
}

export function appStatusKey(appKey: string, index: number): string {
  return `${appKey}:${index}`;
}

export interface ServiceStatusEntry {
  resource_name: string;
  role: string;
  status: ResourceStatus;
  previous_status?: ResourceStatus | null;
  exception?: string | null;
  retry_at: number | null;
  /** Whether the service has called mark_ready(). False during startup phases. */
  ready: boolean;
  /** Human-readable description of the current readiness or startup phase, or null if not available. */
  ready_phase: string | null;
}

/** Telemetry health polled from `/api/telemetry/status`: drop counters and the degradation flag. */
export interface TelemetryHealth {
  droppedOverflow: number;
  droppedExhausted: number;
  droppedShutdown: number;
  errorHandlerFailures: number;
  telemetryDegraded: boolean;
}

/** Default values for `TelemetryHealth` fields, used by `initialState()` so each default
 * lives in exactly one place alongside the interface it mirrors. */
const TELEMETRY_DEFAULTS: TelemetryHealth = {
  droppedOverflow: 0,
  droppedExhausted: 0,
  droppedShutdown: 0,
  errorHandlerFailures: 0,
  telemetryDegraded: false,
};

export interface AppStore extends TelemetryHealth {
  // --- connection ---
  connection: ConnectionStatus;
  uptimeSeconds: number | null;
  systemVersion: string | null;
  setConnection: (status: ConnectionStatus) => void;

  // --- telemetry (health fields inherited from TelemetryHealth) ---
  appStatus: Record<string, AppStatusEntry>;
  serviceStatus: Record<string, ServiceStatusEntry>;
  executionCompleted: WsExecutionCompletedPayload[] | null;
  updateAppStatus: (key: string, entry: AppStatusEntry) => void;
  updateServiceStatus: (name: string, entry: ServiceStatusEntry) => void;
  clearAppStatus: () => void;
  clearServiceStatus: () => void;
  setExecutionCompleted: (data: WsExecutionCompletedPayload[]) => void;
  setTelemetryHealth: (data: Partial<TelemetryHealth>) => void;

  // --- preferences ---
  theme: "dark" | "light";
  sidebarCollapsed: boolean;
  setTheme: (t: "dark" | "light") => void;
  setSidebarCollapsed: (v: boolean) => void;

  // --- time window ---
  timePreset: TimePreset;
  urlWindowParam: TimePreset | null;
  tick: number;
  setTimePreset: (p: TimePreset) => void;
  setUrlWindowParam: (p: TimePreset | null) => void;
  incrementTick: () => void;

  // --- logs ---
  /** Bumped on every `log_hint` WS message — the signal `use-log-data.ts` debounces on to
   * trigger a cursor-based REST fetch. No log content lives in the store; the WS message
   * carries none. */
  logHintVersion: number;
  sendLogLevel: (level: string) => void;
  setSendLogLevel: (fn: (level: string) => void) => void;
  incrementLogHint: () => void;

  // --- composite actions ---
  handleWsConnected: (data: WsConnectedPayload, isReconnect: boolean) => void;
}

/**
 * Fresh initial state for the store. A factory (not a static object) so every
 * call — including test `afterEach` resets — reads storage-backed defaults fresh
 * rather than reusing a value captured at module load.
 */
export function initialState(): Omit<
  AppStore,
  | "setConnection"
  | "updateAppStatus"
  | "updateServiceStatus"
  | "clearAppStatus"
  | "clearServiceStatus"
  | "setExecutionCompleted"
  | "setTelemetryHealth"
  | "setTheme"
  | "setSidebarCollapsed"
  | "setTimePreset"
  | "setUrlWindowParam"
  | "incrementTick"
  | "setSendLogLevel"
  | "incrementLogHint"
  | "handleWsConnected"
> {
  return {
    // --- connection ---
    connection: "connecting",
    uptimeSeconds: null,
    systemVersion: null,

    // --- telemetry ---
    appStatus: {},
    serviceStatus: {},
    executionCompleted: null,
    ...TELEMETRY_DEFAULTS,

    // --- preferences ---
    theme: getStoredValue<"dark" | "light">("theme", "light", isTheme),
    sidebarCollapsed: getStoredValue<boolean>("sidebarCollapsed", false, isBoolean),

    // --- time window ---
    timePreset: getStoredValue<TimePreset>("timePreset", "since-restart", isTimePreset),
    urlWindowParam: null,
    tick: 0,

    // --- logs ---
    logHintVersion: 0,
    sendLogLevel: () => {},
  };
}

export const useAppStore = create<AppStore>()((set) => ({
  ...initialState(),

  // --- connection ---
  setConnection: (status) => set({ connection: status }),

  // --- telemetry ---
  updateAppStatus: (key, entry) => set((state) => ({ appStatus: { ...state.appStatus, [key]: entry } })),
  updateServiceStatus: (name, entry) => set((state) => ({ serviceStatus: { ...state.serviceStatus, [name]: entry } })),
  // Not called by handleWsConnected (see its comment) — kept as a standalone store primitive
  // for callers that need to clear app/service status on its own, and exercised directly in tests.
  clearAppStatus: () => set({ appStatus: {} }),
  clearServiceStatus: () => set({ serviceStatus: {} }),
  setExecutionCompleted: (data) => set({ executionCompleted: data }),
  setTelemetryHealth: (data) => set(data),

  // --- preferences ---
  // These setters aren't plain reducers: each one also writes its persisted copy (and, for
  // theme, the DOM attribute) so callers never have to remember to sync all three themselves.
  setTheme: (t) => {
    document.documentElement.setAttribute("data-theme", t);
    setStoredValue("theme", t);
    set({ theme: t });
  },
  setSidebarCollapsed: (v) => {
    setStoredValue("sidebarCollapsed", v);
    set({ sidebarCollapsed: v });
  },

  // --- time window ---
  // See the preferences note above — setTimePreset persists alongside the state write too.
  setTimePreset: (p) => {
    setStoredValue("timePreset", p);
    set({ timePreset: p });
  },
  setUrlWindowParam: (p) => set({ urlWindowParam: p }),
  incrementTick: () => set((state) => ({ tick: state.tick + 1 })),

  // --- logs ---
  setSendLogLevel: (fn) => set({ sendLogLevel: fn }),
  incrementLogHint: () => set((state) => ({ logHintVersion: state.logHintVersion + 1 })),

  // --- composite actions ---
  handleWsConnected: (data, isReconnect) =>
    // Everything here must land in this single set() call. Splitting it across multiple set()s
    // (e.g. calling clearServiceStatus()) would make atomicity depend on React's batching
    // rather than the shape of the code — a component could then observe an intermediate
    // render where connection is "connected" but serviceStatus/appStatus are stale.
    set((state) => ({
      connection: "connected",
      uptimeSeconds: data.uptime_seconds,
      systemVersion: data.version ?? null,
      // `isReconnect && {...}` is `false` (spreads to nothing) on first connect, or the object
      // (spreads its fields in) on reconnect — clears stale data / triggers catch-up only when
      // reconnecting. appStatus must clear here too: an instance's status/exception can change
      // while disconnected (the missed app_status_changed event is never replayed), and
      // instanceLiveStatus()/instanceLiveError() prefer any existing appStatus entry over the
      // freshly-refetched manifest data (see the reconnect invalidateQueries() call in
      // use-websocket.ts) for as long as it stays around -- so a stale entry can outlive the
      // refetch it was supposed to be superseded by. Logs bump `logHintVersion` here instead: that
      // is the only trigger use-log-data.ts's cursor-based catch-up watches, so without this the
      // `since_id` backfill it's built around never actually runs on reconnect — the disconnect
      // gap would otherwise be silently absorbed only by the unrelated, unfiltered
      // `invalidateQueries()` in use-websocket.ts, which drops anything older than one base-query
      // page instead of backfilling it.
      ...(isReconnect && {
        serviceStatus: {},
        appStatus: {},
        logHintVersion: state.logHintVersion + 1,
      }),
    })),
}));
