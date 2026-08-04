import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { createQueryClient, DEFAULT_STALE_TIME_MS } from "./query-client";

describe("createQueryClient", () => {
  it("returns a QueryClient with staleTime 30_000", () => {
    const client = createQueryClient();
    const defaults = client.getDefaultOptions();
    expect(defaults.queries?.staleTime).toBe(DEFAULT_STALE_TIME_MS);
  });

  it("has refetchOnWindowFocus set to false", () => {
    const client = createQueryClient();
    const defaults = client.getDefaultOptions();
    expect(defaults.queries?.refetchOnWindowFocus).toBe(false);
  });

  it("has refetchOnReconnect set to false", () => {
    const client = createQueryClient();
    const defaults = client.getDefaultOptions();
    expect(defaults.queries?.refetchOnReconnect).toBe(false);
  });

  describe("retry function", () => {
    function getRetry(failureCount: number, error: Error): boolean {
      const client = createQueryClient();
      const retry = client.getDefaultOptions().queries?.retry;
      if (typeof retry !== "function") throw new Error("retry is not a function");
      return retry(failureCount, error);
    }

    it("returns false for 4xx errors (no retry)", () => {
      const error = new ApiError(404, "Not Found");
      expect(getRetry(0, error)).toBe(false);
    });

    it("returns false for 400 Bad Request", () => {
      const error = new ApiError(400, "Bad Request");
      expect(getRetry(0, error)).toBe(false);
    });

    it("returns false for 401 Unauthorized", () => {
      const error = new ApiError(401, "Unauthorized");
      expect(getRetry(0, error)).toBe(false);
    });

    it("returns false for 499 (edge of 4xx range)", () => {
      const error = new ApiError(499, "Client Error");
      expect(getRetry(0, error)).toBe(false);
    });

    it("returns true for 5xx errors on first failure (failureCount < 2)", () => {
      const error = new ApiError(503, "Service Unavailable");
      expect(getRetry(0, error)).toBe(true);
    });

    it("returns true for 500 on second failure (failureCount = 1)", () => {
      const error = new ApiError(500, "Internal Server Error");
      expect(getRetry(1, error)).toBe(true);
    });

    it("returns false for 5xx errors after 2 failures (failureCount >= 2)", () => {
      const error = new ApiError(503, "Service Unavailable");
      expect(getRetry(2, error)).toBe(false);
    });

    it("returns true for network errors (non-HTTP failures) on first attempt", () => {
      const error = new Error("Network error");
      expect(getRetry(0, error)).toBe(true);
    });

    it("returns true for network errors on second attempt (failureCount = 1)", () => {
      const error = new Error("fetch failed");
      expect(getRetry(1, error)).toBe(true);
    });

    it("returns false for network errors after 2 failures (failureCount >= 2)", () => {
      const error = new Error("fetch failed");
      expect(getRetry(2, error)).toBe(false);
    });
  });

  describe("QueryCache.onError — 401 redirect", () => {
    const originalLocation = window.location;

    beforeEach(() => {
      Object.defineProperty(window, "location", {
        value: { ...originalLocation, assign: vi.fn() },
        writable: true,
        configurable: true,
      });
    });

    afterEach(() => {
      Object.defineProperty(window, "location", {
        value: originalLocation,
        writable: true,
        configurable: true,
      });
    });

    function triggerQueryError(error: Error) {
      const client = createQueryClient();
      client.getQueryCache().config.onError?.(error, {
        state: {},
        queryKey: ["test"],
        queryHash: "test",
        options: {},
      } as never);
    }

    it("redirects to /login on a 401 ApiError", () => {
      triggerQueryError(new ApiError(401, "Unauthorized"));

      expect(window.location.assign).toHaveBeenCalledWith("/login");
    });

    it("does not redirect on a non-401 ApiError", () => {
      triggerQueryError(new ApiError(500, "Internal Server Error"));

      expect(window.location.assign).not.toHaveBeenCalled();
    });

    it("does not redirect on a non-ApiError error", () => {
      triggerQueryError(new Error("network down"));

      expect(window.location.assign).not.toHaveBeenCalled();
    });
  });
});
