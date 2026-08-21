// dup-ignore-start: shared 5-line import prologue also present in use-scoped-query.test.ts and use-telemetry-health.test.ts (T04/T05); import statements can't be extracted into a shared helper
import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAppStore } from "../state/store";
import { createLogEntry } from "../test/factories";
// dup-ignore-end
import { createWouterMock } from "../test/mock-wouter";
import {
  expectReconnectAfterBackoff,
  MockWebSocket,
  reconnectWebSocket,
  renderAndCloseBeforeOpen,
  renderConnectedWebSocketHook,
  renderWebSocketHook,
} from "../test/websocket-test-utils";
import { LOGIN_PATH } from "../utils/app-routes";

const mockNavigate = vi.hoisted(() => vi.fn());

vi.mock("wouter", () => createWouterMock({ useLocation: vi.fn().mockReturnValue(["/", mockNavigate]) }));

vi.mock("../api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../api/endpoints")>("../api/endpoints");
  return { ...actual, getSystemStatus: vi.fn() };
});

import { ApiError } from "../api/client";
import { getSystemStatus, type SystemStatus } from "../api/endpoints";

const mockedGetSystemStatus = vi.mocked(getSystemStatus);

const HEALTHY_SYSTEM_STATUS: SystemStatus = {
  status: "ok",
  websocket_connected: true,
  bootstrap_released: true,
  uptime_seconds: 120,
  entity_count: 10,
  app_count: 2,
  services: [],
  version: "1.0.0",
  boot_issues: [],
  log_queue_drops: 0,
  db_write_queue_drops: 0,
  log_persistence_active: true,
};

