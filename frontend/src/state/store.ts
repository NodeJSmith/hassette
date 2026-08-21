import { create } from "zustand";

import type { components } from "../api/generated-types";
import type {
  ConnectedPayload as WsConnectedPayload,
  WsExecutionCompletedPayload,
  WsLogPayload,
} from "../api/ws-types";
import { getStoredValue, setStoredValue } from "../utils/local-storage";
import { RingBuffer } from "../utils/ring-buffer";
import { isTheme } from "../utils/theme";

export const RELATIVE_TIME_TICK_MS = 30_000;
export const LOG_BUFFER_CAPACITY = 1000;

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

/** Telemetry health fields polled from /api/telemetry/status. Used by setTelemetryHealth's partial update. */
export interface TelemetryHealthFields {
  telemetryDegraded: boolean;
  droppedOverflow: number;
  droppedExhausted: number;
  droppedShutdown: number;
  errorHandlerFailures: number;
}

export interface AppStore {
  // --- connection ---
  connection: ConnectionStatus;
  uptimeSeconds: number | null;
  systemVersion: string | null;
  setConnection: (status: ConnectionStatus) => void;

  // --- telemetry ---
  appStatus: Record<string, AppStatusEntry>;
  serviceStatus: Record<string, ServiceStatusEntry>;
  executionCompleted: WsExecutionCompletedPayload[] | null;
  telemetryDegraded: boolean;
  droppedOverflow: number;
  droppedExhausted: number;
  droppedShutdown: number;
  errorHandlerFailures: number;
  updateAppStatus: (key: string, entry: AppStatusEntry) => void;
  updateServiceStatus: (name: string, entry: ServiceStatusEntry) => void;
  clearServiceStatus: () => void;
  setExecutionCompleted: (data: WsExecutionCompletedPayload[]) => void;
  setTelemetryHealth: (data: Partial<TelemetryHealthFields>) => void;

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
  logVersion: number;
  logBuffer: RingBuffer<WsLogPayload>;
  sendLogLevel: (level: string) => void;
  setSendLogLevel: (fn: (level: string) => void) => void;
  pushLog: (entry: WsLogPayload) => void;
  clearLogs: () => void;
  getLogEntries: () => WsLogPayload[];

  // --- composite actions ---
  handleWsConnected: (data: WsConnectedPayload, isReconnect: boolean) => void;
}

/**
 * Fresh initial state for the store. A factory (not a static object) so every
 * call — including test `afterEach` resets — constructs a brand-new `RingBuffer`
 * instance instead of reusing a mutated one across tests.
 */
export function initialState(): Omit<
  AppStore,
  | "setConnection"
  | "updateAppStatus"
  | "updateServiceStatus"
  | "clearServiceStatus"
  | "setExecutionCompleted"
  | "setTelemetryHealth"
  | "setTheme"
  | "setSidebarCollapsed"
  | "setTimePreset"
  | "setUrlWindowParam"
  | "incrementTick"
  | "setSendLogLevel"
  | "pushLog"
  | "clearLogs"
  | "getLogEntries"
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
    telemetryDegraded: false,
    droppedOverflow: 0,
    droppedExhausted: 0,
    droppedShutdown: 0,
    errorHandlerFailures: 0,

    // --- preferences ---
    theme: getStoredValue<"dark" | "light">("theme", "light", isTheme),
    sidebarCollapsed: getStoredValue<boolean>("sidebarCollapsed", false, isBoolean),

    // --- time window ---
    timePreset: getStoredValue<TimePreset>("timePreset", "since-restart", isTimePreset),
    urlWindowParam: null,
    tick: 0,

    // --- logs ---
    logVersion: 0,
    logBuffer: new RingBuffer<WsLogPayload>(LOG_BUFFER_CAPACITY),
    sendLogLevel: () => {},
  };
}

export const useAppStore = create<AppStore>()((set, get) => ({
  ...initialState(),

  // --- connection ---
  setConnection: (status) => set({ connection: status }),

  // --- telemetry ---
  updateAppStatus: (key, entry) => set((state) => ({ appStatus: { ...state.appStatus, [key]: entry } })),
  updateServiceStatus: (name, entry) => set((state) => ({ serviceStatus: { ...state.serviceStatus, [name]: entry } })),
  // Not called by handleWsConnected (see its comment) — kept as a standalone store primitive
  // for callers that need to clear service status on its own, and exercised directly in tests.
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
  pushLog: (entry) =>
    set((state) => {
      state.logBuffer.push(entry);
      return { logVersion: state.logVersion + 1 };
    }),
  // Not called by handleWsConnected (see its comment) — kept as a standalone store primitive
  // for callers that need to clear logs on their own, and exercised directly in tests.
  clearLogs: () =>
    set((state) => {
      state.logBuffer.clear();
      return { logVersion: state.logVersion + 1 };
    }),
  getLogEntries: () => get().logBuffer.toArray(),

  // --- composite actions ---
  handleWsConnected: (data, isReconnect) =>
    // Everything here must land in this single set() call. Splitting it across multiple set()s
    // (e.g. calling clearServiceStatus()/clearLogs()) would make atomicity depend on React's
    // batching rather than the shape of the code — a component could then observe an
    // intermediate render where connection is "connected" but serviceStatus/logs are stale.
    // The reconnect fields below duplicate what clearServiceStatus/clearLogs do (a fresh
    // RingBuffer, not `.clear()`, since a new object is what a single object literal needs),
    // not a call to them.
    set((state) => ({
      connection: "connected",
      uptimeSeconds: data.uptime_seconds,
      systemVersion: data.version ?? null,
      // `isReconnect && {...}` is `false` (spreads to nothing) on first connect, or the object
      // (spreads its fields in) on reconnect — clears stale data only when reconnecting.
      ...(isReconnect && {
        serviceStatus: {},
        logBuffer: new RingBuffer<WsLogPayload>(LOG_BUFFER_CAPACITY),
        logVersion: state.logVersion + 1,
      }),
    })),
}));
