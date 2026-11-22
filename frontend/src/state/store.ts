import { create } from "zustand";

import type { AppStatus, ResourceStatus } from "../api/endpoints";
import type { ConnectedData, ExecutionCompletedData, NeedsRestart } from "../api/ws-types";
import { getStoredValue, setStoredValue } from "../utils/local-storage";
import { isTheme } from "../utils/theme";

export const RELATIVE_TIME_TICK_MS = 30_000;
/** The hassette version this bundle was built from, the baseline for detecting a server update.
 * Both it and the server's reported version come from pyproject.toml's version (build time vs.
 * package metadata), so they're compared as exact strings. */
export const BUNDLE_VERSION = __HASSETTE_VERSION__;
/** What the server reports when it has no package metadata (`UNKNOWN_VERSION` in version_utils.py). */
const UNKNOWN_SERVER_VERSION = "unknown";

/** `unreachable` means several attempts in a row have failed and none has ever reached the
 * transport-level open. The usual causes are a misresolved URL or a server that isn't there,
 * though a proxy that drops the upgrade looks the same. A server that is restarting looks
 * different, because an earlier attempt already opened. */
export type ConnectionStatus = "connecting" | "connected" | "reconnecting" | "disconnected" | "unreachable";

/** Time-window presets for telemetry queries. */
export type TimePreset = "since-restart" | "1h" | "24h" | "7d";

/** Type guard for TimePreset values (localStorage and URL ?window= param). */
export function isTimePreset(v: unknown): v is TimePreset {
  return v === "since-restart" || v === "1h" || v === "24h" || v === "7d";
}

function isBoolean(v: unknown): v is boolean {
  return typeof v === "boolean";
}

/** One instance's latest `app_status_changed` delta. Applies over a snapshot row only when its `status_revision`
 * is strictly greater than the row's (see `liveInstanceEntry` in `utils/app-data.ts`). */
export interface AppStatusEntry {
  status: ResourceStatus;
  status_revision: number;
  instance_name: string;
  previous_status?: ResourceStatus | null;
  class_name?: string | null;
  exception?: string | null;
  /** Set when the instance needs a hassette restart; the first flag stands until restart. */
  needs_restart?: NeedsRestart | null;
}

/** An app's rollup from its latest `app_status_changed` delta, applied by the same rule as `AppStatusEntry`. */
export interface AppRollupEntry {
  app_status: AppStatus;
  status_revision: number;
}

/** Every `app_status_changed` delta seen since the last connect: per instance (keyed by `appStatusKey`) and per app. */
export interface LiveAppStatus {
  instances: Record<string, AppStatusEntry>;
  apps: Record<string, AppRollupEntry>;
}

const EMPTY_APP_STATUS: LiveAppStatus = { instances: {}, apps: {} };

export function appStatusKey(appKey: string, instanceName: string): string {
  return `${appKey}:${instanceName}`;
}

export interface ServiceStatusEntry {
  resource_name: string;
  status: ResourceStatus;
  previous_status?: ResourceStatus | null;
  exception?: string | null;
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
  /** True once a connect reports a different server version than `BUNDLE_VERSION`. The bundle
   * and its generated types match only the server version they were built for, so a different
   * version means the tab must reload; it stays true until then. */
  serverUpdated: boolean;
  /** True once a request gets a 401 that isn't Hassette's own (an expired Home Assistant ingress
   * session). Logging in can't fix that, so the app is replaced by a reload prompt; it stays true
   * until the page reloads. */
  sessionExpired: boolean;
  setConnection: (status: ConnectionStatus) => void;
  setSessionExpired: () => void;

  // --- telemetry (health fields inherited from TelemetryHealth) ---
  appStatus: LiveAppStatus;
  serviceStatus: Record<string, ServiceStatusEntry>;
  executionCompleted: ExecutionCompletedData[] | null;
  updateAppStatus: (appKey: string, instance: AppStatusEntry, app: AppRollupEntry) => void;
  updateServiceStatus: (name: string, entry: ServiceStatusEntry) => void;
  setExecutionCompleted: (data: ExecutionCompletedData[]) => void;
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
   * refetch the log view. No log content lives in the store; the WS message carries none. */
  logHintVersion: number;
  /** Whether log views show every framework line, not just the default view's framework errors.
   * One per-viewer preference shared by every log view, persisted like the other preferences. */
  showAllFrameworkLogs: boolean;
  sendLogLevel: (level: string) => void;
  setSendLogLevel: (fn: (level: string) => void) => void;
  incrementLogHint: () => void;
  setShowAllFrameworkLogs: (v: boolean) => void;

