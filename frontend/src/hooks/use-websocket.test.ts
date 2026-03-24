import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/preact";
import { useWebSocket } from "./use-websocket";
import { createAppState } from "../state/create-app-state";

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
  const OriginalWebSocket = globalThis.WebSocket;

  beforeEach(() => {
    MockWebSocket.instances = [];
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    globalThis.WebSocket = OriginalWebSocket;
    vi.useRealTimers();
  });

  it("creates only one WebSocket connection across re-renders", () => {
    const state = createAppState();

    const { rerender } = renderHook(() => useWebSocket(state));

    expect(MockWebSocket.instances).toHaveLength(1);

    // Re-render multiple times — should NOT create new connections
    rerender();
    rerender();
    rerender();

    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("does not increment reconnectVersion on first connect", () => {
    const state = createAppState();

    renderHook(() => useWebSocket(state));

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({ type: "connected", data: { session_id: 1 } });
    });

    expect(state.reconnectVersion.value).toBe(0);
    expect(state.sessionId.value).toBe(1);
  });

  it("initializes with 'connecting' state", () => {
    const state = createAppState();
    expect(state.connection.value).toBe("connecting");

    renderHook(() => useWebSocket(state));

    // Before onopen/onmessage, state should remain "connecting"
    expect(state.connection.value).toBe("connecting");
  });

  it("transitions to 'connected' on application-level connected message, not on onopen", () => {
    const state = createAppState();

    renderHook(() => useWebSocket(state));

    const ws = MockWebSocket.instances[0];

    // TCP connect (onopen) should NOT set "connected"
    act(() => {
      ws.simulateOpen();
    });
    expect(state.connection.value).toBe("connecting");

    // Application-level "connected" message should set "connected"
    act(() => {
      ws.simulateMessage({ type: "connected", data: { session_id: 1 } });
    });
    expect(state.connection.value).toBe("connected");
  });

  it("transitions to 'disconnected' on first-connection failure", () => {
    vi.useFakeTimers();
    const state = createAppState();

    renderHook(() => useWebSocket(state));

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

    renderHook(() => useWebSocket(state));

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

    renderHook(() => useWebSocket(state));

    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({ type: "connected", data: { session_id: 1 } });
    });
    expect(state.connection.value).toBe("connected");

    // Advancing past timeout should NOT close the socket
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(state.connection.value).toBe("connected");
  });

  it("increments reconnectVersion on reconnect but not first connect", () => {
    vi.useFakeTimers();
    const state = createAppState();

    renderHook(() => useWebSocket(state));

    // First connect
    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
      ws1.simulateMessage({ type: "connected", data: { session_id: 1 } });
    });
    expect(state.reconnectVersion.value).toBe(0);

    // Simulate disconnect
    act(() => {
      ws1.onclose?.();
    });
    expect(state.connection.value).toBe("reconnecting");

    // Advance past backoff timer to trigger reconnect
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    // Second WebSocket created by reconnect
    expect(MockWebSocket.instances).toHaveLength(2);
    const ws2 = MockWebSocket.instances[1];

    act(() => {
      ws2.simulateOpen();
      ws2.simulateMessage({ type: "connected", data: { session_id: 2 } });
    });

    expect(state.reconnectVersion.value).toBe(1);
    expect(state.sessionId.value).toBe(2);
  });

  it("sends log subscribe on connect", () => {
    const state = createAppState();

    renderHook(() => useWebSocket(state));

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({ type: "connected", data: { session_id: 1 } });
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

    renderHook(() => useWebSocket(state));

    // First connect
    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
      ws1.simulateMessage({ type: "connected", data: { session_id: 1 } });
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
      ws2.simulateMessage({ type: "connected", data: { session_id: 2 } });
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

    renderHook(() => useWebSocket(state));

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({ type: "connected", data: { session_id: 1 } });
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

    renderHook(() => useWebSocket(state));

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
      ws.simulateMessage({ type: "connected", data: { session_id: 1 } });
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

  it("clears log store on reconnect", () => {
    vi.useFakeTimers();
    const state = createAppState();

    // Push some entries into the log store before connecting
    state.logs.push({
      seq: 1, timestamp: 1000, level: "INFO", logger_name: "test",
      func_name: "f", lineno: 1, message: "stale", exc_info: null, app_key: null,
    });

    renderHook(() => useWebSocket(state));

    // First connect
    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
      ws1.simulateMessage({ type: "connected", data: { session_id: 1 } });
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
      ws2.simulateMessage({ type: "connected", data: { session_id: 2 } });
    });

    // Log store should be cleared on reconnect
    expect(state.logs.toArray()).toHaveLength(0);
  });
});
