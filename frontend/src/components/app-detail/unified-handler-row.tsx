import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { JobData, ListenerData } from "../../api/endpoints";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { STATUS_SHAPE_SIZE } from "../../utils/constants";
import { pluralize } from "../../utils/format";
import type { StatusKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import {
  isFailing,
  isIdle,
  itemErrorMessage,
  itemKindChip,
  itemNextRunDisplay,
  itemRunCount,
  itemScheduleStatus,
} from "./overview-tab-helpers";

export type UnifiedItemKind = "listener" | "job";

/** Shared look for the small inline chips on the row's second line; callers add border/background color. */
const CHIP_BASE_CLASS =
  "shrink-0 rounded-sm border px-1 py-px font-mono text-xs font-medium leading-[var(--text-micro-leading)] lowercase tracking-[var(--text-label-tracking-tight)] text-muted-foreground";

/** Discriminated union for items that can appear in the unified list. */
export type UnifiedItem =
  | {
      kind: "listener";
      id: number;
      name: string;
      humanDescription: string | null;
      statusKind: StatusKind;
      data: ListenerData;
    }
  | { kind: "job"; id: number; name: string; humanDescription: string | null; statusKind: StatusKind; data: JobData };

interface Props {
  item: UnifiedItem;
  isSelected: boolean;
  onSelect: () => void;
}

/**
 * A single row in the unified handlers+jobs master list.
 *
 * Clicking the row selects it in the detail pane (no expand-in-place).
 * Two-line layout: name/status on line one, kind/mode/stats/next-run on
 * line two. Failing rows gain a third line with the last error message.
 */
export function UnifiedHandlerRow({ item, isSelected, onSelect }: Props) {
  const jobData = item.kind === "job" ? item.data : null;
  const nextRunRelative = useRelativeTime(jobData?.next_run ?? null);
  const fireAtRelative = useRelativeTime(jobData?.fire_at ?? null);

  const chipLabel = itemKindChip(item);
  const runCount = itemRunCount(item);
  const failing = isFailing(item);
  const errorMessage = failing ? itemErrorMessage(item) : null;
  const { failed, timed_out: timedOut } = item.data;

  const { label: nextRunLabel, title: nextRunTitle } = itemNextRunDisplay(item, nextRunRelative, fireAtRelative);
  const scheduleStatus = itemScheduleStatus(item);
  const callLabel = item.kind === "listener" ? "call" : "run";
  const idle = isIdle(item);
  const label = item.humanDescription ? `${item.name}: ${item.humanDescription}` : item.name;

  return (
    <button
      type="button"
      className={cn(
        "flex w-full cursor-pointer items-start gap-1 border-b border-border bg-card p-2 text-left transition-[background,opacity]",
        "[&:last-child]:border-b-0 hover:bg-muted hover:opacity-100",
        "focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-0",
        isSelected &&
          "bg-[var(--primary-soft)] font-medium opacity-100 [box-shadow:inset_var(--border-width-thick)_0_0_0_var(--primary)]",
        idle && !isSelected && "opacity-60",
      )}
      data-testid={`unified-row-${item.kind}-${item.id}`}
      aria-pressed={isSelected}
      aria-label={label}
      onClick={onSelect}
    >
      <span className="shrink-0 pt-0" aria-hidden="true">
        <StatusShape kind={item.statusKind} size={STATUS_SHAPE_SIZE} />
      </span>
      <div className="flex min-w-0 flex-col gap-0">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="min-w-0 truncate text-sm font-medium text-foreground">{item.name}</span>
          {failing && (
            <Badge variant="danger" size="xs">
              failing
            </Badge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span
            className={cn(
              CHIP_BASE_CLASS,
              "border-border bg-muted",
              item.kind === "job" &&
                "border-[var(--handler-job-border)] bg-[var(--handler-job-bg)] text-[var(--handler-job)]",
              item.kind === "listener" &&
                "border-[var(--handler-listener-border)] bg-[var(--handler-listener-bg)] text-[var(--handler-listener)]",
            )}
            data-kind={item.kind}
            aria-label={`kind: ${chipLabel}`}
          >
            {chipLabel}
          </span>
          {item.kind === "listener" && item.data.mode && (
            <span
              className={cn(CHIP_BASE_CLASS, "border-[var(--handler-mode-border)] bg-[var(--handler-mode-bg)]")}
              aria-label={`mode: ${item.data.mode}`}
              data-testid="handler-row-mode-chip"
            >
              {item.data.mode}
            </span>
          )}
          {scheduleStatus !== null && (
            <Badge variant="muted" size="xs" data-testid="handler-row-schedule-status-badge">
              {scheduleStatus}
            </Badge>
          )}
          <span title={`Total ${callLabel}s`}>{pluralize(runCount, callLabel)}</span>
          {failed > 0 && (
            <span className="font-medium text-destructive" data-testid="handler-row-failed-count">
              {failed} failed
            </span>
          )}
          {timedOut > 0 && <span className="font-medium text-[var(--status-warning)]">{timedOut} timed out</span>}
          {nextRunLabel !== null && (
            <span
              className="whitespace-nowrap font-mono text-[length:var(--text-micro)] font-medium text-foreground-secondary"
              title={nextRunTitle ?? undefined}
              data-testid="handler-row-next-run"
            >
              {nextRunLabel}
            </span>
          )}
        </div>
        {failing && errorMessage && (
          <span
            className="truncate text-[length:var(--text-micro)] italic text-destructive"
            title={errorMessage}
            data-testid="handler-row-subline-err"
          >
            {errorMessage}
          </span>
        )}
      </div>
    </button>
  );
}
