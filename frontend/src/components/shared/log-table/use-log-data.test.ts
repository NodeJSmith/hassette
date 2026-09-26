import { act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LogEntry } from "@/api/endpoints";
import { queryKeys } from "@/lib/query-keys";
import { type TimePreset, useAppStore } from "@/state/store";
import { createLogEntry } from "@/test/factories";
import { renderLoaded, renderLoadedLogData } from "@/test/log-data-test-utils";
import { createTestQueryClient, renderHookWithProviders } from "@/test/query-test-utils";
import { server } from "@/test/server";

import { CATCH_UP_FETCH_LIMIT, MAX_CACHED_LOG_ENTRIES, REST_FETCH_LIMIT } from "./constants";
import { useLogData } from "./use-log-data";

const LOGS_ENDPOINT = "/api/logs/recent";
const LOGS_SINCE_ENDPOINT = "/api/logs/since/:sinceId";

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}));

// Import after mock so the spy reference is captured.
const { toast } = await import("sonner");

function seedState(preset: TimePreset = "1h"): void {
  useAppStore.setState({
    timePreset: preset,
    uptimeSeconds: preset === "since-restart" ? 100 : null,
  });
}

async function waitForLoaded(result: { current: { loading: boolean } }): Promise<void> {
  await vi.waitFor(() => {
    expect(result.current.loading).toBe(false);
  });
}

/** Bumps the store's `log_hint` counter inside `act()` — the trigger `use-log-data.ts` debounces
 * on. */
function sendHint(): void {
  act(() => {
    useAppStore.getState().incrementLogHint();
  });
}

/** Builds `count` log entries with sequential ids starting at `startId`, so tests exercise the
 * `id`-based cursor without hand-writing each entry. */
function makeEntries(count: number, startId: number): LogEntry[] {
  return Array.from({ length: count }, (_, i) =>
    createLogEntry({ id: startId + i, seq: startId + i, timestamp: 1000 + startId + i, message: `msg-${startId + i}` }),
  );
}

beforeEach(() => {
  vi.mocked(toast.error).mockClear();
});

