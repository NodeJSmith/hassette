import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/preact";
import { createAppState } from "../state/create-app-state";

// Track the mock location and its setter so tests can simulate navigation
let mockLocation = "/";
const mockSetLocation = vi.fn();

vi.mock("wouter", () => ({
  useLocation: () => [mockLocation, mockSetLocation],
}));

vi.mock("../api/endpoints", () => ({
  getTelemetryStatus: vi.fn(),
}));

import { getTelemetryStatus } from "../api/endpoints";
import { useTelemetryHealth } from "./use-telemetry-health";

const mockedGetTelemetryStatus = vi.mocked(getTelemetryStatus);

describe("useTelemetryHealth", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockLocation = "/";
    mockedGetTelemetryStatus.mockReset();
    mockedGetTelemetryStatus.mockResolvedValue({ degraded: false });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("polls on mount and sets degraded false on success", async () => {
    const state = createAppState();
    renderHook(() => useTelemetryHealth(state));

    // Initial poll fires on mount
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });
    expect(state.telemetryDegraded.value).toBe(false);
  });

  it("polls again after 30s interval", async () => {
    const state = createAppState();
    renderHook(() => useTelemetryHealth(state));

    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });

    // Advance 30s to trigger next poll
    act(() => {
      vi.advanceTimersByTime(30_000);
    });

    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(2);
    });
  });

  it("sets degraded true on fetch failure", async () => {
    const state = createAppState();
    mockedGetTelemetryStatus.mockRejectedValue(new Error("Network error"));

    renderHook(() => useTelemetryHealth(state));

    await vi.waitFor(() => {
      expect(state.telemetryDegraded.value).toBe(true);
    });
  });

  it("sets degraded true when endpoint reports degradation", async () => {
    const state = createAppState();
    mockedGetTelemetryStatus.mockResolvedValue({ degraded: true });

    renderHook(() => useTelemetryHealth(state));

    await vi.waitFor(() => {
      expect(state.telemetryDegraded.value).toBe(true);
    });
  });

  it("backs off on consecutive failures (30s -> 60s -> 120s cap)", async () => {
    const state = createAppState();
    mockedGetTelemetryStatus.mockRejectedValue(new Error("fail"));

    renderHook(() => useTelemetryHealth(state));

    // Initial poll (fires immediately)
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });

    // After first failure, interval doubles to 60s
    // Advancing 30s should NOT trigger another poll (old interval cleared)
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    // Give any pending promises a chance to resolve
    await vi.waitFor(() => {
      // Should still be 1 since the interval is now 60s, not 30s
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });

    // Advancing another 30s (total 60s from first failure) triggers second poll
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(2);
    });

    // After second failure, interval doubles to 120s
    // Advancing 60s should NOT trigger poll
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(2);
    });

    // Advancing another 60s (total 120s from second failure) triggers third poll
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(3);
    });
  });

  it("resets backoff to 30s on success after failures", async () => {
    const state = createAppState();
    // First call fails, second succeeds, third succeeds
    mockedGetTelemetryStatus
      .mockRejectedValueOnce(new Error("fail"))
      .mockResolvedValueOnce({ degraded: false })
      .mockResolvedValue({ degraded: false });

    renderHook(() => useTelemetryHealth(state));

    // Initial poll fails
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });
    expect(state.telemetryDegraded.value).toBe(true);

    // After failure, backoff is 60s — advance to trigger second poll
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(2);
    });
    expect(state.telemetryDegraded.value).toBe(false);

    // After success, interval resets to 30s — advance 30s for third poll
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(3);
    });
  });

  it("resets backoff and polls immediately on navigation", async () => {
    const state = createAppState();
    // Fail initially to trigger backoff
    mockedGetTelemetryStatus
      .mockRejectedValueOnce(new Error("fail"))
      .mockResolvedValue({ degraded: false });

    const { rerender } = renderHook(() => useTelemetryHealth(state));

    // Initial poll fails, backoff kicks in
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });
    expect(state.telemetryDegraded.value).toBe(true);

    // Simulate navigation by changing mock location and re-rendering
    mockLocation = "/apps";
    rerender();

    // Navigation should trigger immediate poll and reset backoff
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(2);
    });
    expect(state.telemetryDegraded.value).toBe(false);

    // After navigation reset, interval should be back to 30s (not 60s)
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(3);
    });
  });

  it("does not set degraded on AbortError (navigation cancellation)", async () => {
    const state = createAppState();
    mockedGetTelemetryStatus.mockRejectedValue(
      new DOMException("The operation was aborted", "AbortError"),
    );

    renderHook(() => useTelemetryHealth(state));

    // Wait for the initial poll to complete
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });

    // AbortError should NOT set degraded — it's a navigation cancellation, not a failure
    expect(state.telemetryDegraded.value).toBe(false);
  });

  it("clears interval on unmount", async () => {
    const state = createAppState();
    const { unmount } = renderHook(() => useTelemetryHealth(state));

    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });

    unmount();

    // Advance time — should NOT trigger another poll
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
  });
});
