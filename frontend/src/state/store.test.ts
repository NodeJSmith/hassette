import { beforeEach, describe, expect, it } from "vitest";

import type { ConnectedPayload } from "../api/ws-types";
import { initialState, useAppStore } from "./store";

function createConnectedPayload(overrides: Partial<ConnectedPayload> = {}): ConnectedPayload {
  return {
    uptime_seconds: 42,
    version: "1.2.3",
    ...overrides,
  } as ConnectedPayload;
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
    it("on first connect, does not clear serviceStatus/appStatus", () => {
      useAppStore.setState({
        serviceStatus: {
          svc: {
            resource_name: "svc",
            role: "r",
            status: "running",
            previous_status: null,
            exception: null,
            retry_at: null,
            ready: true,
            ready_phase: null,
          },
        },
        appStatus: {
          "app-a:0": { status: "running", index: 0 },
        },
      });

      useAppStore.getState().handleWsConnected(createConnectedPayload(), false);

      const state = useAppStore.getState();
      expect(state.connection).toBe("connected");
      expect(state.serviceStatus).toHaveProperty("svc");
      expect(state.appStatus).toHaveProperty("app-a:0");
    });

    it("on reconnect, clears serviceStatus/appStatus", () => {
      useAppStore.setState({
        serviceStatus: {
          svc: {
            resource_name: "svc",
            role: "r",
            status: "running",
            previous_status: null,
            exception: null,
            retry_at: null,
            ready: true,
            ready_phase: null,
          },
        },
        appStatus: {
          "app-a:0": { status: "running", index: 0 },
        },
      });

      useAppStore.getState().handleWsConnected(createConnectedPayload(), true);

      const state = useAppStore.getState();
      expect(state.connection).toBe("connected");
      expect(state.appStatus).toEqual({});
      expect(state.serviceStatus).toEqual({});
    });

    it("on first connect, does not bump logHintVersion", () => {
      const versionBefore = useAppStore.getState().logHintVersion;

      useAppStore.getState().handleWsConnected(createConnectedPayload(), false);

      expect(useAppStore.getState().logHintVersion).toBe(versionBefore);
    });

    it("on reconnect, bumps logHintVersion so use-log-data's cursor catch-up runs", () => {
      const versionBefore = useAppStore.getState().logHintVersion;

      useAppStore.getState().handleWsConnected(createConnectedPayload(), true);

      expect(useAppStore.getState().logHintVersion).toBe(versionBefore + 1);
    });

    it("sets systemVersion from payload, falling back to null when omitted", () => {
      useAppStore.getState().handleWsConnected(createConnectedPayload({ version: undefined }), false);
      expect(useAppStore.getState().systemVersion).toBeNull();

      useAppStore.getState().handleWsConnected(createConnectedPayload({ version: "9.9.9" }), false);
      expect(useAppStore.getState().systemVersion).toBe("9.9.9");
    });

    it("sets uptimeSeconds from the payload", () => {
      useAppStore.getState().handleWsConnected(createConnectedPayload({ uptime_seconds: 123 }), false);
      expect(useAppStore.getState().uptimeSeconds).toBe(123);
    });
  });

  describe("incrementLogHint", () => {
    it("increments logHintVersion", () => {
      const versionBefore = useAppStore.getState().logHintVersion;

      useAppStore.getState().incrementLogHint();

      expect(useAppStore.getState().logHintVersion).toBe(versionBefore + 1);
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

    it("setTimePreset persists to localStorage", () => {
      useAppStore.getState().setTimePreset("1h");

      expect(localStorage.getItem("hassette:timePreset")).toBe('"1h"');
      expect(useAppStore.getState().timePreset).toBe("1h");
    });
  });

  describe("updateAppStatus / updateServiceStatus / clearAppStatus / clearServiceStatus", () => {
    it("updateAppStatus merges a new entry without clobbering existing ones", () => {
      useAppStore.getState().updateAppStatus("app-a:0", { status: "running", index: 0 });
      useAppStore.getState().updateAppStatus("app-b:0", { status: "stopped", index: 0 });

      const state = useAppStore.getState();
      expect(state.appStatus["app-a:0"].status).toBe("running");
      expect(state.appStatus["app-b:0"].status).toBe("stopped");
    });

    it("clearAppStatus resets appStatus to an empty record", () => {
      useAppStore.getState().updateAppStatus("app-a:0", { status: "running", index: 0 });
      expect(Object.keys(useAppStore.getState().appStatus)).toHaveLength(1);

      useAppStore.getState().clearAppStatus();
      expect(useAppStore.getState().appStatus).toEqual({});
    });

    it("clearServiceStatus resets serviceStatus to an empty record", () => {
      useAppStore.getState().updateServiceStatus("svc", {
        resource_name: "svc",
        role: "r",
        status: "running",
        previous_status: null,
        exception: null,
        retry_at: null,
        ready: true,
        ready_phase: null,
      });
      expect(Object.keys(useAppStore.getState().serviceStatus)).toHaveLength(1);

      useAppStore.getState().clearServiceStatus();
      expect(useAppStore.getState().serviceStatus).toEqual({});
    });
  });
});
