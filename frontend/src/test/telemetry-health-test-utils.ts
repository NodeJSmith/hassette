/**
 * Test utilities for `useTelemetryHealth` hook tests.
 *
 * The hook is a `useQuery` poller, so these helpers render it through `query-test-utils.tsx`'s
 * `renderHookWithProviders` (a fresh, isolated QueryClient per render). The hook sets its own
 * `retry`/`retryDelay`, overriding that client's `retry: false` default, so backoff timelines
 * still run. Helpers that need to observe or wait on poll calls take the caller's
 * `vi.mocked(getTelemetryStatus)` as a parameter — the mock itself stays owned by the test file's
 * own `vi.mock("../api/endpoints", ...)` call, since that call (and the `mockReset()`/
 * `mockResolvedValue()` configuration per test) must live where the mock is declared. Waiting on
 * poll count itself is `query-test-utils.tsx`'s generic `waitForCallCount()` — import it directly
 * rather than re-declaring it here.
 */

import type { MockedFunction } from "vitest";
import { expect, vi } from "vitest";

import type { getTelemetryStatus } from "../api/endpoints";
import { useTelemetryHealth } from "../hooks/use-telemetry-health";
import { useAppStore } from "../state/store";
import { renderHookWithProviders, waitForCallCount } from "./query-test-utils";

type MockedGetTelemetryStatus = MockedFunction<typeof getTelemetryStatus>;

/** Renders `useTelemetryHealth` inside a QueryClientProvider, returning the `renderHook` result so tests needing
 * `rerender`/`unmount` can destructure it. Not imported directly by any test file; used only by
 * `renderAndWaitForFirstPoll` and `expectFirstPollDegraded` below. */
function renderTelemetryHealthHook() {
  return renderHookWithProviders(() => useTelemetryHealth());
}

/**
 * Renders the hook and waits for the initial mount-time poll to complete — the shared opening
 * most tests perform (after configuring their own mock behavior) before diverging into backoff
 * timelines, navigation, or unmount assertions.
 */
export async function renderAndWaitForFirstPoll(mockedGetTelemetryStatus: MockedGetTelemetryStatus) {
  const result = renderTelemetryHealthHook();
  await waitForCallCount(mockedGetTelemetryStatus, 1);
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
  await waitForCallCount(mockedGetTelemetryStatus, count);
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