describe("useLogData", () => {
  describe("loading state", () => {
    it("is true initially before REST resolves", () => {
      seedState();
      // Override with a never-resolving handler to freeze the fetch in-flight.
      server.use(http.get(LOGS_ENDPOINT, () => new Promise(() => {})));

      const { result } = renderHookWithProviders(() => useLogData({}));

      expect(result.current.loading).toBe(true);
    });

    it("becomes false after REST resolves", async () => {
      seedState();

      await renderLoaded();
    });
  });

  describe("REST fetch", () => {
    it("calls the /api/logs/recent endpoint with appKey, executionId, and limit", async () => {
      seedState();
      let capturedUrl: string | undefined;

      server.use(
        http.get(LOGS_ENDPOINT, ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json([]);
        }),
      );

      await renderLoaded({ appKey: "my_app", executionId: "exec-42" });

      expect(capturedUrl).toBeDefined();
      const url = new URL(capturedUrl!);
      expect(url.searchParams.get("app_key")).toBe("my_app");
      expect(url.searchParams.get("execution_id")).toBe("exec-42");
      expect(url.searchParams.get("limit")).toBe(String(REST_FETCH_LIMIT));
    });

    it("populates restEntries and allEntries with the fetched entries", async () => {
      seedState();
      const entries = makeEntries(2, 1);

      const result = await renderLoadedLogData(entries);

      expect(result.current.restEntries).toHaveLength(2);
      expect(result.current.allEntries).toHaveLength(2);
      // Order isn't the raw fetch-response order — the base query now merges through
      // mergeCatchUpBatch (id-descending), matching real /logs/recent's own latest-N-DESC shape.
      expect(result.current.restEntries.map((e) => e.message).sort()).toEqual(entries.map((e) => e.message).sort());
    });
  });

  describe("time-window filtering", () => {
    it("passes the since parameter to the REST fetch", async () => {
      seedState("1h");
      let capturedUrl: string | undefined;

      server.use(
        http.get(LOGS_ENDPOINT, ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json([]);
        }),
      );

      await renderLoaded();

      expect(capturedUrl).toBeDefined();
      const url = new URL(capturedUrl!);
      const since = Number(url.searchParams.get("since"));
      expect(since).toBeGreaterThan(0);
      // 1h preset: since should be within ~1h of now
      const nowSeconds = Date.now() / 1000;
      expect(since).toBeGreaterThan(nowSeconds - 3700);
      expect(since).toBeLessThan(nowSeconds);
    });

    it("refetches when the time preset changes", async () => {
      seedState("1h");
      let fetchCount = 0;

      server.use(
        http.get(LOGS_ENDPOINT, () => {
          fetchCount++;
          return HttpResponse.json([]);
        }),
      );

      await renderLoaded();
      const firstFetchCount = fetchCount;

      await act(() => {
        useAppStore.setState({ timePreset: "24h" });
      });

      await vi.waitFor(() => {
        expect(fetchCount).toBeGreaterThan(firstFetchCount);
      });
    });

    it("gates fetching until uptimeSeconds is available for since-restart", async () => {
      // Default: since-restart with null uptime → should not fetch

      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json([])));

      const { result } = renderHookWithProviders(() => useLogData({}));

      // Should stay in loading state because fetching is disabled
      expect(result.current.loading).toBe(true);

      // Provide uptime → unblocks fetch
      await act(() => {
        useAppStore.setState({ uptimeSeconds: 60 });
      });

      await waitForLoaded(result);
    });
  });

  describe("error handling", () => {
    it("shows a toast error and sets loading to false when the REST fetch rejects", async () => {
      seedState();

      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.error()));

      const result = await renderLoaded();

      expect(toast.error).toHaveBeenCalledTimes(1);
      expect(result.current.restEntries).toHaveLength(0);
    });
  });

  describe("hint-triggered catch-up", () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("fetches from /logs/since after a debounced log_hint, preserving appKey/executionId/since", async () => {
      seedState("1h");
      const rest = makeEntries(1, 1);
      let capturedUrl: string | undefined;
      let capturedSinceId: string | undefined;

      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(rest)));
      const result = await renderLoadedLogData(rest, { appKey: "my_app", executionId: "exec-1" });

      const newEntry = makeEntries(1, 2)[0];
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, ({ request, params }) => {
          capturedUrl = request.url;
          capturedSinceId = params["sinceId"] as string;
          return HttpResponse.json([newEntry]);
        }),
      );

      sendHint();
      await vi.advanceTimersByTimeAsync(200);
      await vi.waitFor(() => {
        expect(result.current.allEntries.map((e) => e.id)).toContain(newEntry.id);
      });

      expect(capturedSinceId).toBe("1");
      const url = new URL(capturedUrl!);
      expect(url.searchParams.get("app_key")).toBe("my_app");
      expect(url.searchParams.get("execution_id")).toBe("exec-1");
      expect(Number(url.searchParams.get("since"))).toBeGreaterThan(0);
    });

    it("coalesces 10+ hints within the debounce window into a single fetch", async () => {
      seedState();
      let fetchCount = 0;
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => {
          fetchCount++;
          return HttpResponse.json([]);
        }),
      );

      const result = await renderLoadedLogData(makeEntries(1, 1));

      for (let i = 0; i < 12; i++) {
        sendHint();
        await vi.advanceTimersByTimeAsync(10); // 12 hints across ~120ms — well within the 200ms debounce
      }
      await vi.advanceTimersByTimeAsync(200);

      await vi.waitFor(() => {
        expect(fetchCount).toBe(1);
      });
      void result;
    });

    it("fires a catch-up fetch at least every maxWait window under sustained hints", async () => {
      seedState();
      let fetchCount = 0;
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => {
          fetchCount++;
          return HttpResponse.json([]);
        }),
      );

      await renderLoadedLogData(makeEntries(1, 1));

      // Sustained hints every 100ms (< 200ms debounce, so debounce alone never fires) for 1000ms.
      for (let i = 0; i < 10; i++) {
        sendHint();
        await vi.advanceTimersByTimeAsync(100);
      }

      // maxWait (500ms) must have forced at least one fetch despite the continuous debounce reset.
      await vi.waitFor(() => {
        expect(fetchCount).toBeGreaterThanOrEqual(1);
      });
    });

    it("merges fetched records into allEntries, deduped by rowKey", async () => {
      seedState();
      const rest = makeEntries(1, 1);
      const result = await renderLoadedLogData(rest);

      const duplicate = { ...rest[0] }; // same id/seq/timestamp → same rowKey
      const fresh = makeEntries(1, 2)[0];
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json([duplicate, fresh])));

      sendHint();
      await vi.advanceTimersByTimeAsync(200);

      await vi.waitFor(() => {
        expect(result.current.allEntries).toHaveLength(2);
        expect(result.current.allEntries.map((e) => e.id).sort()).toEqual([1, 2]);
      });
    });

    it("resets the cursor and surfaces a notice when a fetch returns a max id below lastSeenId", async () => {
      seedState();
      const rest = makeEntries(1, 50);
      const result = await renderLoadedLogData(rest);

      // Simulates a DB reset: the batch's max id (3) is below the current cursor (50).
      const resetBatch = makeEntries(3, 1);
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json(resetBatch)));

      sendHint();
      await vi.advanceTimersByTimeAsync(200);

      await vi.waitFor(() => {
        expect(result.current.allEntries.map((e) => e.id).sort((a, b) => a - b)).toEqual([1, 2, 3]);
      });
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Log stream reset"));
    });

    it("chains catch-up fetches when a full page is returned, stopping at the 5-page cap", async () => {
      seedState();
      let fetchCount = 0;
      let nextId = 1;

      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => {
          fetchCount++;
          // Always return a full page so the catch-up loop keeps chaining.
          const page = makeEntries(CATCH_UP_FETCH_LIMIT, nextId);
          nextId += CATCH_UP_FETCH_LIMIT;
          return HttpResponse.json(page);
        }),
      );

      await renderLoadedLogData(makeEntries(1, 0));

      sendHint();
      // 5 pages x 100ms minimum inter-fetch delay, generous headroom for the fetches themselves.
      await vi.advanceTimersByTimeAsync(200 + 5 * 100 + 500);

      await vi.waitFor(() => {
        expect(fetchCount).toBe(5);
      });
    });

    it("backs off and reports an error when the catch-up fetch fails", async () => {
      seedState();
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.error()));

      await renderLoadedLogData(makeEntries(1, 1));

      sendHint();
      // debounce (200ms) + 3 retries at 1000/1500/2250ms backoff, generous headroom.
      await vi.advanceTimersByTimeAsync(200 + 1000 + 1500 + 2250 + 500);

      await vi.waitFor(() => {
        expect(toast.error).toHaveBeenCalled();
      });
    });

    it("does not retry a 4xx catch-up failure, and toasts only once per scopedKey across repeated hint episodes", async () => {
      seedState();
      let fetchCount = 0;
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => {
          fetchCount++;
          return HttpResponse.json({ detail: "limit too large" }, { status: 422 });
        }),
      );

      await renderLoadedLogData(makeEntries(1, 1));

      sendHint();
      // debounce (200ms) + a single fetch attempt, generous headroom — no backoff wait since a
      // 4xx fails immediately instead of retrying.
      await vi.advanceTimersByTimeAsync(200 + 500);

      await vi.waitFor(() => {
        expect(toast.error).toHaveBeenCalledTimes(1);
      });
      expect(fetchCount).toBe(1);

      vi.mocked(toast.error).mockClear();

      // A second hint-triggered episode still runs — the permanent-failure gate only suppresses
      // the toast, not the next episode's attempt.
      sendHint();
      await vi.advanceTimersByTimeAsync(200 + 500);

      await vi.waitFor(() => {
        expect(fetchCount).toBe(2);
      });
      expect(toast.error).not.toHaveBeenCalled();
    });

    it("serializes overlapping catch-up runs instead of racing them, so a slower response never triggers a false reset", async () => {
      seedState();
      const rest = makeEntries(1, 1); // cache starts at id=1
      const result = await renderLoadedLogData(rest);

      let callCount = 0;
      let releaseFirstCall: (() => void) | undefined;

      server.use(
        http.get(LOGS_SINCE_ENDPOINT, async () => {
          callCount++;
          if (callCount === 1) {
            // First run's fetch hangs here — simulates it still being in flight when a second hint
            // schedules another run. Resolves to id=2, a lower max id than what the second run's
            // response below will (correctly) advance the cache to.
            await new Promise<void>((resolve) => {
              releaseFirstCall = resolve;
            });
            return HttpResponse.json(makeEntries(1, 2));
          }
          // Second run only reaches this branch after the first has resolved and merged, so its
          // own sinceId reflects the post-merge cache — never a stale, lower cursor.
          return HttpResponse.json(makeEntries(1, 10));
        }),
      );

      // First hint: debounce fires at +200ms, starting the first (now-hanging) fetch.
      sendHint();
      await vi.advanceTimersByTimeAsync(200);
      await vi.waitFor(() => {
        expect(callCount).toBe(1);
      });

      // Second hint arrives while the first fetch is still in flight. Its own debounce/maxWait
      // cycle elapses, but the guard must defer performCatchUp until the first run settles —
      // proven by callCount staying at 1 even after this cycle's timers fire.
      sendHint();
      await vi.advanceTimersByTimeAsync(500);
      expect(callCount).toBe(1);

      // Release the first (hanging) response — only now should the second, chained run start.
      releaseFirstCall?.();
      await vi.waitFor(() => {
        expect(callCount).toBe(2);
      });

      await vi.waitFor(() => {
        expect(result.current.allEntries.map((e) => e.id).sort((a, b) => a - b)).toEqual([1, 2, 10]);
      });
      expect(toast.error).not.toHaveBeenCalledWith(expect.stringContaining("Log stream reset"));
    });

    it("caps the merged cache at MAX_CACHED_LOG_ENTRIES, dropping the oldest rows", async () => {
      seedState();
      const existingCount = MAX_CACHED_LOG_ENTRIES - 10;
      // `mergeCatchUpBatch` assumes id-DESC cache order (see its docstring); reverse so the seeded
      // base-query data matches that invariant instead of the ascending order `makeEntries` builds.
      const rest = makeEntries(existingCount, 1).reverse(); // ids existingCount..1, newest-first

      const result = await renderLoadedLogData(rest);
      expect(result.current.allEntries).toHaveLength(existingCount);

      const freshCount = 30; // pushes existing+fresh well past the cap
      const fresh = makeEntries(freshCount, existingCount + 1);
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json(fresh)));

      sendHint();
      await vi.advanceTimersByTimeAsync(200);

      await vi.waitFor(() => {
        expect(result.current.allEntries).toHaveLength(MAX_CACHED_LOG_ENTRIES);
      });

      const ids = result.current.allEntries.map((e) => e.id);
      const maxFreshId = existingCount + freshCount;
      expect(ids).toContain(maxFreshId); // newest rows survive
      expect(ids).not.toContain(1); // oldest rows are the ones trimmed
    });
  });

  describe("periodic re-sync", () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("fires a catch-up fetch on an interval even with no hint activity", async () => {
      seedState();
      let fetchCount = 0;
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => {
          fetchCount++;
          return HttpResponse.json([]);
        }),
      );

      await renderLoadedLogData(makeEntries(1, 1));

      expect(fetchCount).toBe(0);
      await vi.advanceTimersByTimeAsync(5000);

      await vi.waitFor(() => {
        expect(fetchCount).toBe(1);
      });
    });

    it("does not toast on a transient failure from the periodic poll", async () => {
      seedState();
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.error()));

      await renderLoadedLogData(makeEntries(1, 1));

      await vi.advanceTimersByTimeAsync(5000);
      // Let the poll's own retry/backoff cycle (1000/1500/2250ms) exhaust, generous headroom.
      await vi.advanceTimersByTimeAsync(1000 + 1500 + 2250 + 500);

      expect(toast.error).not.toHaveBeenCalled();
    });

    it("still toasts once on a permanent (4xx) failure discovered by the periodic poll", async () => {
      seedState();
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json({ detail: "limit too large" }, { status: 422 })),
      );

      await renderLoadedLogData(makeEntries(1, 1));

      await vi.advanceTimersByTimeAsync(5000 + 500);

      await vi.waitFor(() => {
        expect(toast.error).toHaveBeenCalledTimes(1);
      });
    });
  });

  describe("catch-up cancellation", () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("stops the catch-up chain's retries after unmount", async () => {
      seedState();
      let fetchCount = 0;
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(makeEntries(1, 1))));
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => {
          fetchCount++;
          return HttpResponse.error();
        }),
      );

      const { result, unmount } = renderHookWithProviders(() => useLogData({}));
      await vi.waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      sendHint();
      await vi.advanceTimersByTimeAsync(200); // debounce fires, first attempt starts and fails
      await vi.waitFor(() => {
        expect(fetchCount).toBe(1);
      });

      unmount();

      // Advance through the full 3-retry backoff window (1000/1500/2250ms) the chain would
      // otherwise have run through — no further attempts should occur.
      await vi.advanceTimersByTimeAsync(1000 + 1500 + 2250 + 500);
      expect(fetchCount).toBe(1);
    });

    it("stops the catch-up chain's retries after a filter change (new scopedKey)", async () => {
      seedState();
      let fetchCount = 0;
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(makeEntries(1, 1))));
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => {
          fetchCount++;
          return HttpResponse.error();
        }),
      );

      const { result, rerender } = renderHookWithProviders((props: { appKey?: string }) => useLogData(props), {
        initialProps: { appKey: "app-a" },
      });
      await vi.waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      sendHint();
      await vi.advanceTimersByTimeAsync(200); // debounce fires, first attempt starts and fails
      await vi.waitFor(() => {
        expect(fetchCount).toBe(1);
      });

      act(() => rerender({ appKey: "app-b" })); // scopedKey changes — old chain's signal aborts

      // Advance past the point the old chain's next retry (1000ms backoff) would have fired, but
      // stay well under PERIODIC_RESYNC_MS (5000ms) so the unrelated periodic-poll feature (which
      // now legitimately runs for the new app-b scopedKey) can't also increment fetchCount here.
      await vi.advanceTimersByTimeAsync(1000 + 500);
      expect(fetchCount).toBe(1);
    });
  });

  describe("base-query merge", () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("does not let a base-query refetch erase entries a catch-up already merged in", async () => {
      seedState();
      const queryClient = createTestQueryClient();
      let recentCallCount = 0;

      server.use(
        http.get(LOGS_ENDPOINT, () => {
          recentCallCount++;
          // Always returns only the original entry — simulates a base-query refetch (e.g. a WS
          // reconnect) that races a catch-up merge and doesn't know about the newer record yet.
          return HttpResponse.json(makeEntries(1, 1));
        }),
      );
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json(makeEntries(1, 2))));

      const { result } = renderHookWithProviders(() => useLogData({}), { queryClient });
      await vi.waitFor(() => {
        expect(result.current.loading).toBe(false);
      });
      expect(recentCallCount).toBe(1);

      sendHint();
      await vi.advanceTimersByTimeAsync(200);
      await vi.waitFor(() => {
        expect(result.current.allEntries.map((e) => e.id).sort((a, b) => a - b)).toEqual([1, 2]);
      });

      // Before Finding 8's fix, useQuery's default full-replace would wholesale-overwrite the
      // cache with this refetch's stale (single-entry) result, silently erasing id=2.
      await act(async () => {
        await queryClient.refetchQueries({ queryKey: queryKeys.recentLogs() });
      });

      expect(recentCallCount).toBe(2);
      expect(result.current.allEntries.map((e) => e.id).sort((a, b) => a - b)).toEqual([1, 2]);
    });
  });
});
