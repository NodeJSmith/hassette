/**
 * Test utilities for `useWebSocket` hook tests.
 *
 * `MockWebSocket` is a minimal WebSocket stand-in that tracks construction and lets tests
 * simulate open/message/close events (install via `vi.stubGlobal("WebSocket", MockWebSocket)`).
 * `renderWebSocketHook()` renders the hook behind a fresh QueryClientProvider and returns the
 * most recently constructed MockWebSocket instance alongside the render result and its
 * QueryClient. `simulateConnected()` fires the transport-level open followed by the app-level
 * "connected" message that most tests need before exercising post-connect behavior;
 * `renderConnectedWebSocketHook()` and `reconnectWebSocket()` below wrap it for the common case,
 * while tests that need a spy installed before the connect event fires call it directly.
 */

import { act } from "@testing-library/react";
import { expect, vi } from "vitest";

import type { ConnectedPayload } from "../api/ws-types";
import { useWebSocket } from "../hooks/use-websocket";
import { createTestQueryClient, renderHookWithProviders } from "./query-test-utils";

/** Minimal mock WebSocket that tracks construction and allows simulating messages. */
export class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static OPEN = 1;
  static CLOSED = 3;

  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = MockWebSocket.OPEN;
  sent: string[] = [];

  constructor() {
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  simulateMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

/**
 * Renders `useWebSocket` behind a fresh QueryClientProvider and returns the render result plus
 * the QueryClient and the most recently constructed MockWebSocket.
 */
export function renderWebSocketHook() {
  const queryClient = createTestQueryClient();
  const result = renderHookWithProviders(() => useWebSocket(), { queryClient });
  const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
  return { ...result, queryClient, ws };
}

/**
 * Fires the transport-level open followed by the app-level "connected" message — the sequence
 * most `useWebSocket` tests need before exercising post-connect behavior. Used internally by
 * `renderConnectedWebSocketHook` and `reconnectWebSocket` below; exported separately for tests
 * that need to install a spy between render and connect (e.g. to observe the connect event
 * itself, not just its aftermath).
 */
export function simulateConnected(
  ws: MockWebSocket,
  overrides: Partial<ConnectedPayload> & { timestamp?: number } = {},
) {
  const { timestamp = 1000, ...data } = overrides;
  act(() => {
    ws.simulateOpen();
    ws.simulateMessage({
      type: "connected",
      data: { uptime_seconds: 60, entity_count: 0, app_count: 0, version: "", ...data },
      timestamp,
    });
  });
}

/**
 * Renders `useWebSocket` and immediately connects it (open + "connected" message) — the
 * combination most tests need before exercising post-connect behavior.
 */
export function renderConnectedWebSocketHook(overrides: Partial<ConnectedPayload> & { timestamp?: number } = {}) {
  const result = renderWebSocketHook();
  simulateConnected(result.ws, overrides);
  return result;
}

/**
 * Renders `useWebSocket` and fires a close that arrives before `onopen` ever fired for the
 * connection attempt — this backend's observable signal for a rejected handshake (or any other
 * pre-open failure). Returns the MockWebSocket the close was fired on.
 */
export function renderAndCloseBeforeOpen() {
  const { ws } = renderWebSocketHook();
  act(() => {
    ws.onclose?.();
  });
  return ws;
}

/**
 * Advances past the reconnect backoff window (synchronous fake timers) and asserts that a new
 * MockWebSocket connection was created in response.
 */
export function expectReconnectAfterBackoff() {
  act(() => {
    vi.advanceTimersByTime(2_000);
  });
  expect(MockWebSocket.instances).toHaveLength(2);
}

/**
 * Simulates a full disconnect-then-reconnect cycle: fires `onclose` on the given socket,
 * advances past the reconnect backoff window, and connects the new MockWebSocket that
 * `useWebSocket` creates in response. Requires `vi.useFakeTimers()` to already be active.
 * Returns the newly connected MockWebSocket.
 */
export function reconnectWebSocket(
  ws: MockWebSocket,
  overrides: Partial<ConnectedPayload> & { timestamp?: number } = {},
) {
  act(() => {
    ws.onclose?.();
  });
  act(() => {
    vi.advanceTimersByTime(2_000);
  });
  const reconnected = MockWebSocket.instances[MockWebSocket.instances.length - 1];
  simulateConnected(reconnected, { uptime_seconds: 200, ...overrides });
  return reconnected;
}
