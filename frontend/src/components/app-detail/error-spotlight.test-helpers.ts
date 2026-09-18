import type { UnifiedItemKind } from "./unified-handler-row";

export const ENTRY_TESTID_PREFIX = "overview-error-spotlight-entry-";
export const ENTRY_SELECTOR = `[data-testid^='${ENTRY_TESTID_PREFIX}']`;

/** Mirrors the `data-testid` ErrorSpotlight renders for each entry. */
export function entryTestId(kind: UnifiedItemKind, id: number) {
  return `${ENTRY_TESTID_PREFIX}${kind}-${id}`;
}
