import { type HandlerKind, handlerPath } from "../../utils/app-routes";
import { handlerKindLabel } from "../../utils/status";
import { compareFailingFirst } from "./handler-sort";
import type { UnifiedItem } from "./unified-handler-row";

export function handlerHref(appKey: string, item: UnifiedItem, instanceQs: string): string {
  const kind: HandlerKind = item.kind === "listener" ? "listener" : "job";
  return handlerPath(
    appKey,
    kind,
    item.id,
    instanceQs ? { instance: new URLSearchParams(instanceQs).get("instance") } : undefined,
  );
}

export function isFailing(item: UnifiedItem): boolean {
  return item.statusKind === "err";
}

export function itemRunCount(item: UnifiedItem): number {
  return item.kind === "listener" ? item.data.total_invocations : item.data.total_executions;
}

export function sortedByFailingFirst(items: UnifiedItem[]): UnifiedItem[] {
  return [...items].sort((a, b) => {
    const healthOrder = compareFailingFirst(a, b);
    if (healthOrder !== 0) return healthOrder;
    return itemRunCount(b) - itemRunCount(a);
  });
}

export function itemLastActiveAt(item: UnifiedItem): number | null {
  return item.kind === "listener" ? (item.data.last_invoked_at ?? null) : (item.data.last_executed_at ?? null);
}

export function itemErrorType(item: UnifiedItem): string | null {
  return item.data.last_error_type ?? (item.data.timed_out > 0 ? "timed out" : null);
}

export function itemErrorMessage(item: UnifiedItem): string | null {
  return item.data.last_error_message ?? null;
}

export function itemKindChip(item: UnifiedItem): string {
  if (item.kind === "listener") {
    return handlerKindLabel("listener", item.data.listener_kind, null);
  }
  return handlerKindLabel("job", null, item.data.trigger_type);
}
