/**
 * Test utilities for `useLogData` hook tests.
 *
 * `renderLoaded()` renders `useLogData(props)` and waits for the initial REST fetch to resolve —
 * use when the REST response is stubbed separately (a custom handler, or none at all).
 * `renderLoadedLogData()` additionally stubs `/api/logs/recent` to return a static `entries` array
 * before rendering — the common case where the REST response is a static entries array rather
 * than a custom handler.
 */

import { http, HttpResponse, type JsonBodyType } from "msw";
import { afterEach, beforeEach, expect, vi } from "vitest";

import type { LogEntry } from "../api/endpoints";
import { useLogData } from "../components/shared/log-table/use-log-data";
import { renderHookWithProviders } from "./query-test-utils";
import { server } from "./server";

/** Renders `useLogData(props)` and waits for the initial REST fetch to resolve. Use when the
 * REST response is stubbed separately (a custom handler, or none at all). */
export async function renderLoaded(props: Parameters<typeof useLogData>[0] = {}) {
  const { result } = renderHookWithProviders(() => useLogData(props));
  await vi.waitFor(() => {
    expect(result.current.loading).toBe(false);
  });
  return result;
}

/** Stubs `/api/logs/recent` to return `entries`, then renders and waits via `renderLoaded`. Covers
 * the common case where the REST response is a static entries array rather than a custom handler. */
export async function renderLoadedLogData(entries: LogEntry[] = [], props: Parameters<typeof useLogData>[0] = {}) {
  server.use(http.get("/api/logs/recent", () => HttpResponse.json(entries)));
  return renderLoaded(props);
}

/** Registers the `vi.useFakeTimers({ shouldAdvanceTime: true })` / `vi.useRealTimers()` pair that
 * every catch-up/periodic-resync test suite needs — call once at the top of a `describe` block in
 * place of writing both hooks out by hand. */
export function useFakeTimersForCatchUp(): void {
  // dup-ignore-start: bare vi.useFakeTimers()/vi.useRealTimers() pair — same idiom as
  // format.test.ts and time-window.test.ts use; nothing left to extract once it's already its
  // own function.
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });
  // dup-ignore-end
}

/** Stubs a GET `endpoint` handler that counts its own calls and delegates the response to
 * `respond`. Returns a `getCount()` accessor for asserting on call count. Use directly for a
 * non-JSON response (e.g. `HttpResponse.error()`); `stubCountingEndpoint` below covers the
 * common JSON case. */
export function stubCountingHandler(endpoint: string, respond: () => Response): () => number {
  let count = 0;
  server.use(
    http.get(endpoint, () => {
      count++;
      return respond();
    }),
  );
  return () => count;
}

/** Stubs a GET `endpoint` handler that counts its own calls and returns `response` (default: an
 * empty array) every time, optionally with a custom status via `init`. Returns a `getCount()`
 * accessor for asserting on call count. */
export function stubCountingEndpoint(endpoint: string, response: JsonBodyType = [], init?: ResponseInit): () => number {
  return stubCountingHandler(endpoint, () => HttpResponse.json(response, init));
}
