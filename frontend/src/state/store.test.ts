import { beforeEach, describe, expect, it } from "vitest";

import type { ConnectedData } from "../api/ws-types";
import { expectLogHintVersionIncrementedBy } from "../test/websocket-test-utils";
import { BUNDLE_VERSION, initialState, useAppStore } from "./store";

/** A server version that never equals the bundle's. */
const OTHER_VERSION = "999.0.0";

/** Defaults to the bundle's own version, so the data only signals an update when overridden. */
function createConnectedData(overrides: Partial<ConnectedData> = {}): ConnectedData {
  return {
    uptime_seconds: 42,
    entity_count: 0,
    app_count: 0,
    version: BUNDLE_VERSION,
    ...overrides,
  };
}

describe("initialState", () => {
  it("has a no-op sendLogLevel by default", () => {
    const state = initialState();
    expect(() => state.sendLogLevel("DEBUG")).not.toThrow();
  });

  it("starts logHintVersion at 0", () => {
    const state = initialState();
    expect(state.logHintVersion).toBe(0);
  });
});

describe("useAppStore", () => {
  beforeEach(() => {
    useAppStore.setState(initialState());
  });

  describe("handleWsConnected", () => {
    it("flags serverUpdated when a reconnect reports a version other than the bundle's", () => {
      useAppStore.getState().handleWsConnected(createConnectedData(), false);
      useAppStore.getState().handleWsConnected(createConnectedData({ version: OTHER_VERSION }), true);

      expect(useAppStore.getState().serverUpdated).toBe(true);
    });

    it("flags serverUpdated when the first connect already reports a different version", () => {
      // The tab loaded an old bundle while the socket was down and the server was upgraded:
      // the first version it ever sees is already newer than the bundle.
      useAppStore.getState().handleWsConnected(createConnectedData({ version: OTHER_VERSION }), false);

      expect(useAppStore.getState().serverUpdated).toBe(true);
    });

    it("does not flag serverUpdated when the server reports the bundle's version", () => {
      useAppStore.getState().handleWsConnected(createConnectedData(), false);

      expect(useAppStore.getState().serverUpdated).toBe(false);
    });

    it.each([
      ["an empty version", ""],
      ["no version", undefined],
      ["an unknown version", "unknown"],
    ])("does not flag serverUpdated for a connect reporting %s", (_, version) => {
      useAppStore.getState().handleWsConnected(createConnectedData({ version }), false);

      expect(useAppStore.getState().serverUpdated).toBe(false);
    });

    it("keeps serverUpdated set after a later connect reports the bundle's version again", () => {
      useAppStore.getState().handleWsConnected(createConnectedData({ version: OTHER_VERSION }), false);
      useAppStore.getState().handleWsConnected(createConnectedData(), true);

      expect(useAppStore.getState().serverUpdated).toBe(true);
    });

    it("on first connect, does not clear serviceStatus/appStatus", () => {
      useAppStore.setState({
        serviceStatus: {
          svc: {
            resource_name: "svc",
            status: "running",
            previous_status: null,
            exception: null,
            ready: true,
            ready_phase: null,
          },
        },
        appStatus: {
          instances: { "app-a:inst_0": { status: "running", instance_name: "inst_0", status_revision: 5 } },
          apps: { "app-a": { app_status: "running", status_revision: 5 } },
        },
      });

      useAppStore.getState().handleWsConnected(createConnectedData(), false);

      const state = useAppStore.getState();
      expect(state.connection).toBe("connected");
      expect(state.serviceStatus).toHaveProperty("svc");
      expect(state.appStatus.instances).toHaveProperty("app-a:inst_0");
      expect(state.appStatus.apps).toHaveProperty("app-a");
    });

    it("on reconnect, clears serviceStatus/appStatus", () => {
      useAppStore.setState({
        serviceStatus: {
          svc: {
            resource_name: "svc",
            status: "running",
            previous_status: null,
            exception: null,
            ready: true,
            ready_phase: null,
          },
        },
        appStatus: {
          instances: { "app-a:inst_0": { status: "running", instance_name: "inst_0", status_revision: 5 } },
          apps: { "app-a": { app_status: "running", status_revision: 5 } },
        },
      });

      useAppStore.getState().handleWsConnected(createConnectedData(), true);

      const state = useAppStore.getState();
      expect(state.connection).toBe("connected");
      expect(state.appStatus).toEqual({ instances: {}, apps: {} });
      expect(state.serviceStatus).toEqual({});
    });

    it("on first connect, does not bump logHintVersion", () => {
      const versionBefore = useAppStore.getState().logHintVersion;

      useAppStore.getState().handleWsConnected(createConnectedData(), false);

      expect(useAppStore.getState().logHintVersion).toBe(versionBefore);
    });

    it("on reconnect, does not bump logHintVersion (use-websocket's invalidateQueries covers logs)", () => {
      const versionBefore = useAppStore.getState().logHintVersion;

      useAppStore.getState().handleWsConnected(createConnectedData(), true);

      expect(useAppStore.getState().logHintVersion).toBe(versionBefore);
    });

    it("sets systemVersion from the connected data, falling back to null when omitted", () => {
      useAppStore.getState().handleWsConnected(createConnectedData({ version: undefined }), false);
      expect(useAppStore.getState().systemVersion).toBeNull();

      useAppStore.getState().handleWsConnected(createConnectedData({ version: "9.9.9" }), false);
      expect(useAppStore.getState().systemVersion).toBe("9.9.9");
    });

    it("sets uptimeSeconds from the connected data", () => {
      useAppStore.getState().handleWsConnected(createConnectedData({ uptime_seconds: 123 }), false);
      expect(useAppStore.getState().uptimeSeconds).toBe(123);
    });
  });

  describe("incrementLogHint", () => {
    it("increments logHintVersion", () => {
      const versionBefore = useAppStore.getState().logHintVersion;

      useAppStore.getState().incrementLogHint();

      expectLogHintVersionIncrementedBy(versionBefore);
    });

    it("increments once per call, coalescing is the caller's responsibility", () => {
      const versionBefore = useAppStore.getState().logHintVersion;

      useAppStore.getState().incrementLogHint();
      useAppStore.getState().incrementLogHint();
      useAppStore.getState().incrementLogHint();

      expect(useAppStore.getState().logHintVersion).toBe(versionBefore + 3);
    });
  });

  describe("setTelemetryHealth", () => {
    it("applies a partial update without touching unrelated fields", () => {
      useAppStore.setState({
        telemetryDegraded: false,
        droppedOverflow: 5,
        droppedExhausted: 2,
        droppedShutdown: 1,
        errorHandlerFailures: 0,
      });

      useAppStore.getState().setTelemetryHealth({ telemetryDegraded: true, droppedOverflow: 10 });

      const state = useAppStore.getState();
      expect(state.telemetryDegraded).toBe(true);
      expect(state.droppedOverflow).toBe(10);
      // Untouched fields retain their prior values
      expect(state.droppedExhausted).toBe(2);
      expect(state.droppedShutdown).toBe(1);
      expect(state.errorHandlerFailures).toBe(0);
    });
  });

  describe("setTheme / setSidebarCollapsed / setTimePreset", () => {
    it("setTheme writes the data-theme DOM attribute and persists to localStorage", () => {
      useAppStore.getState().setTheme("dark");

      expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
      expect(localStorage.getItem("hassette:theme")).toBe('"dark"');
      expect(useAppStore.getState().theme).toBe("dark");
    });

    it("setSidebarCollapsed persists to localStorage", () => {
      useAppStore.getState().setSidebarCollapsed(true);

      expect(localStorage.getItem("hassette:sidebarCollapsed")).toBe("true");
      expect(useAppStore.getState().sidebarCollapsed).toBe(true);
    });

    it("setShowAllFrameworkLogs persists to localStorage", () => {
      useAppStore.getState().setShowAllFrameworkLogs(true);

      expect(localStorage.getItem("hassette:showAllFrameworkLogs")).toBe("true");
      expect(useAppStore.getState().showAllFrameworkLogs).toBe(true);
    });

    it("setTimePreset persists to localStorage", () => {
      useAppStore.getState().setTimePreset("1h");

      expect(localStorage.getItem("hassette:timePreset")).toBe('"1h"');
      expect(useAppStore.getState().timePreset).toBe("1h");
    });
  });

  describe("updateAppStatus / updateServiceStatus", () => {
    it("updateAppStatus merges a new delta into both maps without clobbering existing ones", () => {
      const { updateAppStatus } = useAppStore.getState();
      updateAppStatus(
        "app-a",
        { status: "running", instance_name: "inst_0", status_revision: 5 },
        { app_status: "running", status_revision: 5 },
      );
      updateAppStatus(
        "app-b",
        { status: "stopped", instance_name: "inst_0", status_revision: 6 },
        { app_status: "stopped", status_revision: 6 },
      );

      const { appStatus } = useAppStore.getState();
      expect(appStatus.instances["app-a:inst_0"].status).toBe("running");
      expect(appStatus.instances["app-b:inst_0"].status_revision).toBe(6);
      expect(appStatus.apps["app-a"]).toEqual({ app_status: "running", status_revision: 5 });
      expect(appStatus.apps["app-b"]).toEqual({ app_status: "stopped", status_revision: 6 });
    });

    it("updateServiceStatus stores the entry under its resource name", () => {
      useAppStore.getState().updateServiceStatus("svc", {
        resource_name: "svc",
        status: "running",
        previous_status: null,
        exception: null,
        ready: true,
        ready_phase: null,
      });

      expect(useAppStore.getState().serviceStatus["svc"].status).toBe("running");
    });
  });
});
