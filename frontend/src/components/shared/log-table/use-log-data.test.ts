import { act, renderHook } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import type { ComponentChildren } from "preact";
import { h } from "preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WsLogPayload } from "../../../api/ws-types";
import { AppStateContext } from "../../../state/context";
import { type AppState, createAppState } from "../../../state/create-app-state";
import { server } from "../../../test/server";
import { REST_FETCH_LIMIT } from "./constants";
import { useLogData } from "./use-log-data";

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}));

// Import after mock so the spy reference is captured.
const { toast } = await import("sonner");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createWrapper(state: AppState) {
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return h(AppStateContext.Provider, { value: state }, children);
  };
}

function makeLogEntry(overrides: Partial<WsLogPayload> = {}): WsLogPayload {
  return {
    seq: 1,
    timestamp: 1000,
    level: "INFO",
    logger_name: "test",
    func_name: "test_fn",
    lineno: 1,
    message: "test message",
    exc_info: null,
    app_key: null,
    execution_id: null,
    instance_name: null,
    instance_index: null,
    source_tier: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(toast.error).mockClear();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useLogData", () => {
  describe("loading state", () => {
    it("is true initially before REST resolves", () => {
      const state = createAppState();
      // Override with a never-resolving handler to freeze the fetch in-flight.
      server.use(http.get("/api/logs/recent", () => new Promise(() => {})));

      const { result } = renderHook(() => useLogData({}), {
        wrapper: createWrapper(state),
      });

      expect(result.current.loading.value).toBe(true);
    });

    it("becomes false after REST resolves", async () => {
      const state = createAppState();

      const { result } = renderHook(() => useLogData({}), {
        wrapper: createWrapper(state),
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });
    });
  });

  describe("REST fetch", () => {
    it("calls the /api/logs/recent endpoint with appKey, executionId, and limit", async () => {
      const state = createAppState();
      let capturedUrl: string | undefined;

      server.use(
        http.get("/api/logs/recent", ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json([]);
        }),
      );

      const { result } = renderHook(() => useLogData({ appKey: "my_app", executionId: "exec-42" }), {
        wrapper: createWrapper(state),
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      expect(capturedUrl).toBeDefined();
      const url = new URL(capturedUrl!);
      expect(url.searchParams.get("app_key")).toBe("my_app");
      expect(url.searchParams.get("execution_id")).toBe("exec-42");
      expect(url.searchParams.get("limit")).toBe(String(REST_FETCH_LIMIT));
    });

    it("populates restEntries with the fetched entries", async () => {
      const state = createAppState();
      const entries = [
        makeLogEntry({ seq: 1, timestamp: 1000, message: "first" }),
        makeLogEntry({ seq: 2, timestamp: 2000, message: "second" }),
      ];

      server.use(http.get("/api/logs/recent", () => HttpResponse.json(entries)));

      const { result } = renderHook(() => useLogData({}), {
        wrapper: createWrapper(state),
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      expect(result.current.restEntries.value).toHaveLength(2);
      expect(result.current.restEntries.value[0].message).toBe("first");
      expect(result.current.restEntries.value[1].message).toBe("second");
    });

    it("includes REST entries in allEntries", async () => {
      const state = createAppState();
      const entries = [makeLogEntry({ seq: 1, timestamp: 1000, message: "rest-entry" })];

      server.use(http.get("/api/logs/recent", () => HttpResponse.json(entries)));

      const { result } = renderHook(() => useLogData({}), {
        wrapper: createWrapper(state),
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      expect(result.current.allEntries.value.some((e) => e.message === "rest-entry")).toBe(true);
    });
  });

  describe("WS merge", () => {
    it("appends WS entries above the REST watermark to allEntries", async () => {
      const state = createAppState();
      const restEntry = makeLogEntry({ seq: 1, timestamp: 1000, message: "rest" });

      server.use(http.get("/api/logs/recent", () => HttpResponse.json([restEntry])));

      const { result } = renderHook(() => useLogData({}), {
        wrapper: createWrapper(state),
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      // Push a WS entry with a timestamp strictly above the REST watermark.
      act(() => {
        state.logs.push(makeLogEntry({ seq: 2, timestamp: 2000, message: "ws-new" }));
      });

      expect(result.current.allEntries.value).toHaveLength(2);
      expect(result.current.allEntries.value[1].message).toBe("ws-new");
    });

    it("does not include WS entries at or below the REST watermark (deduplication)", async () => {
      const state = createAppState();
      const restEntry = makeLogEntry({ seq: 1, timestamp: 5000, message: "rest" });

      server.use(http.get("/api/logs/recent", () => HttpResponse.json([restEntry])));

      const { result } = renderHook(() => useLogData({}), {
        wrapper: createWrapper(state),
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      act(() => {
        // At the watermark — should be filtered out.
        state.logs.push(makeLogEntry({ seq: 2, timestamp: 5000, message: "dup-at-watermark" }));
        // Below the watermark — should be filtered out.
        state.logs.push(makeLogEntry({ seq: 3, timestamp: 3000, message: "dup-below-watermark" }));
      });

      const messages = result.current.allEntries.value.map((e) => e.message);
      expect(messages).not.toContain("dup-at-watermark");
      expect(messages).not.toContain("dup-below-watermark");
    });

    it("excludes WS entries for a different app_key when appKey is provided", async () => {
      const state = createAppState();

      server.use(http.get("/api/logs/recent", () => HttpResponse.json([])));

      const { result } = renderHook(() => useLogData({ appKey: "my_app" }), { wrapper: createWrapper(state) });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      act(() => {
        state.logs.push(makeLogEntry({ seq: 1, timestamp: 9000, app_key: "my_app", message: "mine" }));
        state.logs.push(makeLogEntry({ seq: 2, timestamp: 9001, app_key: "other_app", message: "not-mine" }));
      });

      const messages = result.current.allEntries.value.map((e) => e.message);
      expect(messages).toContain("mine");
      expect(messages).not.toContain("not-mine");
    });

    it("excludes WS entries for a different execution_id when executionId is provided", async () => {
      const state = createAppState();

      server.use(http.get("/api/logs/recent", () => HttpResponse.json([])));

      const { result } = renderHook(() => useLogData({ executionId: "exec-1" }), { wrapper: createWrapper(state) });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      act(() => {
        state.logs.push(makeLogEntry({ seq: 1, timestamp: 9000, execution_id: "exec-1", message: "this-exec" }));
        state.logs.push(makeLogEntry({ seq: 2, timestamp: 9001, execution_id: "exec-2", message: "other-exec" }));
      });

      const messages = result.current.allEntries.value.map((e) => e.message);
      expect(messages).toContain("this-exec");
      expect(messages).not.toContain("other-exec");
    });

    it("includes all WS entries above the watermark when no filters are provided", async () => {
      const state = createAppState();

      server.use(http.get("/api/logs/recent", () => HttpResponse.json([])));

      const { result } = renderHook(() => useLogData({}), {
        wrapper: createWrapper(state),
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      act(() => {
        state.logs.push(makeLogEntry({ seq: 1, timestamp: 1000, app_key: "app-a", message: "a" }));
        state.logs.push(makeLogEntry({ seq: 2, timestamp: 2000, app_key: "app-b", message: "b" }));
      });

      const messages = result.current.allEntries.value.map((e) => e.message);
      expect(messages).toContain("a");
      expect(messages).toContain("b");
    });
  });

  describe("error handling", () => {
    it("shows a toast error and sets loading to false when the REST fetch rejects", async () => {
      const state = createAppState();

      server.use(http.get("/api/logs/recent", () => HttpResponse.error()));

      const { result } = renderHook(() => useLogData({}), {
        wrapper: createWrapper(state),
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      expect(toast.error).toHaveBeenCalledTimes(1);
      expect(result.current.restEntries.value).toHaveLength(0);
    });
  });

  describe("reconnect refetch", () => {
    it("re-fetches REST data when reconnectVersion increments", async () => {
      const state = createAppState();
      let fetchCount = 0;

      server.use(
        http.get("/api/logs/recent", () => {
          fetchCount++;
          return HttpResponse.json([]);
        }),
      );

      const { result } = renderHook(() => useLogData({}), {
        wrapper: createWrapper(state),
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      expect(fetchCount).toBe(1);

      act(() => {
        state.reconnectVersion.value = 1;
      });

      await vi.waitFor(() => {
        expect(fetchCount).toBe(2);
      });
    });

    it("resets the watermark on reconnect so stale WS entries are re-evaluated", async () => {
      const state = createAppState();
      const firstBatch = [makeLogEntry({ seq: 1, timestamp: 5000, message: "initial-rest" })];
      const secondBatch = [makeLogEntry({ seq: 2, timestamp: 3000, message: "reconnect-rest" })];
      let callCount = 0;

      server.use(
        http.get("/api/logs/recent", () => {
          callCount++;
          return HttpResponse.json(callCount === 1 ? firstBatch : secondBatch);
        }),
      );

      const { result } = renderHook(() => useLogData({}), {
        wrapper: createWrapper(state),
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
      });

      // WS entry above the first watermark (5000).
      act(() => {
        state.logs.push(makeLogEntry({ seq: 3, timestamp: 9000, message: "ws-high" }));
      });

      expect(result.current.allEntries.value.some((e) => e.message === "ws-high")).toBe(true);

      // Reconnect — second REST batch has watermark 3000.
      act(() => {
        state.reconnectVersion.value = 1;
      });

      await vi.waitFor(() => {
        expect(result.current.loading.value).toBe(false);
        expect(result.current.restEntries.value[0]?.message).toBe("reconnect-rest");
      });

      // WS entry above the new watermark (3000) should be included.
      act(() => {
        state.logs.push(makeLogEntry({ seq: 4, timestamp: 4000, message: "ws-after-reconnect" }));
      });

      expect(result.current.allEntries.value.some((e) => e.message === "ws-after-reconnect")).toBe(true);
    });
  });
});
