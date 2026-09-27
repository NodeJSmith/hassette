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

import { CATCH_UP_FETCH_LIMIT, MAX_CACHED_LOG_ENTRIES, RESET_PROBE_LIMIT, REST_FETCH_LIMIT } from "./constants";
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

/** Establishes the tracked cursor at `cursorId` via the initial REST fetch, then stubs an empty
 * `/logs/since` page so a subsequent hint's catch-up fetch comes back empty and triggers
 * `probeForReset`'s `/logs/recent` probe. Shared "arrange" step for every reset-probe test below
 * — each test still stubs its own `/logs/recent` probe response afterward to exercise its
 * specific scenario. */
async function renderWithCursorAndEmptyCatchUp(cursorId: number) {
  const result = await renderLoadedLogData(makeEntries(1, cursorId));
  server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json([])));
  return result;
}

/** Renders `useLogData` with a rerenderable `appKey` prop (via `renderHookWithProviders`'s
 * `initialProps`) and waits for the initial load to finish. Shared "arrange" step for tests that
 * change `appKey` mid-test via the returned `rerender`. */
async function renderWithRerenderableAppKey(initialAppKey: string) {
  const rendered = renderHookWithProviders((props: { appKey?: string }) => useLogData(props), {
    initialProps: { appKey: initialAppKey },
  });
  await waitForLoaded(rendered.result);
  return rendered;
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
      // dup-ignore-start: PMD CPD's matched span for this boilerplate "stub a handler, then
      // triggerHintAndWaitFor on a single expect" shape recurs across nearly every hint-triggered
      // test in this file — see the other dup-ignore-start markers in this file for the sibling
      // case (closing assertions into the next test's declaration). PMD ignores identifiers and
      // literals, so unrelated tests' setup/trigger shape matches trivially; nothing here is
      // meaningfully extractable without hiding what each test actually stubs and asserts.
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
      // dup-ignore-end

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
      // Simulates a DB reset where the fresh max id (3) is still below the stale cursor (50) —
      // /logs/since/50 can only ever return id > 50, so it comes back empty even though the DB
      // now holds fresh, lower-id records the probe must catch instead.
      const result = await renderWithCursorAndEmptyCatchUp(50);
      const probeEntry = makeEntries(1, 3)[0];
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json([probeEntry])));

      await triggerHintAndWaitFor(() => {
        expect(result.current.allEntries.map((e) => e.id)).toEqual([3]);
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Log stream reset"));
      });
    });

    it("does not misfire a reset when the probe's single highest-timestamp row has a lower id than other rows in the same batch", async () => {
      seedState();
      const result = await renderWithCursorAndEmptyCatchUp(100);

      // /logs/recent orders by timestamp DESC, not id DESC — under concurrent inserts or clock
      // skew, the highest-timestamp row need not be the highest-id row. This batch simulates
      // exactly that: sent in timestamp-DESC order (as the real backend would), the first row
      // (id 97) has a lower id than three rows further down (particularly id 101). A single-row
      // probe (limit=1) would only ever see id 97 — below the cursor (100) — and misfire a false
      // reset; a batch large enough to include id 101 must not.
      const timestampOrderedBatch = [
        createLogEntry({ id: 97, seq: 97, timestamp: 5000, message: "highest-timestamp-lowest-id" }),
        createLogEntry({ id: 101, seq: 101, timestamp: 4000, message: "true-max-id" }),
        createLogEntry({ id: 100, seq: 100, timestamp: 3000, message: "row-100" }),
        createLogEntry({ id: 99, seq: 99, timestamp: 2000, message: "row-99" }),
        createLogEntry({ id: 98, seq: 98, timestamp: 1000, message: "row-98" }),
      ];
      let capturedLimit: string | null = null;
      // dup-ignore-start: same unavoidable "stub a handler, then triggerHintAndWaitFor" shape as
      // the marker above — see that comment for why this isn't meaningfully extractable.
      server.use(
        http.get(LOGS_ENDPOINT, ({ request }) => {
          const limit = Number(new URL(request.url).searchParams.get("limit") ?? "1");
          capturedLimit = new URL(request.url).searchParams.get("limit");
          return HttpResponse.json(timestampOrderedBatch.slice(0, limit));
        }),
      );

      await triggerHintAndWaitFor(() => {
        expect(result.current.allEntries.map((e) => e.message)).toContain("true-max-id");
        expect(toast.error).not.toHaveBeenCalledWith(expect.stringContaining("Log stream reset"));
      });
      // dup-ignore-end
      expect(Number(capturedLimit)).toBe(RESET_PROBE_LIMIT);
    });

    it("does not toast or change the cache when the reset probe finds nothing new", async () => {
      seedState();
      const result = await renderWithCursorAndEmptyCatchUp(50);
      // A genuinely quiet stream: the probe re-observes the same entry already cached.
      const getProbeCount = stubCountingEndpoint(LOGS_ENDPOINT, makeEntries(1, 50));

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

    it("detects a reset via the tracked cursor even when the probe's id still exceeds the trimmed display cache's max", async () => {
      seedState();
      const full = makeEntries(MAX_CACHED_LOG_ENTRIES, 1);
      const result = await renderLoadedLogData(full);
      expect(result.current.allEntries).toHaveLength(MAX_CACHED_LOG_ENTRIES);

      // Two rolled-back rows (high id, oldest timestamp) each merge and get immediately trimmed
      // out of the display cache — same mechanism as the single-row trimmed-cursor test above —
      // opening a gap between the tracked cursor (6002) and the display cache's own max id (6000).
      const rolledBackA = MAX_CACHED_LOG_ENTRIES + 1;
      const rolledBackB = MAX_CACHED_LOG_ENTRIES + 2;
      let sinceCallCount = 0;
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => {
          sinceCallCount++;
          if (sinceCallCount === 1)
            return HttpResponse.json(makeEntries(1, rolledBackA).map((e) => ({ ...e, timestamp: 1 })));
          if (sinceCallCount === 2)
            return HttpResponse.json(makeEntries(1, rolledBackB).map((e) => ({ ...e, timestamp: 1 })));
          return HttpResponse.json([]);
        }),
      );

      await triggerHintAndWaitFor(() => expect(sinceCallCount).toBe(1));
      await triggerHintAndWaitFor(() => expect(sinceCallCount).toBe(2));
      const idsAfterTrimming = result.current.allEntries.map((e) => e.id);
      expect(idsAfterTrimming).not.toContain(rolledBackA);
      expect(idsAfterTrimming).not.toContain(rolledBackB);

      // The probe's id (6001) lands strictly between the trimmed display max (6000) and the
      // tracked cursor (6002): comparing against the display cache's own max would miss this as
      // a reset (6001 >= 6000), but comparing against the cursor correctly catches it (6001 < 6002).
      const probeEntry = createLogEntry({ id: rolledBackA, seq: rolledBackA, timestamp: 5000, message: "post-reset" });
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json([])),
        http.get(LOGS_ENDPOINT, () => HttpResponse.json([probeEntry])),
      );

      await triggerHintAndWaitFor(() => {
        expect(result.current.allEntries.map((e) => e.id)).toEqual([rolledBackA]);
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Log stream reset"));
      });
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

    it("does not treat a stale, in-flight /logs/recent refetch as a database reset once catch-up has already advanced the cache", async () => {
      seedState();
      const queryClient = createTestQueryClient();

      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(makeEntries(1, 1))));
      const { result } = renderHookWithProviders(() => useLogData({}), { queryClient });
      await vi.waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      // Simulates a WS-reconnect-triggered invalidateQueries(): a refetch of the same base query
      // starts now but hangs — its (stale) response is released manually below, after catch-up.
      let releaseRefetch: ((entries: LogEntry[]) => void) | undefined;
      server.use(
        http.get(
          LOGS_ENDPOINT,
          () =>
            new Promise<Response>((resolve) => {
              releaseRefetch = (entries) => resolve(HttpResponse.json(entries));
            }),
        ),
      );
      act(() => {
        void queryClient.invalidateQueries();
      });
      await vi.waitFor(() => {
        expect(releaseRefetch).toBeDefined();
      });

      // Catch-up runs and completes first, advancing the cache to id=2.
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json(makeEntries(1, 2))));
      await triggerHintAndWaitFor(() => {
        expect(result.current.allEntries.map((e) => e.id).sort((a, b) => a - b)).toEqual([1, 2]);
      });

      // The stale refetch finally resolves with its own, now-outdated snapshot (still just id=1).
      await act(async () => {
        releaseRefetch?.(makeEntries(1, 1));
      });

      await vi.waitFor(() => {
        // A real bug here would wipe the cache back down to just [1] and toast a reset.
        expect(result.current.allEntries.map((e) => e.id).sort((a, b) => a - b)).toEqual([1, 2]);
      });
      expect(toast.error).not.toHaveBeenCalledWith(expect.stringContaining("Log stream reset"));
    });

    it("advances the catch-up cursor past a high-id, old-timestamp row even after it's trimmed out of the display cache", async () => {
      seedState();
      // Fill the cache to exactly the cap with ordinary entries (id and timestamp both increasing).
      const full = makeEntries(MAX_CACHED_LOG_ENTRIES, 1);
      const result = await renderLoadedLogData(full);
      expect(result.current.allEntries).toHaveLength(MAX_CACHED_LOG_ENTRIES);

      // Simulates a clock rollback: the highest id ever seen, but an older timestamp than
      // everything already cached — sorts to the bottom on merge and is immediately trimmed.
      const rolledBackId = MAX_CACHED_LOG_ENTRIES + 1;
      const staleTimestampRow = [
        createLogEntry({ id: rolledBackId, seq: rolledBackId, timestamp: 1, message: "rolled-back" }),
      ];
      const capturedSinceIds: string[] = [];
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, ({ params }) => {
          capturedSinceIds.push(params["sinceId"] as string);
          return HttpResponse.json(capturedSinceIds.length === 1 ? staleTimestampRow : []);
        }),
      );

      await triggerHintAndWaitFor(() => {
        expect(capturedSinceIds).toHaveLength(1);
      });
      // Confirms the setup: the row really was trimmed out of the display cache.
      expect(result.current.allEntries.map((e) => e.id)).not.toContain(rolledBackId);

      // A second catch-up episode must request from the row's own id, not re-request the same
      // (now permanently stale) range forever.
      await triggerHintAndWaitFor(() => {
        expect(capturedSinceIds).toHaveLength(2);
      });
      expect(capturedSinceIds[1]).toBe(String(rolledBackId));
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

      const { rerender } = await renderWithRerenderableAppKey("app-a");

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

    it("aborts a queued catch-up run instead of executing it against a scope that already changed", async () => {
      seedState();
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(makeEntries(1, 1))));

      let sinceCallCountA = 0;
      let releaseFirstCall: (() => void) | undefined;
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, async ({ request }) => {
          if (new URL(request.url).searchParams.get("app_key") !== "app-a") return HttpResponse.json([]);
          sinceCallCountA++;
          if (sinceCallCountA === 1) {
            // First app-a run's fetch hangs — simulates it still being in flight when a second
            // hint schedules another run, queued behind it in catchUpChainRef, before scope
            // changes. `context` and `signal` must be captured together at that schedule time
            // (still app-a) for the queued run to correctly abort once app-a's controller is
            // cancelled below — reading the signal lazily at execution time would instead hand it
            // the new scope's live, un-aborted signal, letting a second app-a fetch fire here.
            await new Promise<void>((resolve) => {
              releaseFirstCall = resolve;
            });
          }
          return HttpResponse.json(makeEntries(1, 2));
        }),
      );

      const { rerender } = await renderWithRerenderableAppKey("app-a");

      // First hint starts the (now-hanging) fetch for app-a.
      await triggerHintAndWaitFor(() => {
        expect(sinceCallCountA).toBe(1);
      });

      // Second hint arrives while the first is still in flight — queued behind it, still
      // targeting app-a at this schedule instant.
      sendHint();
      await vi.advanceTimersByTimeAsync(HINT_MAX_WAIT_MS);
      expect(sinceCallCountA).toBe(1); // still queued, not yet executing

      // Scope changes to app-b before the queued run gets its turn — aborts app-a's controller.
      act(() => rerender({ appKey: "app-b" }));

      // Release the hanging first fetch so the chain advances to the queued (now-stale) run.
      await act(async () => {
        releaseFirstCall?.();
      });
      await vi.advanceTimersByTimeAsync(HINT_MAX_WAIT_MS + CATCH_UP_MIN_DELAY_MS + 500);

      // The queued run must bail via its own already-aborted signal instead of firing a second
      // fetch against the scope nobody's viewing anymore.
      expect(sinceCallCountA).toBe(1);
    });
  });

  describe("base-query merge", () => {
    useFakeTimersForCatchUp();

    it("does not let a base-query refetch erase entries a catch-up already merged in", async () => {
      // since-restart, not a fixed-window preset: this test is about refetch-merges-not-replaces
      // semantics, orthogonal to fixed-window pruning (which would otherwise treat these
      // deliberately tiny, non-wall-clock-relative fixture timestamps as long since expired).
      seedState("since-restart");
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

  describe("since-restart reconnect (uptime-only key change)", () => {
    useFakeTimersForCatchUp();

    it("carries the cursor and cached entries forward across a reconnect, instead of abandoning catch-up progress", async () => {
      seedState("since-restart");
      const queryClient = createTestQueryClient();
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(makeEntries(1, 1))));

      const { result } = renderHookWithProviders(() => useLogData({}), { queryClient });
      await waitForLoaded(result);

      // A hint-triggered catch-up advances the cursor and cache past the base fetch's own entry.
      server.use(http.get(LOGS_SINCE_ENDPOINT, () => HttpResponse.json(makeEntries(5, 2))));
      await triggerHintAndWaitFor(() => {
        expect(result.current.allEntries).toHaveLength(6); // ids 1-6
      });

      // Simulate a WS reconnect: uptimeSeconds changes (appKey/executionId/preset don't), which
      // changes scopedKey and fires a fresh base fetch — a limited, disjoint page as a real
      // reconnect fetch would return, simulating log volume that accumulated while disconnected.
      const capturedSinceIds: string[] = [];
      server.use(
        http.get(LOGS_SINCE_ENDPOINT, ({ params }) => {
          capturedSinceIds.push(params["sinceId"] as string);
          return HttpResponse.json([]);
        }),
      );
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(makeEntries(1, 100))));
      // Migration means the reconnect's own limited fetch merges with, rather than replaces, the
      // pre-reconnect cache — ids 1-6 survive alongside the new id 100.
      await act(async () => {
        useAppStore.setState({ uptimeSeconds: 200 });
        await vi.waitFor(() =>
          expect(result.current.allEntries.map((e) => e.id).sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5, 6, 100]),
        );
      });

      // The next catch-up fetch must start from the migrated cursor's advanced value (100, from
      // the post-reconnect fetch), not from the pre-migration value (6) or from 0.
      await triggerHintAndWaitFor(() => {
        expect(capturedSinceIds).toHaveLength(1);
      });
      expect(capturedSinceIds[0]).toBe("100");
    });

    it("does not migrate cursor/cache when appKey changes alongside uptime (a real scope change, not a reconnect)", async () => {
      seedState("since-restart");
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(makeEntries(1, 1))));

      const { result, rerender } = await renderWithRerenderableAppKey("app-a");
      expect(result.current.allEntries).toHaveLength(1);

      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json(makeEntries(1, 200))));
      // A different app's view starts from a clean slate — no id=1 carried over from app-a.
      await act(() => {
        useAppStore.setState({ uptimeSeconds: 200 });
        rerender({ appKey: "app-b" });
      });
      await vi.waitFor(() => {
        expect(result.current.allEntries.map((e) => e.id)).toEqual([200]);
      });
    });
  });

  describe("fixed-window pruning", () => {
    useFakeTimersForCatchUp();

    it("prunes cached entries that have aged out of a fixed time window on refetch", async () => {
      vi.setSystemTime(new Date(2026, 0, 1, 12, 0, 0).getTime());
      seedState("1h");
      const queryClient = createTestQueryClient();

      const staleEntry = createLogEntry({ id: 1, seq: 1, timestamp: Date.now() / 1000 - 1800, message: "stale" });
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json([staleEntry])));

      const { result } = renderHookWithProviders(() => useLogData({}), { queryClient });
      await waitForLoaded(result);
      expect(result.current.allEntries.map((e) => e.message)).toEqual(["stale"]);

      // 40 minutes later, "stale" (30 min old at fetch time) is now 70 min old — outside the
      // 1h window. A later refetch (e.g. a WS reconnect) must prune it, not just leave it until
      // the count-based MAX_CACHED_LOG_ENTRIES cap eventually evicts it.
      vi.setSystemTime(Date.now() + 40 * 60 * 1000);
      const freshEntry = createLogEntry({ id: 2, seq: 2, timestamp: Date.now() / 1000 - 60, message: "fresh" });
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json([freshEntry])));

      await act(async () => {
        await queryClient.refetchQueries({ queryKey: queryKeys.recentLogs() });
        // Flushes react-query's subscriber notification — under fake timers, setSystemTime's
        // clock jump can leave that notification's own scheduling stranded without this.
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(result.current.allEntries.map((e) => e.message)).toEqual(["fresh"]);
    });

    it("does not prune anything for the since-restart preset, whose window is the whole post-boot history", async () => {
      seedState("since-restart");
      const queryClient = createTestQueryClient();

      const oldEntry = createLogEntry({
        id: 1,
        seq: 1,
        timestamp: Date.now() / 1000 - 100_000,
        message: "old-but-since-boot",
      });
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json([oldEntry])));

      const { result } = renderHookWithProviders(() => useLogData({}), { queryClient });
      await waitForLoaded(result);

      const freshEntry = createLogEntry({ id: 2, seq: 2, timestamp: Date.now() / 1000 - 60, message: "fresh" });
      server.use(http.get(LOGS_ENDPOINT, () => HttpResponse.json([freshEntry])));
      await act(async () => {
        await queryClient.refetchQueries({ queryKey: queryKeys.recentLogs() });
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(result.current.allEntries.map((e) => e.message).sort()).toEqual(["fresh", "old-but-since-boot"]);
    });
  });
});
