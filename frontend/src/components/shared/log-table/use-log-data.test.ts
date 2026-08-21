import { act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type TimePreset, useAppStore } from "@/state/store";
import { createLogEntry } from "@/test/factories";
import { renderLoaded, renderLoadedLogData, renderLoadedWithRestEntry } from "@/test/log-data-test-utils";
import { renderHookWithProviders } from "@/test/query-test-utils";
import { server } from "@/test/server";

import { LIVE_LOG_UPDATE_INTERVAL_MS, REST_FETCH_LIMIT } from "./constants";
import { useLogData } from "./use-log-data";

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

beforeEach(() => {
  vi.mocked(toast.error).mockClear();
});

describe("useLogData", () => {
  describe("loading state", () => {
    it("is true initially before REST resolves", () => {
      seedState();
      // Override with a never-resolving handler to freeze the fetch in-flight.
      server.use(http.get("/api/logs/recent", () => new Promise(() => {})));

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
        http.get("/api/logs/recent", ({ request }) => {
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

    it("populates restEntries with the fetched entries", async () => {
      seedState();
      const entries = [
        createLogEntry({ seq: 1, timestamp: 1000, message: "first" }),
        createLogEntry({ seq: 2, timestamp: 2000, message: "second" }),
      ];

      const result = await renderLoadedLogData(entries);

      expect(result.current.restEntries).toHaveLength(2);
      expect(result.current.restEntries[0].message).toBe("first");
      expect(result.current.restEntries[1].message).toBe("second");
    });

    it("includes REST entries in allEntries", async () => {
      seedState();
      const entries = [createLogEntry({ seq: 1, timestamp: 1000, message: "rest-entry" })];

      const result = await renderLoadedLogData(entries);

      expect(result.current.allEntries.some((e) => e.message === "rest-entry")).toBe(true);
    });
  });

  describe("WS merge", () => {
    it("prepends WS entries above the REST watermark to keep timestamp-desc order", async () => {
      seedState();
      const result = await renderLoadedWithRestEntry(createLogEntry({ seq: 1, timestamp: 1000, message: "rest" }));

      act(() => {
        useAppStore.getState().pushLog(createLogEntry({ seq: 2, timestamp: 2000, message: "ws-new" }));
      });

      await vi.waitFor(() => {
        expect(result.current.allEntries).toHaveLength(2);
        expect(result.current.allEntries[0].message).toBe("ws-new");
        expect(result.current.allEntries[1].message).toBe("rest");
      });
    });

    it("orders multiple WS entries newest first before REST entries", async () => {
      seedState();
      const result = await renderLoadedWithRestEntry(createLogEntry({ seq: 1, timestamp: 1000, message: "rest" }));

      act(() => {
        useAppStore.getState().pushLog(createLogEntry({ seq: 2, timestamp: 2000, message: "ws-older" }));
        useAppStore.getState().pushLog(createLogEntry({ seq: 3, timestamp: 3000, message: "ws-newer" }));
      });

      await vi.waitFor(() => {
        expect(result.current.allEntries.map((e) => e.message)).toEqual(["ws-newer", "ws-older", "rest"]);
      });
    });

    // dup-ignore-start: parallel WS-merge filter test case — render+push+assert shape token-matches the sibling filter-scenario tests below that push and check a different message set, not duplicated setup
    it("excludes WS entries whose rowKey matches a REST entry (deduplication)", async () => {
      seedState();
      const result = await renderLoadedWithRestEntry(createLogEntry({ seq: 1, timestamp: 5000, message: "rest" }));

      act(() => {
        // Same seq+timestamp as REST entry → same rowKey → excluded
        useAppStore.getState().pushLog(createLogEntry({ seq: 1, timestamp: 5000, message: "exact-dup" }));
        // Different seq → different rowKey → included
        useAppStore.getState().pushLog(createLogEntry({ seq: 2, timestamp: 5000, message: "same-ts-diff-seq" }));
        useAppStore.getState().pushLog(createLogEntry({ seq: 3, timestamp: 6000, message: "newer" }));
      });

      await vi.waitFor(() => {
        const messages = result.current.allEntries.map((e) => e.message);
        expect(messages).toContain("same-ts-diff-seq");
        expect(messages).toContain("newer");
        expect(messages).not.toContain("exact-dup");
      });
    });
    // dup-ignore-end

    // dup-ignore-start: parallel WS-merge filter test case — render+push+assert shape token-matches the sibling filter-scenario tests in this describe block that push and check a different message set, not duplicated setup
    it("preserves distinct records that share a timestamp (same-timestamp dedup fix)", async () => {
      seedState();

      const result = await renderLoadedLogData();

      act(() => {
        useAppStore.getState().pushLog(createLogEntry({ seq: 10, timestamp: 9000, message: "first" }));
        useAppStore.getState().pushLog(createLogEntry({ seq: 11, timestamp: 9000, message: "second" }));
        useAppStore.getState().pushLog(createLogEntry({ seq: 12, timestamp: 9000, message: "third" }));
      });

      await vi.waitFor(() => {
        const messages = result.current.allEntries.map((e) => e.message);
        expect(messages).toHaveLength(3);
        expect(messages).toContain("first");
        expect(messages).toContain("second");
        expect(messages).toContain("third");
      });
    });
    // dup-ignore-end

    // dup-ignore-start: parallel WS-merge filter test case — render+push+assert shape token-matches the sibling filter-scenario tests in this describe block that push and check a different message set, not duplicated setup
    it("excludes WS entries for a different app_key when appKey is provided", async () => {
      seedState();

      const result = await renderLoadedLogData([], { appKey: "my_app" });

      act(() => {
        useAppStore.getState().pushLog(createLogEntry({ seq: 1, timestamp: 9000, app_key: "my_app", message: "mine" }));
        useAppStore
          .getState()
          .pushLog(createLogEntry({ seq: 2, timestamp: 9001, app_key: "other_app", message: "not-mine" }));
      });

      await vi.waitFor(() => {
        const messages = result.current.allEntries.map((e) => e.message);
        expect(messages).toContain("mine");
        expect(messages).not.toContain("not-mine");
      });
    });
    // dup-ignore-end

    // dup-ignore-start: parallel WS-merge filter test case — render+push+assert shape token-matches the sibling filter-scenario tests in this describe block that push and check a different message set, not duplicated setup
    it("excludes WS entries for a different execution_id when executionId is provided", async () => {
      seedState();

      const result = await renderLoadedLogData([], { executionId: "exec-1" });

      act(() => {
        useAppStore
          .getState()
          .pushLog(createLogEntry({ seq: 1, timestamp: 9000, execution_id: "exec-1", message: "this-exec" }));
        useAppStore
          .getState()
          .pushLog(createLogEntry({ seq: 2, timestamp: 9001, execution_id: "exec-2", message: "other-exec" }));
      });

      await vi.waitFor(() => {
        const messages = result.current.allEntries.map((e) => e.message);
        expect(messages).toContain("this-exec");
        expect(messages).not.toContain("other-exec");
      });
    });
    // dup-ignore-end

    // dup-ignore-start: parallel WS-merge filter test case — render+push+assert shape token-matches the sibling filter-scenario tests in this describe block that push and check a different message set, not duplicated setup
    it("includes all WS entries not in the REST set when no filters are provided", async () => {
      seedState();

      const result = await renderLoadedLogData();

      act(() => {
        useAppStore.getState().pushLog(createLogEntry({ seq: 1, timestamp: 1000, app_key: "app-a", message: "a" }));
        useAppStore.getState().pushLog(createLogEntry({ seq: 2, timestamp: 2000, app_key: "app-b", message: "b" }));
      });

      await vi.waitFor(() => {
        const messages = result.current.allEntries.map((e) => e.message);
        expect(messages).toContain("a");
        expect(messages).toContain("b");
      });
    });
    // dup-ignore-end

    it("throttles live WS entries before exposing them to the table", async () => {
      seedState();

      const result = await renderLoadedLogData();

      vi.useFakeTimers();
      try {
        act(() => {
          useAppStore.getState().pushLog(createLogEntry({ seq: 1, timestamp: 1000, message: "throttled" }));
        });

        expect(result.current.allEntries.map((e) => e.message)).not.toContain("throttled");

        await act(async () => {
          vi.advanceTimersByTime(LIVE_LOG_UPDATE_INTERVAL_MS - 1);
        });
        expect(result.current.allEntries.map((e) => e.message)).not.toContain("throttled");

        await act(async () => {
          vi.advanceTimersByTime(1);
        });
        expect(result.current.allEntries.map((e) => e.message)).toContain("throttled");
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe("time-window filtering", () => {
    it("passes the since parameter to the REST fetch", async () => {
      seedState("1h");
      let capturedUrl: string | undefined;

      server.use(
        http.get("/api/logs/recent", ({ request }) => {
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
        http.get("/api/logs/recent", () => {
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

      server.use(http.get("/api/logs/recent", () => HttpResponse.json([])));

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

      server.use(http.get("/api/logs/recent", () => HttpResponse.error()));

      const result = await renderLoaded();

      expect(toast.error).toHaveBeenCalledTimes(1);
      expect(result.current.restEntries).toHaveLength(0);
    });
  });
});
