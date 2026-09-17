import { handlerPath, parseInstanceParam } from "../../utils/app-routes";
import { formatTimestamp } from "../../utils/format";
import { scheduleStatusLabel } from "../../utils/handler-rows";
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

/** Display label plus tooltip for a job's upcoming run, or nulls when there is none to show. */
export function itemNextRunDisplay(
  item: UnifiedItem,
  nextRunRelative: string,
  fireAtRelative: string,
): { label: string | null; title: string | null } {
  if (item.kind !== "job") return { label: null, title: null };
  if (item.data.next_run) {
    return { label: `next ${nextRunRelative}`, title: formatTimestamp(item.data.next_run) };
  }
  if (item.data.fire_at) {
    return { label: `fire at ${fireAtRelative}`, title: formatTimestamp(item.data.fire_at) };
  }
  return { label: null, title: null };
}

/** Human-readable schedule status for a job, or null for listeners and unlabeled statuses. */
export function itemScheduleStatus(item: UnifiedItem): string | null {
  if (item.kind !== "job") return null;
  return scheduleStatusLabel(item.data.schedule_status ?? null, item.data.schedule_status_reason ?? null);
}
