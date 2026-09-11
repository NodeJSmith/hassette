import { handlerPath, parseInstanceParam } from "../../utils/app-routes";
import { handlerKindLabel, TIMED_OUT_LABEL } from "../../utils/status";
import { compareFailingFirst } from "./handler-sort";
import type { UnifiedItem } from "./unified-handler-row";

export function handlerHref(appKey: string, item: UnifiedItem, instanceQs: string): string {
  return handlerPath(appKey, item.kind, item.id, {
    instance: parseInstanceParam(new URLSearchParams(instanceQs).get("instance")),
  });
}

export function isFailing(item: UnifiedItem): boolean {
  return item.statusKind === "err";
}

export function isIdle(item: UnifiedItem): boolean {
  return item.statusKind === "mute";
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

export function itemErrorLabel(item: UnifiedItem): string | null {
  return item.data.last_error_type ?? (item.data.timed_out > 0 ? TIMED_OUT_LABEL : null);
}

export function itemErrorMessage(item: UnifiedItem): string | null {
  return item.data.last_error_message ?? null;
}

export function itemKindChip(item: UnifiedItem): string {
  if (item.kind === "listener") {
    return handlerKindLabel("listener", item.data.listener_kind);
  }
  return handlerKindLabel("job", null, item.data.trigger_type);
}
