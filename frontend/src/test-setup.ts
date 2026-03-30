/**
 * Vitest setup file — polyfills for jsdom environment.
 *
 * jsdom does not provide requestAnimationFrame/cancelAnimationFrame,
 * which Preact hooks use internally for batched updates. Without these
 * stubs, hook cleanup timers that fire after test teardown cause
 * "cancelAnimationFrame is not defined" unhandled errors.
 */

if (typeof globalThis.requestAnimationFrame === "undefined") {
  globalThis.requestAnimationFrame = (cb: FrameRequestCallback): number => {
    return setTimeout(cb, 0) as unknown as number;
  };
}

if (typeof globalThis.cancelAnimationFrame === "undefined") {
  globalThis.cancelAnimationFrame = (id: number): void => {
    clearTimeout(id);
  };
}
