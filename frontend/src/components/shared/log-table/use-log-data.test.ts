import { act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LogEntry } from "@/api/endpoints";
import { type TimePreset, useAppStore } from "@/state/store";
import { createLogEntry } from "@/test/factories";
import { renderLoaded, stubCountingEndpoint, useFakeTimersForLogData } from "@/test/log-data-test-utils";
import { renderHookWithProviders } from "@/test/query-test-utils";
import { server } from "@/test/server";

import { REST_FETCH_LIMIT } from "./constants";
import { HINT_DEBOUNCE_MS, HINT_MAX_WAIT_MS, PERIODIC_RESYNC_MS, useLogData } from "./use-log-data";

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const LOGS_ENDPOINT = "/api/logs/recent";
/** Hint spacing for the sustained-burst tests. Must stay under `HINT_DEBOUNCE_MS` (so only the maxWait cap
 * fires) and divide `HINT_MAX_WAIT_MS` evenly (so a hint lands as each maxWait timer fires and re-arms it
 * immediately — otherwise refetches come every maxWait + spacing, and the derived minimum overcounts). */
const HINT_BURST_SPACING_MS = 100;
/** Design AC#5: hints sent every `COALESCE_HINT_SPACING_MS` across `COALESCE_BURST_WINDOW_MS` (10+ hints)
 * coalesce into one refetch. */
const COALESCE_BURST_WINDOW_MS = 100;
const COALESCE_HINT_SPACING_MS = 10;

function seedState(preset: TimePreset = "1h"): void {
  useAppStore.setState({
    timePreset: preset,
    uptimeSeconds: preset === "since-restart" ? 100 : null,
  });
}

/** Bumps the store's `log_hint` counter inside `act()` — the trigger `use-log-data.ts` debounces
 * on. */
function sendHint(): void {
  act(() => {
    useAppStore.getState().incrementLogHint();
  });
}

/** Fires a hint, advances past the debounce window, and waits for `assertion` — the common
 * "trigger a hint-driven refetch, then wait for its effect" sequence every hint test needs. */
async function triggerHintAndWaitFor(assertion: () => void): Promise<void> {
  sendHint();
  await vi.advanceTimersByTimeAsync(HINT_DEBOUNCE_MS);
  await vi.waitFor(assertion);
}

/** Sends one hint every `spacingMs` until the hints span at least `spanMs`, and returns the total time
 * advanced. N hints span only `(N - 1) * spacingMs`, hence the extra hint. */
async function sendHintBurst(spanMs: number, spacingMs: number): Promise<number> {
  const hints = Math.ceil(spanMs / spacingMs) + 1;
  for (let i = 0; i < hints; i++) {
    sendHint();
    await vi.advanceTimersByTimeAsync(spacingMs);
  }
  return hints * spacingMs;
}

/** A promise plus its own `resolve`, so a test can control exactly when a mocked fetch settles —
 * used to hold a `/logs/recent` response open while other hints fire around it. */
function createDeferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("useLogData", () => {
  useFakeTimersForLogData();

  beforeEach(() => {
    seedState();
    vi.mocked(toast.error).mockClear();
  });

  it("fetches /logs/recent with appKey, executionId, since, and limit forwarded", async () => {
    let capturedUrl: URL | undefined;
    server.use(
      http.get(LOGS_ENDPOINT, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json([]);
      }),
    );

    await renderLoaded({ appKey: "my_app", executionId: "exec-1" });

    expect(capturedUrl?.searchParams.get("app_key")).toBe("my_app");
    expect(capturedUrl?.searchParams.get("execution_id")).toBe("exec-1");
    expect(capturedUrl?.searchParams.get("limit")).toBe(String(REST_FETCH_LIMIT));
    expect(capturedUrl?.searchParams.has("since")).toBe(true);
  });

  it("refetches exactly once after the debounce window following a single hint", async () => {
    const getCount = stubCountingEndpoint(LOGS_ENDPOINT, []);

    const result = await renderLoaded();
    expect(getCount()).toBe(1);

    // dup-ignore-start: generic "await the async action, assert loading settled false" shape
    // coincidentally matches use-async-action.test.ts's unrelated hook — not real duplication.
    await triggerHintAndWaitFor(() => expect(getCount()).toBe(2));
    expect(result.current.loading).toBe(false);
  });

  it("coalesces 10+ hints within 100ms into exactly one refetch (design AC#5)", async () => {
    // dup-ignore-end
    const getCount = stubCountingEndpoint(LOGS_ENDPOINT, []);

    await renderLoaded();
    expect(getCount()).toBe(1);

    await sendHintBurst(COALESCE_BURST_WINDOW_MS, COALESCE_HINT_SPACING_MS);
    await vi.advanceTimersByTimeAsync(HINT_DEBOUNCE_MS);
    await vi.waitFor(() => expect(getCount()).toBe(2));

    // No further refetch trickles in once the burst has settled.
    await vi.advanceTimersByTimeAsync(HINT_MAX_WAIT_MS);
    expect(getCount()).toBe(2);
  });

  it("refetches at least every HINT_MAX_WAIT_MS under continuous hints", async () => {
    const getCount = stubCountingEndpoint(LOGS_ENDPOINT, []);

    await renderLoaded();
    expect(getCount()).toBe(1);

    // Each hint resets the debounce timer, so only the maxWait cap can force a refetch through —
    // at least once per full HINT_MAX_WAIT_MS elapsed during the burst.
    const elapsed = await sendHintBurst(2 * HINT_MAX_WAIT_MS, HINT_BURST_SPACING_MS);
    const minRefetches = Math.floor(elapsed / HINT_MAX_WAIT_MS);
    await vi.waitFor(() => expect(getCount()).toBeGreaterThanOrEqual(1 + minRefetches));
  });

  it("does not cancel a slow in-flight fetch under sustained hints (starvation regression)", async () => {
    const baseline = [createLogEntry({ id: 1, message: "baseline" })];
    const later = [createLogEntry({ id: 3, message: "later-response" })];
    const slow = createDeferred<LogEntry[]>();

    let callIndex = 0;
    server.use(
      http.get(LOGS_ENDPOINT, async () => {
        callIndex += 1;
        if (callIndex === 1) return HttpResponse.json(baseline);
        if (callIndex === 2) return HttpResponse.json(await slow.promise);
        return HttpResponse.json(later);
      }),
    );

    const result = await renderLoaded();
    expect(result.current.allEntries[0]?.message).toBe("baseline");
    expect(callIndex).toBe(1);

    // Trigger the second (slow) fetch — this is the one that must survive the burst below.
    sendHint();
    await vi.advanceTimersByTimeAsync(HINT_DEBOUNCE_MS);
    await vi.waitFor(() => expect(callIndex).toBe(2));

    // Hints spaced under HINT_DEBOUNCE_MS, so only the maxWait cap fires — and it must not cancel
    // in-flight call #2 (invalidateQueries' default cancelRefetch: true would starve it forever).
    await sendHintBurst(3 * HINT_MAX_WAIT_MS, HINT_BURST_SPACING_MS);
    // Flush the last hint's debounce timer so no stray fetch confounds the assertions below.
    await vi.advanceTimersByTimeAsync(HINT_DEBOUNCE_MS);
    expect(callIndex).toBe(2);

    // Now let the slow fetch settle.
    slow.resolve([createLogEntry({ id: 2, message: "slow-response" })]);
    await vi.waitFor(() => {
      expect(result.current.allEntries.some((e) => e.message === "slow-response")).toBe(true);
    });

    // The slow fetch was never cancelled and re-issued: no third call happened.
    expect(callIndex).toBe(2);
  });

  it("refetches every PERIODIC_RESYNC_MS with no hints", async () => {
    const getCount = stubCountingEndpoint(LOGS_ENDPOINT, []);

    await renderLoaded();
    expect(getCount()).toBe(1);

    await vi.advanceTimersByTimeAsync(PERIODIC_RESYNC_MS);
    await vi.waitFor(() => expect(getCount()).toBe(2));

    await vi.advanceTimersByTimeAsync(PERIODIC_RESYNC_MS);
    await vi.waitFor(() => expect(getCount()).toBe(3));
  });

  it("replaces the cache: a dropped row disappears and a changed row shows its new values", async () => {
    const first = [
      createLogEntry({ id: 1, message: "first" }),
      createLogEntry({ id: 2, message: "second", execution_kind: null }),
    ];
    const second = [createLogEntry({ id: 2, message: "second", execution_kind: "handler" })];

    let callIndex = 0;
    server.use(
      http.get(LOGS_ENDPOINT, () => {
        callIndex += 1;
        return HttpResponse.json(callIndex === 1 ? first : second);
      }),
    );

    const result = await renderLoaded();
    expect(result.current.allEntries.map((e) => e.id)).toEqual([1, 2]);

    await triggerHintAndWaitFor(() => expect(result.current.allEntries).toHaveLength(1));
    expect(result.current.allEntries[0].id).toBe(2);
    expect(result.current.allEntries[0].execution_kind).toBe("handler");
  });

  it("does not fetch while waiting for uptime on since-restart, even on a hint", async () => {
    seedState("since-restart");
    useAppStore.setState({ uptimeSeconds: null });
    const getCount = stubCountingEndpoint(LOGS_ENDPOINT, []);

    const { result } = renderHookWithProviders(() => useLogData({}));
    expect(result.current.loading).toBe(true);
    expect(getCount()).toBe(0);

    sendHint();
    await vi.advanceTimersByTimeAsync(HINT_MAX_WAIT_MS);
    expect(getCount()).toBe(0);
  });

  it("clears pending timers on unmount — no fetch fires afterward", async () => {
    const getCount = stubCountingEndpoint(LOGS_ENDPOINT, []);

    const { result, unmount } = renderHookWithProviders(() => useLogData({}));
    await vi.waitFor(() => expect(result.current.loading).toBe(false));
    expect(getCount()).toBe(1);

    sendHint();
    unmount();

    await vi.advanceTimersByTimeAsync(HINT_MAX_WAIT_MS + PERIODIC_RESYNC_MS);
    expect(getCount()).toBe(1);
  });

  it("toasts once per outage, not on every failed periodic refetch, and re-arms after recovery", async () => {
    let failing = true;
    server.use(
      http.get(LOGS_ENDPOINT, () =>
        failing ? HttpResponse.json({ detail: "db down" }, { status: 503 }) : HttpResponse.json([]),
      ),
    );

    await renderLoaded();
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));

    // Two more failed periodic ticks — same outage, no new toast.
    await vi.advanceTimersByTimeAsync(PERIODIC_RESYNC_MS * 2);
    expect(toast.error).toHaveBeenCalledTimes(1);

    // Recovery re-arms the toast; the next failure is a new outage and toasts again.
    failing = false;
    await vi.advanceTimersByTimeAsync(PERIODIC_RESYNC_MS);
    failing = true;
    await vi.advanceTimersByTimeAsync(PERIODIC_RESYNC_MS);
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledTimes(2));
  });
});
