// dup-ignore-start: shared 5-line import prologue also present in use-scoped-query.test.ts and use-websocket.test.ts (T05/T02); import statements can't be extracted into a shared helper
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAppStore } from "../state/store";
import { createWouterMock } from "../test/mock-wouter";
// dup-ignore-end

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
import { advanceTime, useFakeTimersForEachTest, waitForCallCount } from "../test/query-test-utils";
import {
  expectFirstPollDegraded,
  expectFirstPollNotDegraded,
  expectPollNotDegraded,
  renderAndWaitForFirstPoll,
} from "../test/telemetry-health-test-utils";
import { BASE_INTERVAL_MS } from "./use-telemetry-health";

const mockedGetTelemetryStatus = vi.mocked(getTelemetryStatus);

const HEALTHY_TELEMETRY_STATUS = {
  degraded: false,
  dropped_overflow: 0,
  dropped_exhausted: 0,
  dropped_shutdown: 0,
  error_handler_failures: 0,
};

describe("useTelemetryHealth", () => {
  useFakeTimersForEachTest();

  beforeEach(() => {
    mockLocation = "/";
    mockedGetTelemetryStatus.mockReset();
    mockedGetTelemetryStatus.mockResolvedValue(HEALTHY_TELEMETRY_STATUS);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("polls on mount and sets degraded false on success", async () => {
    // Initial poll fires on mount
    await expectFirstPollNotDegraded(mockedGetTelemetryStatus);
  });

  it("polls again after 30s interval", async () => {
    await renderAndWaitForFirstPoll(mockedGetTelemetryStatus);

    // Advance 30s to trigger next poll
    advanceTime(BASE_INTERVAL_MS);

    await waitForCallCount(mockedGetTelemetryStatus, 2);
  });

  it("does not set degraded on generic network error", async () => {
    mockedGetTelemetryStatus.mockRejectedValue(new Error("Network error"));

    // Network errors keep degraded false — only HTTP 503 means DB is degraded
    await expectFirstPollNotDegraded(mockedGetTelemetryStatus);
  });

  it("sets degraded true on HTTP 503 (ApiError)", async () => {
    const { ApiError } = await import("../api/client");
    mockedGetTelemetryStatus.mockRejectedValue(new ApiError(503, "Service Unavailable"));

    await expectFirstPollDegraded();
  });

  it("sets degraded true when endpoint reports degradation", async () => {
    mockedGetTelemetryStatus.mockResolvedValue({ ...HEALTHY_TELEMETRY_STATUS, degraded: true });

    await expectFirstPollDegraded();
  });

  it("backs off on consecutive failures (30s -> 60s -> 120s cap)", async () => {
    mockedGetTelemetryStatus.mockRejectedValue(new Error("fail"));

    // Initial poll (fires immediately)
    await renderAndWaitForFirstPoll(mockedGetTelemetryStatus);

    // After first failure, interval doubles to 60s
    // Advancing 30s should NOT trigger another poll (old interval cleared)
    advanceTime(BASE_INTERVAL_MS);
    // Should still be 1 since the interval is now 60s, not 30s
    await waitForCallCount(mockedGetTelemetryStatus, 1);

    // Advancing another 30s (total 60s from first failure) triggers second poll
    advanceTime(BASE_INTERVAL_MS);
    await waitForCallCount(mockedGetTelemetryStatus, 2);

    // After second failure, interval doubles to 120s
    // Advancing 60s should NOT trigger poll
    advanceTime(60_000);
    // Should still be 2 since the interval is now 120s, not 60s
    await waitForCallCount(mockedGetTelemetryStatus, 2);

    // Advancing another 60s (total 120s from second failure) triggers third poll
    advanceTime(60_000);
    await waitForCallCount(mockedGetTelemetryStatus, 3);
  });

  it("resets backoff to 30s on success after failures", async () => {
    // First call fails, second succeeds, third succeeds
    mockedGetTelemetryStatus
      .mockRejectedValueOnce(new Error("fail"))
      .mockResolvedValueOnce(HEALTHY_TELEMETRY_STATUS)
      .mockResolvedValue(HEALTHY_TELEMETRY_STATUS);

    // Initial poll fails (network error — degraded stays false)
    await expectFirstPollNotDegraded(mockedGetTelemetryStatus);

    // After failure, backoff is 60s — advance to trigger second poll
    advanceTime(60_000);
    await expectPollNotDegraded(mockedGetTelemetryStatus, 2);

    // After success, interval resets to 30s — advance 30s for third poll
    advanceTime(BASE_INTERVAL_MS);
    await waitForCallCount(mockedGetTelemetryStatus, 3);
  });

  it("resets backoff and polls immediately on navigation", async () => {
    // Fail initially to trigger backoff
    mockedGetTelemetryStatus.mockRejectedValueOnce(new Error("fail")).mockResolvedValue(HEALTHY_TELEMETRY_STATUS);

    // Initial poll fails (network error — degraded stays false), backoff kicks in
    const { rerender } = await expectFirstPollNotDegraded(mockedGetTelemetryStatus);

    // Simulate navigation by changing mock location and re-rendering
    mockLocation = "/apps";
    rerender();

    // Navigation should trigger immediate poll and reset backoff
    await expectPollNotDegraded(mockedGetTelemetryStatus, 2);

    // After navigation reset, interval should be back to 30s (not 60s)
    advanceTime(BASE_INTERVAL_MS);
    await waitForCallCount(mockedGetTelemetryStatus, 3);
  });

  it("does not set degraded on AbortError (navigation cancellation)", async () => {
    mockedGetTelemetryStatus.mockRejectedValue(new DOMException("The operation was aborted", "AbortError"));

    // Wait for the initial poll to complete, and confirm AbortError did NOT set degraded —
    // it's a navigation cancellation, not a failure
    await expectFirstPollNotDegraded(mockedGetTelemetryStatus);
  });

  it("clears interval on unmount", async () => {
    const { unmount } = await renderAndWaitForFirstPoll(mockedGetTelemetryStatus);

    unmount();

    // Advance time — should NOT trigger another poll
    advanceTime(60_000);
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

    await renderAndWaitForFirstPoll(mockedGetTelemetryStatus);
    expect(useAppStore.getState().droppedOverflow).toBe(5);
    expect(useAppStore.getState().droppedExhausted).toBe(3);
    expect(useAppStore.getState().droppedShutdown).toBe(1);
    expect(useAppStore.getState().errorHandlerFailures).toBe(7);
  });
});
