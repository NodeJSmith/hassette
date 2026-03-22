import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/preact";
import { useWebSocket } from "./use-websocket";
import { createAppState } from "../state/create-app-state";

/** Minimal mock WebSocket that tracks construction and allows simulating messages. */
class MockWebSocket {
  static instances: MockWebSocket[] = [];

  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    MockWebSocket.instances.push(this);
  }

  close() {
    this.onclose?.();
  }

  simulateOpen() {
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
});
