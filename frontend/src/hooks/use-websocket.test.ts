// dup-ignore-start: shared 5-line import prologue also present in use-scoped-query.test.ts and use-telemetry-health.test.ts (T04/T05); import statements can't be extracted into a shared helper
import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { getSystemStatus, type SystemStatus, WS_PATH } from "../api/endpoints";
import { resolveWsUrl } from "../lib/base-path";
import { useAppStore } from "../state/store";
import { createSystemStatus } from "../test/factories";
// dup-ignore-end
import { createWouterMock } from "../test/mock-wouter";
import {
  expectLogHintVersionIncrementedBy,
  expectReconnectAfterBackoff,
  MockWebSocket,
  reconnectWebSocket,
  renderAndCloseBeforeOpen,
  renderConnectedWebSocketHook,
  renderWebSocketHook,
  simulateConnected,
} from "../test/websocket-test-utils";
import { LOGIN_PATH } from "../utils/app-routes";
import {
  AUTH_CHECK_TIMEOUT_MS,
  HANDSHAKE_TIMEOUT_MS,
  INITIAL_BACKOFF_MS,
  JITTER_RATIO,
  jitteredDelay,
  MAX_BACKOFF_MS,
  UNREACHABLE_ATTEMPT_THRESHOLD,
} from "./use-websocket";

const mockNavigate = vi.hoisted(() => vi.fn());

vi.mock("wouter", () => createWouterMock({ useLocation: vi.fn().mockReturnValue(["/", mockNavigate]) }));

vi.mock("../api/endpoints", async () => {
  const actual = await vi.importActual<typeof import("../api/endpoints")>("../api/endpoints");
  return { ...actual, getSystemStatus: vi.fn() };
});

const mockedGetSystemStatus = vi.mocked(getSystemStatus);

const HEALTHY_SYSTEM_STATUS: SystemStatus = createSystemStatus();
const HASSETTE_401 = new ApiError(401, "Unauthorized", undefined, "not_authenticated");