describe("useWebSocket", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    mockNavigate.mockClear();
    mockedGetSystemStatus.mockReset();
    // Default: the REST auth check confirms a real 401, so a close-before-onopen redirects.
    // Tests exercising the "false positive" path (still authenticated) override this.
    mockedGetSystemStatus.mockRejectedValue(new ApiError(401, "Unauthorized"));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("creates only one WebSocket connection across re-renders", () => {
    const { rerender } = renderWebSocketHook();

    expect(MockWebSocket.instances).toHaveLength(1);

    // Re-render multiple times — should NOT create new connections
    rerender();
    rerender();
    rerender();

    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("sets uptimeSeconds from connected message", () => {
    renderConnectedWebSocketHook({ uptime_seconds: 300, entity_count: 5, app_count: 1 });

    expect(useAppStore.getState().uptimeSeconds).toBe(300);
  });

  it("initializes with 'connecting' state", () => {
    expect(useAppStore.getState().connection).toBe("connecting");

    renderWebSocketHook();

    // Before onopen/onmessage, state should remain "connecting"
    expect(useAppStore.getState().connection).toBe("connecting");
  });

  it("transitions to 'connected' on application-level connected message, not on onopen", () => {
    const { ws } = renderWebSocketHook();

    // TCP connect (onopen) should NOT set "connected"
    act(() => {
      ws.simulateOpen();
    });
    expect(useAppStore.getState().connection).toBe("connecting");

    // Application-level "connected" message should set "connected"
    act(() => {
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 100, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });
    expect(useAppStore.getState().connection).toBe("connected");
  });

  it("transitions to 'disconnected' on first-connection failure", () => {
    vi.useFakeTimers();

    // Close without ever receiving "connected" message
    renderAndCloseBeforeOpen();

    // Should be "disconnected" (not "reconnecting") since never connected
    expect(useAppStore.getState().connection).toBe("disconnected");
  });

  describe("closed before onopen ever fires (ambiguous signal: could be a rejected handshake or any other pre-open failure)", () => {
    it("redirects to /login only after a REST check confirms a real 401", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      mockedGetSystemStatus.mockRejectedValue(new ApiError(401, "Unauthorized"));

      // Close arrives before onopen ever fired for this attempt.
      renderAndCloseBeforeOpen();

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith(LOGIN_PATH);
      });

      // Advance well past the backoff window — no reconnect attempt should have been scheduled.
      act(() => {
        vi.advanceTimersByTime(30_000);
      });
      expect(MockWebSocket.instances).toHaveLength(1);
    });

    it("does not redirect and reconnects with backoff when the REST check shows we're still authenticated", async () => {
      // Same observable signal (closed before onopen) but caused by something other than auth
      // rejection — e.g. a test server with no WS support, a transient network blip. The health
      // check succeeding proves the session is fine, so this must not bounce the user to /login.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      mockedGetSystemStatus.mockResolvedValue(HEALTHY_SYSTEM_STATUS);

      renderAndCloseBeforeOpen();

      await waitFor(() => {
        expect(mockedGetSystemStatus).toHaveBeenCalledTimes(1);
      });
      expect(mockNavigate).not.toHaveBeenCalled();

      // The existing reconnect-with-backoff behavior fires a new connection attempt.
      expectReconnectAfterBackoff();
    });

    it("does not redirect and reconnects with backoff when the REST check itself fails for a non-auth reason", async () => {
      // A network error (not an ApiError, or an ApiError that isn't 401) proves nothing about
      // auth -- must not be treated as a confirmed rejection.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      mockedGetSystemStatus.mockRejectedValue(new Error("network error"));

      renderAndCloseBeforeOpen();

      await waitFor(() => {
        expect(mockedGetSystemStatus).toHaveBeenCalledTimes(1);
      });
      expect(mockNavigate).not.toHaveBeenCalled();

      expectReconnectAfterBackoff();
    });

    it("reconnects instead of hanging forever when the auth check itself stalls", async () => {
      // Simulates a request that never settles on its own (e.g. server hung, dropped
      // connection with no TCP RST). Only the bounded timeout inside confirmAuthRejection
      // unblocks it — without that, scheduleReconnect would never run and the app would
      // stay disconnected indefinitely.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      mockedGetSystemStatus.mockImplementation(
        (signal) =>
          new Promise((_resolve, reject) => {
            signal?.addEventListener("abort", () =>
              reject(new DOMException("The operation was aborted", "AbortError")),
            );
          }),
      );

      renderAndCloseBeforeOpen();

      // Advance past the auth-check timeout — the stalled request should now be aborted.
      // Use the async variant so the rejection's catch/finally chain (and the subsequent
      // scheduleReconnect() call) actually runs before we advance further.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });

      expect(mockNavigate).not.toHaveBeenCalled();

      // Advance past reconnect backoff — must still fire even though the auth check never
      // resolved or rejected on its own.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(MockWebSocket.instances).toHaveLength(2);
    });

    it("keeps reconnecting (no redirect, no REST check) when a close arrives after onopen already fired", () => {
      vi.useFakeTimers();
      const { ws } = renderWebSocketHook();

      // onopen fires (transport-level connect succeeded) before the close — a previously
      // working connection dropping, not a rejected handshake — even though the app-level
      // "connected" message never arrived and hasConnectedRef is still false.
      act(() => {
        ws.simulateOpen();
        ws.onclose?.();
      });

      expect(mockNavigate).not.toHaveBeenCalled();
      expect(mockedGetSystemStatus).not.toHaveBeenCalled();

      // The existing reconnect-with-backoff behavior fires a new connection attempt.
      expectReconnectAfterBackoff();
    });
  });

  it("closes socket on handshake timeout when server never sends connected message", () => {
    vi.useFakeTimers();
    const { ws } = renderWebSocketHook();

    // TCP connect succeeds but server never sends "connected" message
    act(() => {
      ws.simulateOpen();
    });
    expect(useAppStore.getState().connection).toBe("connecting");

    // Advance past handshake timeout (10s)
    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    // Socket should have been closed by the timeout, triggering onclose
    // which sets "disconnected" since hasConnectedRef is still false
    expect(useAppStore.getState().connection).toBe("disconnected");
  });

  it("clears handshake timer when connected message arrives", () => {
    vi.useFakeTimers();
    renderConnectedWebSocketHook({ uptime_seconds: 50 });
    expect(useAppStore.getState().connection).toBe("connected");

    // Advancing past timeout should NOT close the socket
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(useAppStore.getState().connection).toBe("connected");
  });

  it("sends log subscribe on connect", () => {
    const { ws } = renderConnectedWebSocketHook();

    const subscribeMsgs = ws.sent.map((s) => JSON.parse(s));
    expect(subscribeMsgs).toHaveLength(1);
    expect(subscribeMsgs[0]).toEqual({
      type: "subscribe",
      data: { logs: true, min_log_level: "INFO" },
    });
  });

  it("resubscribes on reconnect", () => {
    vi.useFakeTimers();
    const { ws: ws1 } = renderConnectedWebSocketHook({ uptime_seconds: 100 });
    expect(ws1.sent).toHaveLength(1);

    const ws2 = reconnectWebSocket(ws1);

    // Second socket should also have sent subscribe
    const subscribeMsgs = ws2.sent.map((s) => JSON.parse(s));
    expect(subscribeMsgs).toHaveLength(1);
    expect(subscribeMsgs[0]).toEqual({
      type: "subscribe",
      data: { logs: true, min_log_level: "INFO" },
    });
  });

  it("wires sendLogLevel to send level updates", () => {
    const { ws } = renderConnectedWebSocketHook();

    // Clear the initial subscribe message
    ws.sent.length = 0;

    // Call the targeted callback
    useAppStore.getState().sendLogLevel("WARNING");

    const msgs = ws.sent.map((s) => JSON.parse(s));
    expect(msgs).toHaveLength(1);
    expect(msgs[0]).toEqual({
      type: "subscribe",
      data: { logs: true, min_log_level: "WARNING" },
    });
  });

  it("sendLogLevel is no-op after disconnect", () => {
    vi.useFakeTimers();
    const { ws } = renderConnectedWebSocketHook();

    // Disconnect
    act(() => {
      ws.onclose?.();
    });

    // Clear sent from before disconnect
    ws.sent.length = 0;

    // Should not throw or send anything
    useAppStore.getState().sendLogLevel("ERROR");
    expect(ws.sent).toHaveLength(0);
  });

  it("maps service_status ready and ready_phase into serviceStatus state", () => {
    const { ws } = renderConnectedWebSocketHook();

    act(() => {
      ws.simulateMessage({
        type: "service_status",
        data: {
          resource_name: "WebsocketService",
          role: "service",
          status: "running",
          previous_status: "starting",
          exception: null,
          exception_type: null,
          exception_traceback: null,
          retry_at: null,
          ready: true,
          ready_phase: "Connected and authenticated",
        },
        timestamp: 1000,
      });
    });

    const entry = useAppStore.getState().serviceStatus["WebsocketService"];
    expect(entry).toBeDefined();
    expect(entry.ready).toBe(true);
    expect(entry.ready_phase).toBe("Connected and authenticated");
    expect(entry.status).toBe("running");
  });

  it("defaults ready to false and ready_phase to null for pre-schema events", () => {
    const { ws } = renderConnectedWebSocketHook();

    act(() => {
      ws.simulateMessage({
        type: "service_status",
        data: {
          resource_name: "OldService",
          role: "service",
          status: "running",
          previous_status: null,
          exception: null,
          exception_type: null,
          exception_traceback: null,
          retry_at: null,
        },
        timestamp: 1000,
      });
    });

    const entry = useAppStore.getState().serviceStatus["OldService"];
    expect(entry).toBeDefined();
    expect(entry.ready).toBe(false);
    expect(entry.ready_phase).toBeNull();
  });

  it("clears serviceStatus on reconnect", () => {
    vi.useFakeTimers();
    const { ws: ws1 } = renderConnectedWebSocketHook();

    act(() => {
      ws1.simulateMessage({
        type: "service_status",
        data: {
          resource_name: "StaleSvc",
          role: "service",
          status: "running",
          previous_status: null,
          exception: null,
          exception_type: null,
          exception_traceback: null,
          retry_at: null,
          ready: false,
          ready_phase: "Connecting...",
        },
        timestamp: 1000,
      });
    });

    expect(Object.keys(useAppStore.getState().serviceStatus)).toHaveLength(1);

    reconnectWebSocket(ws1);

    expect(Object.keys(useAppStore.getState().serviceStatus)).toHaveLength(0);
  });

  it("clears log store on reconnect", () => {
    vi.useFakeTimers();

    // Push some entries into the log store before connecting
    useAppStore.getState().pushLog(
      createLogEntry({
        message: "stale",
        execution_id: null,
        instance_name: null,
        instance_index: null,
        source_tier: null,
      }),
    );

    const { ws: ws1 } = renderConnectedWebSocketHook();

    // Log store still has the entry from before connect (first connect does not clear)
    expect(useAppStore.getState().getLogEntries()).toHaveLength(1);

    reconnectWebSocket(ws1);

    // Log store should be cleared on reconnect
    expect(useAppStore.getState().getLogEntries()).toHaveLength(0);
  });

  it("writes execution_completed handler batch to executionCompleted", () => {
    const { ws } = renderConnectedWebSocketHook();

    const batch = [
      {
        kind: "handler",
        listener_id: 1,
        app_key: "my_app",
        instance_index: 0,
        status: "success",
        duration_ms: 42,
        error_type: null,
      },
      {
        kind: "handler",
        listener_id: 2,
        app_key: "my_app",
        instance_index: 0,
        status: "error",
        duration_ms: 10,
        error_type: "ValueError",
      },
    ];

    act(() => {
      ws.simulateMessage({ type: "execution_completed", data: batch, timestamp: 1000 });
    });

    expect(useAppStore.getState().executionCompleted).toEqual(batch);
  });

  it("writes execution_completed job batch to executionCompleted", () => {
    const { ws } = renderConnectedWebSocketHook();

    const batch = [
      {
        kind: "job",
        job_id: 5,
        app_key: "my_app",
        instance_index: 0,
        status: "success",
        duration_ms: 80,
        error_type: null,
      },
    ];

    act(() => {
      ws.simulateMessage({ type: "execution_completed", data: batch, timestamp: 1000 });
    });

    expect(useAppStore.getState().executionCompleted).toEqual(batch);
  });

  it("calls queryClient.invalidateQueries() on reconnect", () => {
    vi.useFakeTimers();
    const { queryClient, ws: ws1 } = renderConnectedWebSocketHook({ uptime_seconds: 100 });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    // First connect — should NOT call invalidateQueries
    expect(invalidateSpy).not.toHaveBeenCalled();

    reconnectWebSocket(ws1);

    // On reconnect, invalidateQueries should have been called with no filter
    expect(invalidateSpy).toHaveBeenCalledOnce();
    expect(invalidateSpy).toHaveBeenCalledWith();
  });

  it("does not call queryClient.invalidateQueries() on first connect", () => {
    const { queryClient } = renderConnectedWebSocketHook({ uptime_seconds: 100 });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("drops invalid messages without updating state", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { ws } = renderConnectedWebSocketHook();

    act(() => {
      ws.simulateMessage({ type: "execution_completed", data: "not-an-array", timestamp: 1000 });
    });

    expect(useAppStore.getState().executionCompleted).toBeNull();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("[ws] invalid message:"), expect.anything());

    warnSpy.mockRestore();
  });
});
