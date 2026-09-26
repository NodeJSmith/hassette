import { act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LogEntry } from "@/api/endpoints";
import { queryKeys } from "@/lib/query-keys";
import { type TimePreset, useAppStore } from "@/state/store";
import { createLogEntry } from "@/test/factories";
import {
  renderLoaded,
  renderLoadedLogData,
  stubCountingEndpoint,
  stubCountingHandler,
  useFakeTimersForCatchUp,
} from "@/test/log-data-test-utils";
import { createTestQueryClient, renderHookWithProviders } from "@/test/query-test-utils";
import { server } from "@/test/server";

import { CATCH_UP_FETCH_LIMIT, MAX_CACHED_LOG_ENTRIES, REST_FETCH_LIMIT } from "./constants";
import {
  CATCH_UP_BACKOFF_MULTIPLIER,
  CATCH_UP_INITIAL_BACKOFF_MS,
  CATCH_UP_MAX_PAGES,
  CATCH_UP_MAX_RETRIES,
  CATCH_UP_MIN_DELAY_MS,
  HINT_DEBOUNCE_MS,
  HINT_MAX_WAIT_MS,
  PERIODIC_RESYNC_MS,
  useLogData,
} from "./use-log-data";

const LOGS_ENDPOINT = "/api/logs/recent";
const LOGS_SINCE_ENDPOINT = "/api/logs/since/:sinceId";

// The full span of retry delays fetchSinceWithBackoff waits through on consecutive failures,
// summed across CATCH_UP_MAX_RETRIES attempts of exponential backoff — derived from the source
// module's constants so a change to the retry count or backoff shape doesn't silently desync this
// from the real behavior.
const CATCH_UP_FULL_RETRY_WINDOW_MS = ((): number => {
  let delay = CATCH_UP_INITIAL_BACKOFF_MS;
  let total = 0;
  for (let i = 0; i < CATCH_UP_MAX_RETRIES; i++) {
    total += delay;
    delay *= CATCH_UP_BACKOFF_MULTIPLIER;
  }
  return total;
})();

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

/** Fires a hint, advances past the debounce window, and waits for `assertion` — the common
 * "trigger a hint-driven catch-up fetch, then wait for its effect" sequence every hint-triggered
 * test needs. */
