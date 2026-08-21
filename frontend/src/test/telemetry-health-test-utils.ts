/**
 * Test utilities for `useTelemetryHealth` hook tests.
 *
 * The hook needs no `QueryClientProvider` — it only touches the Zustand app store and fetch via
 * `getTelemetryStatus` — so these helpers compose directly with `renderHook` rather than
 * `query-test-utils.tsx`'s Query-composing primitives (`renderHookWithProviders`,
 * `renderInvalidatorHook`). Helpers that need to observe or wait on poll calls take the caller's
 * `vi.mocked(getTelemetryStatus)` as a parameter — the mock itself stays owned by the test file's
 * own `vi.mock("../api/endpoints", ...)` call, since that call (and the `mockReset()`/
 * `mockResolvedValue()` configuration per test) must live where the mock is declared.
 */

import { renderHook } from "@testing-library/react";
import type { MockedFunction } from "vitest";
import { expect, vi } from "vitest";

import type { getTelemetryStatus } from "../api/endpoints";
import { useTelemetryHealth } from "../hooks/use-telemetry-health";
import { useAppStore } from "../state/store";

type MockedGetTelemetryStatus = MockedFunction<typeof getTelemetryStatus>;

/** Renders `useTelemetryHealth` directly, returning the `renderHook` result so tests needing
 * `rerender`/`unmount` can destructure it. Not imported directly by any test file; used only by
 * `renderAndWaitForFirstPoll` and `expectFirstPollDegraded` below. */
function renderTelemetryHealthHook() {
  return renderHook(() => useTelemetryHealth());
}

/**
 * Waits for the mocked `getTelemetryStatus` to have been called `count` times — the "next poll
 * landed" signal most tests wait on at least once.
 */
export async function waitForPollCount(mockedGetTelemetryStatus: MockedGetTelemetryStatus, count: number) {
  await vi.waitFor(() => {
    expect(mockedGetTelemetryStatus).toHaveBeenCalledTimes(count);
  });
}

/**
 * Renders the hook and waits for the initial mount-time poll to complete — the shared opening
 * most tests perform (after configuring their own mock behavior) before diverging into backoff
 * timelines, navigation, or unmount assertions.
 */
export async function renderAndWaitForFirstPoll(mockedGetTelemetryStatus: MockedGetTelemetryStatus) {
  const result = renderTelemetryHealthHook();
  await waitForPollCount(mockedGetTelemetryStatus, 1);
  return result;
}

/**
 * Renders, waits for the initial poll, and asserts the app store's degraded flag stayed false —
 * the shared assertion every "this failure mode should not flip degraded" test performs.
 */
export async function expectFirstPollNotDegraded(mockedGetTelemetryStatus: MockedGetTelemetryStatus) {
  const result = await renderAndWaitForFirstPoll(mockedGetTelemetryStatus);
  expect(useAppStore.getState().telemetryDegraded).toBe(false);
  return result;
}

/** Waits for the `count`th poll and asserts the app store's degraded flag is still false — the
 * shared "backoff/reset advanced the clock but degraded didn't flip" assertion. */
export async function expectPollNotDegraded(mockedGetTelemetryStatus: MockedGetTelemetryStatus, count: number) {
  await waitForPollCount(mockedGetTelemetryStatus, count);
  expect(useAppStore.getState().telemetryDegraded).toBe(false);
}

/**
 * Renders the hook and waits until the app store's degraded flag flips true — the shared
 * assertion every "this failure mode should flip degraded" test performs.
 */
export async function expectFirstPollDegraded() {
  renderTelemetryHealthHook();
  await vi.waitFor(() => {
    expect(useAppStore.getState().telemetryDegraded).toBe(true);
  });
}
