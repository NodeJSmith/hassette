import { beforeEach, describe, expect, it } from "vitest";

import type { ConnectedPayload, WsLogPayload } from "../api/ws-types";
import { RingBuffer } from "../utils/ring-buffer";
import { initialState, LOG_BUFFER_CAPACITY, useAppStore } from "./store";

function createLogEntry(seq: number): WsLogPayload {
  return {
    seq,
    timestamp: seq * 1000,
    level: "INFO",
    logger_name: "test",
    func_name: "test_func",
    lineno: 1,
    message: `msg-${seq}`,
    exc_info: null,
    app_key: null,
    execution_id: null,
    instance_name: null,
    instance_index: null,
    source_tier: null,
  };
}

function createConnectedPayload(overrides: Partial<ConnectedPayload> = {}): ConnectedPayload {
  return {
    uptime_seconds: 42,
    version: "1.2.3",
    ...overrides,
  } as ConnectedPayload;
}

describe("initialState", () => {
  it("constructs a fresh RingBuffer instance on each call", () => {
    const a = initialState();
    const b = initialState();

    expect(a.logBuffer).not.toBe(b.logBuffer);

    a.logBuffer.push(createLogEntry(1));
    expect(a.logBuffer.toArray()).toHaveLength(1);
    expect(b.logBuffer.toArray()).toHaveLength(0);
  });

  it("has a no-op sendLogLevel by default", () => {
    const state = initialState();
    expect(() => state.sendLogLevel("DEBUG")).not.toThrow();
  });
});

describe("useAppStore", () => {
  beforeEach(() => {
    useAppStore.setState({ ...initialState(), logBuffer: new RingBuffer<WsLogPayload>(LOG_BUFFER_CAPACITY) });
  });

  describe("handleWsConnected", () => {
    it("on first connect, does not clear serviceStatus/logBuffer/logVersion", () => {
      useAppStore.setState({
        serviceStatus: {
          svc: {
            resource_name: "svc",
            role: "r",
            status: "ok",
            previous_status: null,
            exception: null,
            retry_at: null,
            ready: true,
            ready_phase: null,
          },
        },
      });
      useAppStore.getState().pushLog(createLogEntry(1));
      const versionBeforeConnect = useAppStore.getState().logVersion;

      useAppStore.getState().handleWsConnected(createConnectedPayload(), false);

      const state = useAppStore.getState();
      expect(state.connection).toBe("connected");
      expect(state.serviceStatus).toHaveProperty("svc");
      expect(state.logBuffer.toArray()).toHaveLength(1);
      expect(state.logVersion).toBe(versionBeforeConnect);
    });

    it("on reconnect, clears serviceStatus/logBuffer and resets logVersion", () => {
      useAppStore.setState({
        serviceStatus: {
          svc: {
            resource_name: "svc",
            role: "r",
            status: "ok",
            previous_status: null,
            exception: null,
            retry_at: null,
            ready: true,
            ready_phase: null,
          },
        },
      });
      useAppStore.getState().pushLog(createLogEntry(1));
      const versionBeforeReconnect = useAppStore.getState().logVersion;

      useAppStore.getState().handleWsConnected(createConnectedPayload(), true);

      const state = useAppStore.getState();
      expect(state.connection).toBe("connected");
      expect(state.serviceStatus).toEqual({});
      expect(state.logBuffer.toArray()).toHaveLength(0);
      expect(state.logVersion).toBeGreaterThan(versionBeforeReconnect);
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

  describe("pushLog / clearLogs", () => {
    it("pushLog appends to the buffer and increments logVersion", () => {
      const versionBefore = useAppStore.getState().logVersion;

      useAppStore.getState().pushLog(createLogEntry(1));

      const state = useAppStore.getState();
      expect(state.logBuffer.toArray()).toHaveLength(1);
      expect(state.logVersion).toBe(versionBefore + 1);
    });

    it("clearLogs empties the buffer and increments logVersion", () => {
      useAppStore.getState().pushLog(createLogEntry(1));
      useAppStore.getState().pushLog(createLogEntry(2));
      const versionAfterPushes = useAppStore.getState().logVersion;

      useAppStore.getState().clearLogs();

      const state = useAppStore.getState();
      expect(state.logBuffer.toArray()).toHaveLength(0);
      expect(state.logVersion).toBeGreaterThan(versionAfterPushes);
    });

    it("getLogEntries reads the current buffer contents", () => {
      useAppStore.getState().pushLog(createLogEntry(1));
      useAppStore.getState().pushLog(createLogEntry(2));

      const entries = useAppStore.getState().getLogEntries();
      expect(entries).toHaveLength(2);
      expect(entries[0].seq).toBe(1);
      expect(entries[1].seq).toBe(2);
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

  describe("updateAppStatus / updateServiceStatus / clearServiceStatus", () => {
    it("updateAppStatus merges a new entry without clobbering existing ones", () => {
      useAppStore.getState().updateAppStatus("app-a:0", { status: "running", index: 0 });
      useAppStore.getState().updateAppStatus("app-b:0", { status: "stopped", index: 0 });

      const state = useAppStore.getState();
      expect(state.appStatus["app-a:0"].status).toBe("running");
      expect(state.appStatus["app-b:0"].status).toBe("stopped");
    });

    it("clearServiceStatus resets serviceStatus to an empty record", () => {
      useAppStore.getState().updateServiceStatus("svc", {
        resource_name: "svc",
        role: "r",
        status: "ok",
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
