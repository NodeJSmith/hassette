import { act } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppState } from "../state/create-app-state";
import { createTestQueryClient, renderHookWithProviders } from "../test/query-test-utils";
import { useWebSocket } from "./use-websocket";

/** Minimal mock WebSocket that tracks construction and allows simulating messages. */
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static OPEN = 1;

  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1; // OPEN
  sent: string[] = [];

  constructor() {
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3; // CLOSED
    this.onclose?.();
  }

  simulateOpen() {
    this.readyState = 1; // OPEN
    this.onopen?.();
  }

  simulateMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

describe("useWebSocket", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("creates only one WebSocket connection across re-renders", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    const { rerender } = renderHookWithProviders(() => useWebSocket(state), { queryClient });

    expect(MockWebSocket.instances).toHaveLength(1);

    // Re-render multiple times — should NOT create new connections
    rerender();
    rerender();
    rerender();

    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("does not set sessionId (signal does not exist)", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 120, entity_count: 10, app_count: 2, version: "" },
        timestamp: 1000,
      });
    });

    expect("sessionId" in state).toBe(false);
  });

  it("sets uptimeSeconds from connected message", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 300, entity_count: 5, app_count: 1, version: "" },
        timestamp: 1000,
      });
    });

    expect(state.uptimeSeconds.value).toBe(300);
  });

  it("initializes with 'connecting' state", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    expect(state.connection.value).toBe("connecting");

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    // Before onopen/onmessage, state should remain "connecting"
    expect(state.connection.value).toBe("connecting");
  });

  it("transitions to 'connected' on application-level connected message, not on onopen", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];

    // TCP connect (onopen) should NOT set "connected"
    act(() => {
      ws.simulateOpen();
    });
    expect(state.connection.value).toBe("connecting");

    // Application-level "connected" message should set "connected"
    act(() => {
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 100, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });
    expect(state.connection.value).toBe("connected");
  });

  it("transitions to 'disconnected' on first-connection failure", () => {
    vi.useFakeTimers();
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];

    // Close without ever receiving "connected" message
    act(() => {
      ws.onclose?.();
    });

    // Should be "disconnected" (not "reconnecting") since never connected
    expect(state.connection.value).toBe("disconnected");
  });

  it("closes socket on handshake timeout when server never sends connected message", () => {
    vi.useFakeTimers();
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];

    // TCP connect succeeds but server never sends "connected" message
    act(() => {
      ws.simulateOpen();
    });
    expect(state.connection.value).toBe("connecting");

    // Advance past handshake timeout (10s)
    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    // Socket should have been closed by the timeout, triggering onclose
    // which sets "disconnected" since hasConnectedRef is still false
    expect(state.connection.value).toBe("disconnected");
  });

  it("clears handshake timer when connected message arrives", () => {
    vi.useFakeTimers();
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 50, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });
    expect(state.connection.value).toBe("connected");

    // Advancing past timeout should NOT close the socket
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(state.connection.value).toBe("connected");
  });

  it("sends log subscribe on connect", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    const subscribeMsgs = ws.sent.map((s) => JSON.parse(s));
    expect(subscribeMsgs).toHaveLength(1);
    expect(subscribeMsgs[0]).toEqual({
      type: "subscribe",
      data: { logs: true, min_log_level: "INFO" },
    });
  });

  it("resubscribes on reconnect", () => {
    vi.useFakeTimers();
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    // First connect
    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
      ws1.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 100, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });
    expect(ws1.sent).toHaveLength(1);

    // Disconnect
    act(() => {
      ws1.onclose?.();
    });

    // Advance past backoff
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    const ws2 = MockWebSocket.instances[1];
    act(() => {
      ws2.simulateOpen();
      ws2.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 200, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    // Second socket should also have sent subscribe
    const subscribeMsgs = ws2.sent.map((s) => JSON.parse(s));
    expect(subscribeMsgs).toHaveLength(1);
    expect(subscribeMsgs[0]).toEqual({
      type: "subscribe",
      data: { logs: true, min_log_level: "INFO" },
    });
  });

  it("wires updateLogSubscription to send level updates", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    // Clear the initial subscribe message
    ws.sent.length = 0;

    // Call the targeted callback
    state.updateLogSubscription("WARNING");

    const msgs = ws.sent.map((s) => JSON.parse(s));
    expect(msgs).toHaveLength(1);
    expect(msgs[0]).toEqual({
      type: "subscribe",
      data: { logs: true, min_log_level: "WARNING" },
    });
  });

  it("updateLogSubscription is no-op after disconnect", () => {
    vi.useFakeTimers();
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    // Disconnect
    act(() => {
      ws.onclose?.();
    });

    // Clear sent from before disconnect
    ws.sent.length = 0;

    // Should not throw or send anything
    state.updateLogSubscription("ERROR");
    expect(ws.sent).toHaveLength(0);
  });

  it("maps service_status ready and ready_phase into serviceStatus state", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

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

    const entry = state.serviceStatus.value["WebsocketService"];
    expect(entry).toBeDefined();
    expect(entry.ready).toBe(true);
    expect(entry.ready_phase).toBe("Connected and authenticated");
    expect(entry.status).toBe("running");
  });

  it("defaults ready to false and ready_phase to null for pre-schema events", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

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

    const entry = state.serviceStatus.value["OldService"];
    expect(entry).toBeDefined();
    expect(entry.ready).toBe(false);
    expect(entry.ready_phase).toBeNull();
  });

  it("clears serviceStatus on reconnect", () => {
    vi.useFakeTimers();
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
      ws1.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

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

    expect(Object.keys(state.serviceStatus.value)).toHaveLength(1);

    act(() => {
      ws1.onclose?.();
    });

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    const ws2 = MockWebSocket.instances[1];
    act(() => {
      ws2.simulateOpen();
      ws2.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 200, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    expect(Object.keys(state.serviceStatus.value)).toHaveLength(0);
  });

  it("clears log store on reconnect", () => {
    vi.useFakeTimers();
    const state = createAppState();
    const queryClient = createTestQueryClient();

    // Push some entries into the log store before connecting
    state.logs.push({
      seq: 1,
      timestamp: 1000,
      level: "INFO",
      logger_name: "test",
      func_name: "f",
      lineno: 1,
      message: "stale",
      exc_info: null,
      app_key: null,
      execution_id: null,
      instance_name: null,
      instance_index: null,
      source_tier: null,
    });

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    // First connect
    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
      ws1.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    // Log store still has the entry from before connect (first connect does not clear)
    expect(state.logs.toArray()).toHaveLength(1);

    // Disconnect
    act(() => {
      ws1.onclose?.();
    });

    // Advance past backoff to trigger reconnect
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    const ws2 = MockWebSocket.instances[1];
    act(() => {
      ws2.simulateOpen();
      ws2.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 200, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    // Log store should be cleared on reconnect
    expect(state.logs.toArray()).toHaveLength(0);
  });

  it("writes invocation_completed batch to invocationCompleted signal", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    const batch = [
      { listener_id: 1, app_key: "my_app", instance_index: 0, status: "success", duration_ms: 42, error_type: null },
      {
        listener_id: 2,
        app_key: "my_app",
        instance_index: 0,
        status: "error",
        duration_ms: 10,
        error_type: "ValueError",
      },
    ];

    act(() => {
      ws.simulateMessage({ type: "invocation_completed", data: batch, timestamp: 1000 });
    });

    expect(state.invocationCompleted.value).toEqual(batch);
  });

  it("writes execution_completed batch to executionCompleted signal", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    const batch = [
      { job_id: 5, app_key: "my_app", instance_index: 0, status: "success", duration_ms: 80, error_type: null },
    ];

    act(() => {
      ws.simulateMessage({ type: "execution_completed", data: batch, timestamp: 1000 });
    });

    expect(state.executionCompleted.value).toEqual(batch);
  });

  it("calls queryClient.invalidateQueries() on reconnect", () => {
    vi.useFakeTimers();
    const state = createAppState();
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    // First connect — should NOT call invalidateQueries
    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
      ws1.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 100, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });
    expect(invalidateSpy).not.toHaveBeenCalled();

    // Simulate disconnect
    act(() => {
      ws1.onclose?.();
    });

    // Advance past backoff timer to trigger reconnect
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    // Second WebSocket created by reconnect
    const ws2 = MockWebSocket.instances[1];
    act(() => {
      ws2.simulateOpen();
      ws2.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 200, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    // On reconnect, invalidateQueries should have been called with no filter
    expect(invalidateSpy).toHaveBeenCalledOnce();
    expect(invalidateSpy).toHaveBeenCalledWith();
  });

  it("does not call queryClient.invalidateQueries() on first connect", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 100, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("drops invalid messages without updating state", () => {
    const state = createAppState();
    const queryClient = createTestQueryClient();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    renderHookWithProviders(() => useWebSocket(state), { queryClient });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({
        type: "connected",
        data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "" },
        timestamp: 1000,
      });
    });

    act(() => {
      ws.simulateMessage({ type: "invocation_completed", data: "not-an-array", timestamp: 1000 });
    });

    expect(state.invocationCompleted.value).toBeNull();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("[ws] invalid message:"), expect.anything());

    warnSpy.mockRestore();
  });
});
