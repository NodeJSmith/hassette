import clsx from "clsx";

import type { JobData, ListenerData } from "../../api/endpoints";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { formatTimestamp, pluralize } from "../../utils/format";
import type { StatusKind } from "../../utils/status";
import { handlerKindLabel } from "../../utils/status";
import { Badge } from "../shared/badge";
import { StatusShape } from "../shared/status-shape";
import styles from "./unified-handler-row.module.css";

export type UnifiedItemKind = "listener" | "job";

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
  // Hooks must be called unconditionally — null yields "".
  const jobData = item.kind === "job" ? item.data : null;
  const nextRunRelative = useRelativeTime(jobData?.next_run ?? null);
  const fireAtRelative = useRelativeTime(jobData?.fire_at ?? null);

  let invocationsOrRuns: number;
  let failed: number;
  let timedOut: number;
  let chipLabel: string;
  let isFailing: boolean;
  let lastErrorMessage: string | null = null;
  let nextRunLabel: string | null = null;
  let nextRunTitle: string | null = null;

  if (item.kind === "listener") {
    const listener = item.data;
    chipLabel = handlerKindLabel("listener", listener.listener_kind, null);
    invocationsOrRuns = listener.total_invocations;
    failed = listener.failed;
    timedOut = listener.timed_out;
    isFailing = item.statusKind === "err";
    lastErrorMessage = isFailing ? (listener.last_error_message ?? null) : null;
  } else {
    const job = item.data;
    chipLabel = handlerKindLabel("job", null, job.trigger_type);
    invocationsOrRuns = job.total_executions;
    failed = job.failed;
    timedOut = job.timed_out;
    isFailing = item.statusKind === "err";
    if (job.next_run) {
      nextRunLabel = `next ${nextRunRelative}`;
      nextRunTitle = formatTimestamp(job.next_run);
    } else if (job.fire_at) {
      nextRunLabel = `fire at ${fireAtRelative}`;
      nextRunTitle = formatTimestamp(job.fire_at);
    }
  }

  const callLabel = item.kind === "listener" ? "call" : "run";
  const isIdle = item.statusKind === "mute";
  const label = item.humanDescription ? `${item.name}: ${item.humanDescription}` : item.name;

  return (
    <button
      type="button"
      class={clsx(styles.row, isSelected && styles.rowSelected, isIdle && styles.rowIdle)}
      data-testid={`unified-row-${item.kind}-${item.id}`}
      aria-pressed={isSelected}
      aria-label={label}
      onClick={onSelect}
    >
      <span class={styles.status} aria-hidden="true">
        <StatusShape kind={item.statusKind} size={10} />
      </span>
      <div class={styles.body}>
        <div class={styles.header}>
          <span class={styles.name}>{item.name}</span>
          {isFailing && (
            <Badge variant="danger" size="xs">
              failing
            </Badge>
          )}
        </div>
        <div class={styles.meta}>
          <span class={styles.kindChip} aria-label={`kind: ${chipLabel}`}>
            {chipLabel}
          </span>
          {item.kind === "listener" && item.data.mode && (
            <span class={styles.modeChip} aria-label={`mode: ${item.data.mode}`} data-testid="handler-row-mode-chip">
              {item.data.mode}
            </span>
          )}
          <span title={`Total ${callLabel}s`}>{pluralize(invocationsOrRuns, callLabel)}</span>
          {failed > 0 && (
            <span class={styles.statsErr} data-testid="handler-failed-count">
              {failed} failed
            </span>
          )}
          {timedOut > 0 && <span class={styles.statsWarn}>{timedOut} timed out</span>}
          {nextRunLabel !== null && (
            <span class={styles.nextRun} title={nextRunTitle ?? undefined} data-testid="handler-row-next-run">
              {nextRunLabel}
            </span>
          )}
        </div>
        {isFailing && lastErrorMessage && (
          <span class={styles.sublineErr} title={lastErrorMessage} data-testid="handler-row-subline-err">
            {lastErrorMessage}
          </span>
        )}
      </div>
    </button>
  );
}
