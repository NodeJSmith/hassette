import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAppStore } from "../state/store";
import { createWouterMock } from "../test/mock-wouter";

let mockLocation = "/";
const mockSetLocation = vi.fn();

vi.mock("wouter", () =>
  createWouterMock({
    useLocation: () => [mockLocation, mockSetLocation],
  }),
);

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
    mockedGetTelemetryStatus.mockResolvedValue({
      degraded: false,
      dropped_overflow: 0,
      dropped_exhausted: 0,
      dropped_shutdown: 0,
      error_handler_failures: 0,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("polls on mount and sets degraded false on success", async () => {
    renderHook(() => useTelemetryHealth());

    // Initial poll fires on mount
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });
    expect(useAppStore.getState().telemetryDegraded).toBe(false);
  });

  it("polls again after 30s interval", async () => {
    renderHook(() => useTelemetryHealth());

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

  it("does not set degraded on generic network error", async () => {
    mockedGetTelemetryStatus.mockRejectedValue(new Error("Network error"));

    renderHook(() => useTelemetryHealth());

    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });
    // Network errors keep degraded false — only HTTP 503 means DB is degraded
    expect(useAppStore.getState().telemetryDegraded).toBe(false);
  });

  it("sets degraded true on HTTP 503 (ApiError)", async () => {
    const { ApiError } = await import("../api/client");
    mockedGetTelemetryStatus.mockRejectedValue(new ApiError(503, "Service Unavailable"));

    renderHook(() => useTelemetryHealth());

    await vi.waitFor(() => {
      expect(useAppStore.getState().telemetryDegraded).toBe(true);
    });
  });

  it("sets degraded true when endpoint reports degradation", async () => {
    mockedGetTelemetryStatus.mockResolvedValue({
      degraded: true,
      dropped_overflow: 0,
      dropped_exhausted: 0,
      dropped_shutdown: 0,
      error_handler_failures: 0,
    });

    renderHook(() => useTelemetryHealth());

    await vi.waitFor(() => {
      expect(useAppStore.getState().telemetryDegraded).toBe(true);
    });
  });

  it("backs off on consecutive failures (30s -> 60s -> 120s cap)", async () => {
    mockedGetTelemetryStatus.mockRejectedValue(new Error("fail"));

    renderHook(() => useTelemetryHealth());

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
    // First call fails, second succeeds, third succeeds
    mockedGetTelemetryStatus
      .mockRejectedValueOnce(new Error("fail"))
      .mockResolvedValueOnce({
        degraded: false,
        dropped_overflow: 0,
        dropped_exhausted: 0,
        dropped_shutdown: 0,
        error_handler_failures: 0,
      })
      .mockResolvedValue({
        degraded: false,
        dropped_overflow: 0,
        dropped_exhausted: 0,
        dropped_shutdown: 0,
        error_handler_failures: 0,
      });

    renderHook(() => useTelemetryHealth());

    // Initial poll fails (network error — degraded stays false)
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });
    expect(useAppStore.getState().telemetryDegraded).toBe(false);

    // After failure, backoff is 60s — advance to trigger second poll
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(2);
    });
    expect(useAppStore.getState().telemetryDegraded).toBe(false);

    // After success, interval resets to 30s — advance 30s for third poll
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(3);
    });
  });

  it("resets backoff and polls immediately on navigation", async () => {
    // Fail initially to trigger backoff
    mockedGetTelemetryStatus.mockRejectedValueOnce(new Error("fail")).mockResolvedValue({
      degraded: false,
      dropped_overflow: 0,
      dropped_exhausted: 0,
      dropped_shutdown: 0,
      error_handler_failures: 0,
    });

    const { rerender } = renderHook(() => useTelemetryHealth());

    // Initial poll fails (network error — degraded stays false), backoff kicks in
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });
    expect(useAppStore.getState().telemetryDegraded).toBe(false);

    // Simulate navigation by changing mock location and re-rendering
    mockLocation = "/apps";
    rerender();

    // Navigation should trigger immediate poll and reset backoff
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(2);
    });
    expect(useAppStore.getState().telemetryDegraded).toBe(false);

    // After navigation reset, interval should be back to 30s (not 60s)
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(3);
    });
  });

  it("does not set degraded on AbortError (navigation cancellation)", async () => {
    mockedGetTelemetryStatus.mockRejectedValue(new DOMException("The operation was aborted", "AbortError"));

    renderHook(() => useTelemetryHealth());

    // Wait for the initial poll to complete
    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });

    // AbortError should NOT set degraded — it's a navigation cancellation, not a failure
    expect(useAppStore.getState().telemetryDegraded).toBe(false);
  });

  it("clears interval on unmount", async () => {
    const { unmount } = renderHook(() => useTelemetryHealth());

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

  it("propagates dropped_overflow, dropped_exhausted, dropped_shutdown to app state", async () => {
    mockedGetTelemetryStatus.mockResolvedValue({
      degraded: false,
      dropped_overflow: 5,
      dropped_exhausted: 3,
      dropped_shutdown: 1,
      error_handler_failures: 7,
    });

    renderHook(() => useTelemetryHealth());

    await vi.waitFor(() => {
      expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(1);
    });
    expect(useAppStore.getState().droppedOverflow).toBe(5);
    expect(useAppStore.getState().droppedExhausted).toBe(3);
    expect(useAppStore.getState().droppedShutdown).toBe(1);
    expect(useAppStore.getState().errorHandlerFailures).toBe(7);
  });
});
