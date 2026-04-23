import type { ReadonlySignal } from "@preact/signals";

/**
 * Subscribe to the given signals so the calling component re-renders whenever they change.
 * Preact signals auto-track reads of `.value` during render — this forces a subscription
 * even when the value itself is not used in the return value.
 *
 * Accepts null/undefined/false so callers can conditionally subscribe without
 * splitting into multiple calls: `useSubscribe(isMobile ? tick : null, logs.version)`
 */
export function useSubscribe(...signals: (ReadonlySignal | null | undefined | false)[]): void {
  for (const s of signals) if (s) void s.value;
}
