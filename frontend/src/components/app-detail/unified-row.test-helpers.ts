import type { UnifiedItemKind } from "./unified-handler-row";

export const ROW_TESTID_PREFIX = "unified-row-";

/** Mirrors the `data-testid` UnifiedHandlerRow renders for each row. */
export function rowTestId(kind: UnifiedItemKind, id: number) {
  return `${ROW_TESTID_PREFIX}${kind}-${id}`;
}
