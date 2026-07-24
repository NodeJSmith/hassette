import type { UnifiedItem } from "./unified-handler-row";

export function compareFailingFirst(a: UnifiedItem, b: UnifiedItem): number {
  return Number(b.statusKind === "err") - Number(a.statusKind === "err");
}
