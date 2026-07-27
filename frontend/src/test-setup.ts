/**
 * Vitest setup file — polyfills for jsdom environment and MSW server lifecycle.
 *
 * jsdom does not provide requestAnimationFrame/cancelAnimationFrame,
 * which React uses internally for scheduling. Without these
 * stubs, hook cleanup timers that fire after test teardown cause
 * "cancelAnimationFrame is not defined" unhandled errors.
 *
 * MSW (Mock Service Worker) intercepts all fetch calls at the network level
 * during tests. Default handlers are defined in src/test/handlers.ts.
 * Tests that need custom responses use `server.use(...)` for per-test overrides.
 */

import { afterAll, afterEach, beforeAll } from "vitest";

import { initialState, LOG_BUFFER_CAPACITY, useAppStore } from "./state/store";
import { server } from "./test/server";
import { RingBuffer } from "./utils/ring-buffer";

globalThis.requestAnimationFrame = (cb: FrameRequestCallback): number => {
  return setTimeout(cb, 0) as unknown as number;
};

globalThis.cancelAnimationFrame = (id: number): void => {
  clearTimeout(id);
};

// jsdom does not provide ResizeObserver — stub it for components that use it.
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// jsdom does not provide matchMedia — stub it for useMediaQuery and components
// that depend on it. Always returns false (desktop viewport) by default.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  }),
});

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
});

// Reset the Zustand app store between tests. Plain `setState(initialState())` alone would
// reconstruct the RingBuffer via initialState()'s factory already, but we spell it out
// explicitly here per the design doc's isolation note: setState(initialState) (no call) reuses
// the same mutable buffer reference, so a fresh RingBuffer must always be constructed.
//
// initialState() also reads real localStorage for theme/sidebarCollapsed/timePreset, so clear
// it too — otherwise "defaults" silently means "whatever a prior test in this file wrote."
afterEach(() => {
  localStorage.clear();
  useAppStore.setState({ ...initialState(), logBuffer: new RingBuffer(LOG_BUFFER_CAPACITY) });
});

afterAll(() => {
  server.close();
});
