/**
 * Test utilities for `useLogData` hook tests.
 *
 * `renderLoaded()` renders `useLogData(props)` and waits for the initial REST fetch to resolve —
 * use when the REST response is stubbed separately (a custom handler, or none at all).
 * `renderLoadedLogData()` additionally stubs `/api/logs/recent` to return a static `entries` array
 * before rendering — the common case where the REST response is a static entries array rather
 * than a custom handler. `renderLoadedWithRestEntry()` further stubs a single REST-origin log
 * entry as the initial REST response — the WS-merge tests' shared setup: one REST entry present
 * before WS pushes arrive.
 */

import { http, HttpResponse } from "msw";
import { expect, vi } from "vitest";

import type { WsLogPayload } from "../api/ws-types";
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
export async function renderLoadedLogData(entries: WsLogPayload[] = [], props: Parameters<typeof useLogData>[0] = {}) {
  server.use(http.get("/api/logs/recent", () => HttpResponse.json(entries)));
  return renderLoaded(props);
}

/** Stubs a single REST-origin log entry as the initial REST response, then renders and waits via
 * `renderLoadedLogData`. Covers the WS-merge tests' common setup: one REST entry present before WS
 * pushes arrive. */
export async function renderLoadedWithRestEntry(entry: WsLogPayload) {
  return renderLoadedLogData([entry]);
}