  // --- composite actions ---
  handleWsConnected: (data: ConnectedData, isReconnect: boolean) => void;
}

/**
 * Fresh initial state for the store. A factory (not a static object) so every
 * call — including test `afterEach` resets — reads storage-backed defaults fresh
 * rather than reusing a value captured at module load.
 */
export function initialState(): Omit<
  AppStore,
  | "setConnection"
  | "setSessionExpired"
  | "updateAppStatus"
  | "updateServiceStatus"
  | "setExecutionCompleted"
  | "setTelemetryHealth"
  | "setTheme"
  | "setSidebarCollapsed"
  | "setTimePreset"
  | "setUrlWindowParam"
  | "incrementTick"
  | "setSendLogLevel"
  | "incrementLogHint"
  | "setShowAllFrameworkLogs"
  | "handleWsConnected"
> {
  return {
    // --- connection ---
    connection: "connecting",
    uptimeSeconds: null,
    systemVersion: null,
    serverUpdated: false,
    sessionExpired: false,

    // --- telemetry ---
    appStatus: EMPTY_APP_STATUS,
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
    showAllFrameworkLogs: getStoredValue<boolean>("showAllFrameworkLogs", false, isBoolean),
    sendLogLevel: () => {},
  };
}

export const useAppStore = create<AppStore>()((set) => ({
  ...initialState(),

  // --- connection ---
  setConnection: (status) => set({ connection: status }),
  setSessionExpired: () => set({ sessionExpired: true }),

  // --- telemetry ---
  updateAppStatus: (appKey, instance, app) =>
    set((state) => ({
      appStatus: {
        instances: { ...state.appStatus.instances, [appStatusKey(appKey, instance.instance_name)]: instance },
        apps: { ...state.appStatus.apps, [appKey]: app },
      },
    })),
  updateServiceStatus: (name, entry) => set((state) => ({ serviceStatus: { ...state.serviceStatus, [name]: entry } })),
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
  // See the preferences note above — persists alongside the state write.
  setShowAllFrameworkLogs: (v) => {
    setStoredValue("showAllFrameworkLogs", v);
    set({ showAllFrameworkLogs: v });
  },

  // --- composite actions ---
  handleWsConnected: (data, isReconnect) =>
    // Everything here must land in this single set() call. Splitting it across multiple set()s
    // (e.g. a separate set() that clears serviceStatus) would make atomicity depend on React's batching
    // rather than the shape of the code — a component could then observe an intermediate
    // render where connection is "connected" but serviceStatus/appStatus are stale.
    set((state) => ({
      connection: "connected",
      uptimeSeconds: data.uptime_seconds,
      systemVersion: data.version ?? null,
      serverUpdated: state.serverUpdated || isVersionChange(data.version),
      // `isReconnect && {...}` is `false` (spreads to nothing) on first connect, or the object
      // (spreads its fields in) on reconnect — clears stale data only when reconnecting.
      // appStatus clears here too: a restarted server's deltas are compared against the refetched rows
      // (see the reconnect invalidateQueries() call in use-websocket.ts), and an entry from before the
      // disconnect has no reason to outlive them. Logs need no bump here: the unfiltered
      // `invalidateQueries()` in use-websocket.ts already covers the log query on reconnect,
      // same as every other cache entry.
      ...(isReconnect && {
        serviceStatus: {},
        appStatus: EMPTY_APP_STATUS,
      }),
    })),
}));

/** Whether a reported server version differs from the one this bundle was built for. An absent,
 * empty (older servers default it to ""), or "unknown" (no package metadata) version can't be
 * compared, so it isn't a change. */
function isVersionChange(reported: string | undefined): boolean {
  return Boolean(reported) && reported !== UNKNOWN_SERVER_VERSION && reported !== BUNDLE_VERSION;
}
