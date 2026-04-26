/**
 * Vitest setup file — polyfills for jsdom environment and MSW server lifecycle.
 *
 * jsdom does not provide requestAnimationFrame/cancelAnimationFrame,
 * which Preact hooks use internally for batched updates. Without these
 * stubs, hook cleanup timers that fire after test teardown cause
 * "cancelAnimationFrame is not defined" unhandled errors.
 *
 * MSW (Mock Service Worker) intercepts all fetch calls at the network level
 * during tests. Default handlers are defined in src/test/handlers.ts.
 * Tests that need custom responses use `server.use(...)` for per-test overrides.
 */

import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "./test/handlers";

globalThis.requestAnimationFrame = (cb: FrameRequestCallback): number => {
  return setTimeout(cb, 0) as unknown as number;
};

globalThis.cancelAnimationFrame = (id: number): void => {
  clearTimeout(id);
};

export const server = setupServer(...handlers);

beforeAll(() => {
  // Handler coverage is complete — any unhandled request is a missing handler.
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  // Reset any per-test handler overrides so tests don't bleed into each other.
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});
