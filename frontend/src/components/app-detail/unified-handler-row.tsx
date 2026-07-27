import clsx from "clsx";

import type { JobData, ListenerData } from "../../api/endpoints";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { formatTimestamp, pluralize } from "../../utils/format";
import type { StatusKind } from "../../utils/status";
import { Badge } from "../shared/badge";
import { StatusShape } from "../shared/status-shape";
import { isFailing, itemErrorMessage, itemKindChip, itemRunCount } from "./overview-tab-helpers";
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
  const jobData = item.kind === "job" ? item.data : null;
  const nextRunRelative = useRelativeTime(jobData?.next_run ?? null);
  const fireAtRelative = useRelativeTime(jobData?.fire_at ?? null);

  const chipLabel = itemKindChip(item);
  const runCount = itemRunCount(item);
  const failing = isFailing(item);
  const errorMessage = failing ? itemErrorMessage(item) : null;
  const { failed, timed_out: timedOut } = item.data;

  let nextRunLabel: string | null = null;
  let nextRunTitle: string | null = null;
  if (item.kind === "job") {
    if (item.data.next_run) {
      nextRunLabel = `next ${nextRunRelative}`;
      nextRunTitle = formatTimestamp(item.data.next_run);
    } else if (item.data.fire_at) {
      nextRunLabel = `fire at ${fireAtRelative}`;
      nextRunTitle = formatTimestamp(item.data.fire_at);
    }
  }

  const callLabel = item.kind === "listener" ? "call" : "run";
  const isIdle = item.statusKind === "mute";
  const label = item.humanDescription ? `${item.name}: ${item.humanDescription}` : item.name;

  return (
    <button
      type="button"
      className={clsx(styles.row, isSelected && styles.rowSelected, isIdle && styles.rowIdle)}
      data-testid={`unified-row-${item.kind}-${item.id}`}
      aria-pressed={isSelected}
      aria-label={label}
      onClick={onSelect}
    >
      <span className={styles.status} aria-hidden="true">
        <StatusShape kind={item.statusKind} size={STATUS_DOT_SIZE} />
      </span>
      <div className={styles.body}>
        <div className={styles.header}>
          <span className={styles.name}>{item.name}</span>
          {failing && (
            <Badge variant="danger" size="xs">
              failing
            </Badge>
          )}
        </div>
        <div className={styles.meta}>
          <span className={styles.kindChip} data-kind={item.kind} aria-label={`kind: ${chipLabel}`}>
            {chipLabel}
          </span>
          {item.kind === "listener" && item.data.mode && (
            <span
              className={styles.modeChip}
              aria-label={`mode: ${item.data.mode}`}
              data-testid="handler-row-mode-chip"
            >
              {item.data.mode}
            </span>
          )}
          <span title={`Total ${callLabel}s`}>{pluralize(runCount, callLabel)}</span>
          {failed > 0 && (
            <span className={styles.statsErr} data-testid="handler-failed-count">
              {failed} failed
            </span>
          )}
          {timedOut > 0 && <span className={styles.statsWarn}>{timedOut} timed out</span>}
          {nextRunLabel !== null && (
            <span className={styles.nextRun} title={nextRunTitle ?? undefined} data-testid="handler-row-next-run">
              {nextRunLabel}
            </span>
          )}
        </div>
        {failing && errorMessage && (
          <span className={styles.sublineErr} title={errorMessage} data-testid="handler-row-subline-err">
            {errorMessage}
          </span>
        )}
      </div>
    </button>
  );
}
