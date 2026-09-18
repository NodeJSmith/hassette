import type { UnifiedItemKind } from "./unified-handler-row";

export const ENTRY_TESTID_PREFIX = "overview-error-spotlight-entry-";

/** Mirrors the `data-testid` ErrorSpotlight renders for each entry. */
export function entryTestId(kind: UnifiedItemKind, id: number) {
  return `${ENTRY_TESTID_PREFIX}${kind}-${id}`;
}