async function triggerHintAndWaitFor(assertion: () => void): Promise<void> {
  sendHint();
  await vi.advanceTimersByTimeAsync(HINT_DEBOUNCE_MS);
  await vi.waitFor(assertion);
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

    it("populates allEntries with the fetched entries", async () => {
      seedState();
      const entries = makeEntries(2, 1);

      const result = await renderLoadedLogData(entries);

      expect(result.current.allEntries).toHaveLength(2);
      // Order isn't the raw fetch-response order — the base query now merges through
      // mergeCatchUpBatch (timestamp-descending), matching real /logs/recent's own latest-N-DESC shape.
      expect(result.current.allEntries.map((e) => e.message).sort()).toEqual(entries.map((e) => e.message).sort());
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
      const getFetchCount = stubCountingEndpoint(LOGS_ENDPOINT);

      await renderLoaded();
      const firstFetchCount = getFetchCount();

      await act(() => {
        useAppStore.setState({ timePreset: "24h" });
      });

      await vi.waitFor(() => {
        expect(getFetchCount()).toBeGreaterThan(firstFetchCount);
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
      expect(result.current.allEntries).toHaveLength(0);
    });
  });

  describe("hint-triggered catch-up", () => {
    useFakeTimersForCatchUp();

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

      await triggerHintAndWaitFor(() => {
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
      const getFetchCount = stubCountingEndpoint(LOGS_SINCE_ENDPOINT);

      await renderLoadedLogData(makeEntries(1, 1));

      for (let i = 0; i < 12; i++) {
        sendHint();
        await vi.advanceTimersByTimeAsync(10); // 12 hints across ~120ms — well within the debounce window
      }
      await vi.advanceTimersByTimeAsync(HINT_DEBOUNCE_MS);

      await vi.waitFor(() => {
        expect(getFetchCount()).toBe(1);
      });
    });

    it("fires a catch-up fetch at least every maxWait window under sustained hints", async () => {
      seedState();
      const getFetchCount = stubCountingEndpoint(LOGS_SINCE_ENDPOINT);

      await renderLoadedLogData(makeEntries(1, 1));

      // Sustained hints every 100ms (< 200ms debounce, so debounce alone never fires) for 1000ms.
      for (let i = 0; i < 10; i++) {
        sendHint();
        await vi.advanceTimersByTimeAsync(100);
      }

      // maxWait (500ms) must have forced at least one fetch despite the continuous debounce reset.
      await vi.waitFor(() => {
        expect(getFetchCount()).toBeGreaterThanOrEqual(1);
      });
    });

    it("merges fetched records into allEntries, deduped by rowKey", async () => {
      seedState();
      const rest = makeEntries(1, 1);
      const result = await renderLoadedLogData(rest);

      const duplicate = { ...rest[0] }; // same id/seq/timestamp → same rowKey
      const fresh = makeEntries(1, 2)[0];
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json([duplicate, fresh])));

      await triggerHintAndWaitFor(() => {
        expect(result.current.allEntries).toHaveLength(2);
        expect(result.current.allEntries.map((e) => e.id).sort()).toEqual([1, 2]);
      });
    });

    it("orders the merged cache by timestamp, not insertion (id) order, when the two diverge", async () => {
      seedState();
      // Simulates concurrent inserts / clock skew: id 1 has the later timestamp, id 2 the earlier
      // one — the opposite of makeEntries' usual id-and-timestamp-move-together shape.
      const rest = [
        createLogEntry({ id: 1, seq: 1, timestamp: 2000, message: "newer-by-timestamp" }),
        createLogEntry({ id: 2, seq: 2, timestamp: 1000, message: "older-by-timestamp" }),
      ];
      const result = await renderLoadedLogData(rest);

      // filterLogEntries' keepTimestampSourceOrder fast path (use-log-filters.ts) trusts this
      // array is already timestamp-DESC — id-DESC would put id 2 first instead.
      expect(result.current.allEntries.map((e) => e.message)).toEqual(["newer-by-timestamp", "older-by-timestamp"]);
    });

    it("resets the cursor and surfaces a notice when a fetch returns a max id below lastSeenId", async () => {
      seedState();
      const rest = makeEntries(1, 50);
      const result = await renderLoadedLogData(rest);

      // Simulates a DB reset: the batch's max id (3) is below the current cursor (50).
      const resetBatch = makeEntries(3, 1);
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json(resetBatch)));

      await triggerHintAndWaitFor(() => {
        expect(result.current.allEntries.map((e) => e.id).sort((a, b) => a - b)).toEqual([1, 2, 3]);
      });
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Log stream reset"));
    });

    it("detects a reset even when the catch-up fetch itself comes back empty, via a /logs/recent probe", async () => {
      seedState();
      const rest = makeEntries(1, 50);
      const result = await renderLoadedLogData(rest);

      // Simulates a DB reset where the fresh max id (3) is still below the stale cursor (50) —
      // /logs/since/50 can only ever return id > 50, so it comes back empty even though the DB
      // now holds fresh, lower-id records the probe must catch instead.
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json([])));
      const probeEntry = makeEntries(1, 3)[0];
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json([probeEntry])));

      await triggerHintAndWaitFor(() => {
        expect(result.current.allEntries.map((e) => e.id)).toEqual([3]);
      });
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Log stream reset"));
    });

    it("does not toast or change the cache when the reset probe finds nothing new", async () => {
      seedState();
      const rest = makeEntries(1, 50);
      const result = await renderLoadedLogData(rest);

      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json([])));
      // A genuinely quiet stream: the probe re-observes the same entry already cached.
      const getProbeCount = stubCountingEndpoint(LOGS_ENDPOINT, rest);

      await triggerHintAndWaitFor(() => {
        expect(getProbeCount()).toBe(1);
      });
      // dup-ignore-start: PMD CPD's matched span for this boilerplate "final assertions, close
      // this test, open the next" shape happens to run through this test's own toEqual/toast
      // assertions and into the next test's declaration line below — PMD ignores identifiers and
      // literals, so unrelated tests' closing/opening lines match trivially. The marker has to
      // cover the whole matched span (ending past the "it(" line) or the checker won't recognize
      // it as ignored; nothing here is meaningfully extractable across an it() boundary.
      expect(result.current.allEntries.map((e) => e.id)).toEqual([50]);
      expect(toast.error).not.toHaveBeenCalled();
    });

    it("chains catch-up fetches when a full page is returned, stopping at the 5-page cap", async () => {
      // dup-ignore-end (see dup-ignore-start above — the marker had to span into this line)
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
      // CATCH_UP_MAX_PAGES pages x the minimum inter-fetch delay, generous headroom for the fetches themselves.
      await vi.advanceTimersByTimeAsync(HINT_DEBOUNCE_MS + CATCH_UP_MAX_PAGES * CATCH_UP_MIN_DELAY_MS + 500);

      await vi.waitFor(() => {
        expect(fetchCount).toBe(CATCH_UP_MAX_PAGES);
      });
    });

    it("backs off and reports an error when the catch-up fetch fails", async () => {
      seedState();
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.error()));

      await renderLoadedLogData(makeEntries(1, 1));

      sendHint();
      // debounce + 3 retries at the initial/1.5x/2.25x backoff delays, generous headroom.
      await vi.advanceTimersByTimeAsync(HINT_DEBOUNCE_MS + CATCH_UP_FULL_RETRY_WINDOW_MS + 500);

      await vi.waitFor(() => {
        expect(toast.error).toHaveBeenCalled();
      });
    });

    it("does not retry a 4xx catch-up failure, and toasts only once per scopedKey across repeated hint episodes", async () => {
      seedState();
      const getFetchCount = stubCountingEndpoint(LOGS_SINCE_ENDPOINT, { detail: "limit too large" }, { status: 422 });

      await renderLoadedLogData(makeEntries(1, 1));

      sendHint();
      // debounce + a single fetch attempt, generous headroom — no backoff wait since a
      // 4xx fails immediately instead of retrying.
      await vi.advanceTimersByTimeAsync(HINT_DEBOUNCE_MS + 500);

      await vi.waitFor(() => {
        expect(toast.error).toHaveBeenCalledTimes(1);
      });
      expect(getFetchCount()).toBe(1);

      vi.mocked(toast.error).mockClear();

      // A second hint-triggered episode still runs — the permanent-failure gate only suppresses
      // the toast, not the next episode's attempt.
      sendHint();
      await vi.advanceTimersByTimeAsync(HINT_DEBOUNCE_MS + 500);

      // dup-ignore-start: PMD CPD's matched span for this boilerplate "final assertions, close
      // this test, open the next" shape happens to run through this test's own waitFor/toast
      // assertions and into the next test's declaration line below — PMD ignores identifiers and
      // literals, so unrelated tests' closing/opening lines match trivially. The marker has to
      // cover the whole matched span (ending past the "it(" line) or the checker won't recognize
      // it as ignored; nothing here is meaningfully extractable across an it() boundary.
      await vi.waitFor(() => {
        expect(getFetchCount()).toBe(2);
      });
      expect(toast.error).not.toHaveBeenCalled();
    });

    it("serializes overlapping catch-up runs instead of racing them, so a slower response never triggers a false reset", async () => {
      // dup-ignore-end (see dup-ignore-start above — the marker had to span into this line)
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

      // First hint: debounce fires, starting the first (now-hanging) fetch.
      await triggerHintAndWaitFor(() => {
        expect(callCount).toBe(1);
      });

      // Second hint arrives while the first fetch is still in flight. Its own debounce/maxWait
      // cycle elapses, but the guard must defer performCatchUp until the first run settles —
      // proven by callCount staying at 1 even after this cycle's timers fire.
      sendHint();
      await vi.advanceTimersByTimeAsync(HINT_MAX_WAIT_MS);
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
      // `mergeCatchUpBatch` re-sorts on every merge regardless of input order, but seed newest-first
      // anyway to match the cache's real steady-state shape.
      const rest = makeEntries(existingCount, 1).reverse(); // ids existingCount..1, newest-first

      const result = await renderLoadedLogData(rest);
      expect(result.current.allEntries).toHaveLength(existingCount);

      const freshCount = 30; // pushes existing+fresh well past the cap
      const fresh = makeEntries(freshCount, existingCount + 1);
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json(fresh)));

      await triggerHintAndWaitFor(() => {
        expect(result.current.allEntries).toHaveLength(MAX_CACHED_LOG_ENTRIES);
      });

      const ids = result.current.allEntries.map((e) => e.id);
      const maxFreshId = existingCount + freshCount;
      expect(ids).toContain(maxFreshId); // newest rows survive
      expect(ids).not.toContain(1); // oldest rows are the ones trimmed
    });
  });

  describe("periodic re-sync", () => {
    useFakeTimersForCatchUp();

    it("fires a catch-up fetch on an interval even with no hint activity", async () => {
      seedState();
      const getFetchCount = stubCountingEndpoint(LOGS_SINCE_ENDPOINT);

      await renderLoadedLogData(makeEntries(1, 1));

      expect(getFetchCount()).toBe(0);
      await vi.advanceTimersByTimeAsync(PERIODIC_RESYNC_MS);

      await vi.waitFor(() => {
        expect(getFetchCount()).toBe(1);
      });
    });

    it("does not toast on a transient failure from the periodic poll", async () => {
      seedState();
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.error()));

      await renderLoadedLogData(makeEntries(1, 1));

      await vi.advanceTimersByTimeAsync(PERIODIC_RESYNC_MS);
      // dup-ignore-start: PMD CPD's matched span for this boilerplate "final assertions, close
      // this test, open the next" shape happens to run through this test's own advanceTimers/toast
      // assertions and into the next test's declaration line below — PMD ignores identifiers and
      // literals, so unrelated tests' closing/opening lines match trivially. The marker has to
      // cover the whole matched span (ending past the "it(" line) or the checker won't recognize
      // it as ignored; nothing here is meaningfully extractable across an it() boundary.
      // Let the poll's own retry/backoff cycle exhaust, generous headroom.
      await vi.advanceTimersByTimeAsync(CATCH_UP_FULL_RETRY_WINDOW_MS + 500);

      expect(toast.error).not.toHaveBeenCalled();
    });

    it("still toasts once on a permanent (4xx) failure discovered by the periodic poll", async () => {
      // dup-ignore-end (see dup-ignore-start above — the marker had to span into this line)
      seedState();
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json({ detail: "limit too large" }, { status: 422 })),
      );

      await renderLoadedLogData(makeEntries(1, 1));

      await vi.advanceTimersByTimeAsync(PERIODIC_RESYNC_MS + 500);

      await vi.waitFor(() => {
        expect(toast.error).toHaveBeenCalledTimes(1);
      });
    });
  });

  describe("catch-up cancellation", () => {
    useFakeTimersForCatchUp();

    it("stops the catch-up chain's retries after unmount", async () => {
      seedState();
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(makeEntries(1, 1))));
      const getFetchCount = stubCountingHandler(LOGS_SINCE_ENDPOINT, () => HttpResponse.error());

      const { result, unmount } = renderHookWithProviders(() => useLogData({}));
      await vi.waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      // debounce fires, first attempt starts and fails
      await triggerHintAndWaitFor(() => {
        expect(getFetchCount()).toBe(1);
      });

      unmount();

      // Advance through the full 3-retry backoff window the chain would otherwise have run
      // through — no further attempts should occur.
      await vi.advanceTimersByTimeAsync(CATCH_UP_FULL_RETRY_WINDOW_MS + 500);
      expect(getFetchCount()).toBe(1);
    });

    it("stops the catch-up chain's retries after a filter change (new scopedKey)", async () => {
      seedState();
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(makeEntries(1, 1))));
      const getFetchCount = stubCountingHandler(LOGS_SINCE_ENDPOINT, () => HttpResponse.error());

      const { result, rerender } = renderHookWithProviders((props: { appKey?: string }) => useLogData(props), {
        initialProps: { appKey: "app-a" },
      });
      await vi.waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      // debounce fires, first attempt starts and fails
      await triggerHintAndWaitFor(() => {
        expect(getFetchCount()).toBe(1);
      });

      act(() => rerender({ appKey: "app-b" })); // scopedKey changes — old chain's signal aborts

      // Advance past the point the old chain's next retry (the initial backoff delay) would have
      // fired, but stay well under PERIODIC_RESYNC_MS so the unrelated periodic-poll feature (which
      // now legitimately runs for the new app-b scopedKey) can't also increment fetchCount here.
      await vi.advanceTimersByTimeAsync(CATCH_UP_INITIAL_BACKOFF_MS + 500);
      expect(getFetchCount()).toBe(1);
    });
  });

  describe("base-query merge", () => {
    useFakeTimersForCatchUp();

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

      await triggerHintAndWaitFor(() => {
        expect(result.current.allEntries.map((e) => e.id).sort((a, b) => a - b)).toEqual([1, 2]);
      });

      // A base-query refetch must merge into the existing cache rather than wholesale-replacing
      // it — otherwise this stale (single-entry) refetch result would silently erase id=2.
      await act(async () => {
        await queryClient.refetchQueries({ queryKey: queryKeys.recentLogs() });
      });

      expect(recentCallCount).toBe(2);
      expect(result.current.allEntries.map((e) => e.id).sort((a, b) => a - b)).toEqual([1, 2]);
    });
  });
});