describe("useWebSocket", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    mockNavigate.mockClear();
    mockedGetSystemStatus.mockReset();
    // Default: the REST auth check confirms Hassette's own 401, so a close-before-onopen redirects.
    // Tests exercising the "false positive" path (still authenticated) override this.
    mockedGetSystemStatus.mockRejectedValue(HASSETTE_401);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.restoreAllMocks();
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

  it("connects to the WebSocket resolved against the base", () => {
    renderWebSocketHook();

    expect(MockWebSocket.instances[0].url).toBe(resolveWsUrl(WS_PATH));
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

  /** Opens the first socket, then closes it: a reconnect that skips the auth check. */
  function renderAndCloseAfterOpen() {
    const { ws } = renderWebSocketHook();
    act(() => {
      ws.simulateOpen();
      ws.onclose?.();
    });
  }

  describe("closed before onopen ever fires (ambiguous signal: could be a rejected handshake or any other pre-open failure)", () => {
    it("redirects to /login only after a REST check confirms Hassette's own 401", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      mockedGetSystemStatus.mockRejectedValue(HASSETTE_401);

      // Close arrives before onopen ever fired for this attempt.
      renderAndCloseBeforeOpen();

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith(LOGIN_PATH);
      });
      expect(useAppStore.getState().sessionExpired).toBe(false);

      // Advance well past the backoff window — no reconnect attempt should have been scheduled.
      act(() => {
        vi.advanceTimersByTime(MAX_BACKOFF_MS);
      });
      expect(MockWebSocket.instances).toHaveLength(1);
    });

    it("shows the session-expired view, without redirecting or reconnecting, on a 401 that isn't Hassette's", async () => {
      // Supervisor answers an expired HA ingress session with a bare 401 (no problem code).
      vi.useFakeTimers({ shouldAdvanceTime: true });
      mockedGetSystemStatus.mockRejectedValue(new ApiError(401, "Unauthorized"));

      renderAndCloseBeforeOpen();

      await waitFor(() => {
        expect(useAppStore.getState().sessionExpired).toBe(true);
      });
      expect(mockNavigate).not.toHaveBeenCalled();

      act(() => {
        vi.advanceTimersByTime(MAX_BACKOFF_MS);
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
        await vi.advanceTimersByTimeAsync(AUTH_CHECK_TIMEOUT_MS);
      });

      expect(mockNavigate).not.toHaveBeenCalled();

      // Advance past reconnect backoff — must still fire even though the auth check never
      // resolved or rejected on its own. The first reconnect waits INITIAL_BACKOFF_MS; doubling
      // it is just a safe margin past that window, not the real backoff multiplier.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(INITIAL_BACKOFF_MS * 2);
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

  describe("repeated attempts that never reach onopen", () => {
    const latestSocket = () => MockWebSocket.instances[MockWebSocket.instances.length - 1];

    /** Closes the newest socket before it opens, then runs the auth check and the reconnect delay. */
    async function failLatestAttemptBeforeOpen() {
      const ws = latestSocket();
      await act(async () => {
        ws.onclose?.();
        await vi.advanceTimersByTimeAsync(MAX_BACKOFF_MS);
      });
    }

    beforeEach(() => {
      vi.useFakeTimers();
      mockedGetSystemStatus.mockResolvedValue(HEALTHY_SYSTEM_STATUS);
    });

    it("shows 'unreachable' only once the threshold of never-opened attempts is reached", async () => {
      renderWebSocketHook();

      for (let i = 1; i < UNREACHABLE_ATTEMPT_THRESHOLD; i++) {
        await failLatestAttemptBeforeOpen();
        expect(useAppStore.getState().connection).not.toBe("unreachable");
      }

      await failLatestAttemptBeforeOpen();
      expect(useAppStore.getState().connection).toBe("unreachable");
      // Still retrying, and the retry doesn't flash back to "Connecting...".
      expect(MockWebSocket.instances).toHaveLength(UNREACHABLE_ATTEMPT_THRESHOLD + 1);
      expect(useAppStore.getState().connection).toBe("unreachable");
    });

    it("leaves 'unreachable' once a later attempt connects", async () => {
      renderWebSocketHook();
      for (let i = 0; i < UNREACHABLE_ATTEMPT_THRESHOLD; i++) await failLatestAttemptBeforeOpen();

      simulateConnected(latestSocket());

      const { connection } = useAppStore.getState();
      expect(connection).toBe("connected");
    });

    it("switches from 'unreachable' to 'connecting' as soon as the transport opens", async () => {
      renderWebSocketHook();
      for (let i = 0; i < UNREACHABLE_ATTEMPT_THRESHOLD; i++) await failLatestAttemptBeforeOpen();
      expect(useAppStore.getState().connection).toBe("unreachable");

      act(() => {
        latestSocket().simulateOpen();
      });

      expect(useAppStore.getState().connection).toBe("connecting");
    });

    it("never shows 'unreachable' after a connection opened at least once", async () => {
      const { ws } = renderConnectedWebSocketHook();
      act(() => {
        ws.onclose?.();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(MAX_BACKOFF_MS);
      });

      for (let i = 0; i < UNREACHABLE_ATTEMPT_THRESHOLD * 2; i++) await failLatestAttemptBeforeOpen();

      expect(useAppStore.getState().connection).toBe("reconnecting");
    });

    it("never shows 'unreachable' after a transport-level open, even without a completed handshake", async () => {
      renderAndCloseAfterOpen();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(MAX_BACKOFF_MS);
      });

      for (let i = 0; i < UNREACHABLE_ATTEMPT_THRESHOLD * 2; i++) {
        await failLatestAttemptBeforeOpen();
        expect(useAppStore.getState().connection).not.toBe("unreachable");
      }
    });
  });

  describe("jitteredDelay", () => {
    it("stays within [base * (1 - JITTER_RATIO), base]", () => {
      expect(jitteredDelay(10_000, () => 0)).toBe(10_000);
      expect(jitteredDelay(10_000, () => 0.999_999)).toBeGreaterThanOrEqual(10_000 * (1 - JITTER_RATIO));
      expect(jitteredDelay(10_000, () => 0.5)).toBe(10_000 * (1 - JITTER_RATIO / 2));
    });

    it("spreads reconnects from simultaneous disconnects across the jitter window", () => {
      vi.useFakeTimers();
      vi.spyOn(Math, "random").mockReturnValue(0.999);
      renderAndCloseAfterOpen();

      // A full-length wait would land at INITIAL_BACKOFF_MS; the jittered one fires well before it.
      act(() => {
        vi.advanceTimersByTime(INITIAL_BACKOFF_MS * (1 - JITTER_RATIO) + 1);
      });
      expect(MockWebSocket.instances).toHaveLength(2);
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
      vi.advanceTimersByTime(HANDSHAKE_TIMEOUT_MS);
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
      vi.advanceTimersByTime(HANDSHAKE_TIMEOUT_MS);
    });
    expect(useAppStore.getState().connection).toBe("connected");
  });

  it("sends log subscribe on connect", () => {
    const { ws } = renderConnectedWebSocketHook();

    const subscribeMessages = ws.sent.map((s) => JSON.parse(s));
    expect(subscribeMessages).toHaveLength(1);
    expect(subscribeMessages[0]).toEqual({
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
    const subscribeMessages = ws2.sent.map((s) => JSON.parse(s));
    expect(subscribeMessages).toHaveLength(1);
    expect(subscribeMessages[0]).toEqual({
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

    const messages = ws.sent.map((s) => JSON.parse(s));
    expect(messages).toHaveLength(1);
    expect(messages[0]).toEqual({
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
          status: "running",
          previous_status: "starting",
          exception: null,
          exception_type: null,
          exception_traceback: null,
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

  it("maps app_status_changed needs_restart into appStatus state", () => {
    const { ws } = renderConnectedWebSocketHook();
    const flag = { reason: "1 task still pending", pending_tasks: ["MyApp.poll"], flagged_at: 1000 };

    act(() => {
      ws.simulateMessage({
        type: "app_status_changed",
        data: {
          app_key: "my_app",
          index: 0,
          status: "failed",
          previous_status: "stopping",
          instance_name: "MyApp[0]",
          class_name: "MyApp",
          exception: null,
          exception_type: null,
          exception_traceback: null,
          needs_restart: flag,
        },
        timestamp: 1000,
      });
    });

    expect(useAppStore.getState().appStatus["my_app:0"]?.needs_restart).toEqual(flag);
  });

  it("defaults ready to false and ready_phase to null for pre-schema events", () => {
    const { ws } = renderConnectedWebSocketHook();

    act(() => {
      ws.simulateMessage({
        type: "service_status",
        data: {
          resource_name: "OldService",
          status: "running",
          previous_status: null,
          exception: null,
          exception_type: null,
          exception_traceback: null,
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
          status: "running",
          previous_status: null,
          exception: null,
          exception_type: null,
          exception_traceback: null,
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

  it("increments logHintVersion on log_hint message", () => {
    const { ws } = renderConnectedWebSocketHook();
    const versionBefore = useAppStore.getState().logHintVersion;

    act(() => {
      ws.simulateMessage({ type: "log_hint", timestamp: 1000 });
    });

    expectLogHintVersionIncrementedBy(versionBefore);
  });

  it("increments logHintVersion once per log_hint message received", () => {
    const { ws } = renderConnectedWebSocketHook();
    const versionBefore = useAppStore.getState().logHintVersion;

    act(() => {
      ws.simulateMessage({ type: "log_hint", timestamp: 1000 });
      ws.simulateMessage({ type: "log_hint", timestamp: 1001 });
      ws.simulateMessage({ type: "log_hint", timestamp: 1002 });
    });

    expect(useAppStore.getState().logHintVersion).toBe(versionBefore + 3);
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
    // Spy installed after first connect — this test only observes the reconnect event; the
    // "not called on first connect" invariant has its own dedicated test below, with the spy
    // installed before render so it's actually live for the event it checks.
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    reconnectWebSocket(ws1);

    // On reconnect, invalidateQueries should have been called with no filter
    expect(invalidateSpy).toHaveBeenCalledOnce();
    expect(invalidateSpy).toHaveBeenCalledWith();
  });

  it("does not call queryClient.invalidateQueries() on first connect", () => {
    // Render and spy BEFORE connecting (not renderConnectedWebSocketHook, which would connect
    // before the spy exists) — the spy must be live for the very event it's checking.
    const { queryClient, ws } = renderWebSocketHook();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    simulateConnected(ws, { uptime_seconds: 100 });

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("invalidates every manifest-backed query on apps_changed", () => {
    const { ws, queryClient } = renderConnectedWebSocketHook();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    act(() => {
      ws.simulateMessage({ type: "apps_changed", data: {}, timestamp: 1000 });
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["manifests"] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["manifest"] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["app-grid"] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["system-status"] });
  });

  it.each([true, false])("invalidates the system-status query on connectivity (connected=%s)", (connected) => {
    const { ws, queryClient } = renderConnectedWebSocketHook();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    act(() => {
      ws.simulateMessage({ type: "connectivity", data: { connected }, timestamp: 1000 });
    });

    expect(invalidateSpy).toHaveBeenCalledOnce();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["system-status"] });
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
