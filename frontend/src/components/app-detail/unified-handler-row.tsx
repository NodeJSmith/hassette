import clsx from "clsx";
import { StatusShape } from "../shared/status-shape";
import type { StatusKind } from "../../utils/status";
import { handlerKindLabel } from "../../utils/status";
import type { ListenerData, JobData } from "../../api/endpoints";
import { pluralize, formatTimestamp } from "../../utils/format";
import { useRelativeTime } from "../../hooks/use-relative-time";
import styles from "./unified-handler-row.module.css";

export type UnifiedItemKind = "listener" | "job";

/** Discriminated union for items that can appear in the unified list. */
export type UnifiedItem =
  | { kind: "listener"; id: number; name: string; humanDescription: string | null; statusKind: StatusKind; data: ListenerData }
  | { kind: "job"; id: number; name: string; humanDescription: string | null; statusKind: StatusKind; data: JobData };

interface Props {
  item: UnifiedItem;
  isSelected: boolean;
  onSelect: () => void;
}

const KIND_GLYPHS: Record<string, string> = {
  "state change": "◇",
  "service call": "▷",
  "cron": "↻", "interval": "↻", "every": "↻", "daily": "↻",
  "once": "↻", "after": "↻", "schedule": "↻",
};

function kindGlyph(label: string): string {
  return KIND_GLYPHS[label] ?? "◆";
}

/**
 * A single row in the unified handlers+jobs master list.
 *
 * Clicking the row selects it in the detail pane (no expand-in-place).
 * The kind chip visually distinguishes handlers vs jobs.
 */
export function UnifiedHandlerRow({ item, isSelected, onSelect }: Props) {
  // Extract job timestamps for hook calls — hooks must be called unconditionally at top level.
  // For listener items these will be null, and useRelativeTime(null) returns "".
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
    const l = item.data;
    chipLabel = handlerKindLabel("listener", l.listener_kind, null);
    invocationsOrRuns = l.total_invocations;
    failed = l.failed;
    timedOut = l.timed_out;
    isFailing = item.statusKind === "err";
    lastErrorMessage = isFailing ? (l.last_error_message ?? null) : null;
  } else {
    const j = item.data;
    chipLabel = handlerKindLabel("job", null, j.trigger_type);
    invocationsOrRuns = j.total_executions;
    failed = j.failed;
    timedOut = j.timed_out;
    isFailing = item.statusKind === "err";
    // Next-run line for schedule jobs
    if (j.next_run) {
      nextRunLabel = `next ${nextRunRelative}`;
      nextRunTitle = formatTimestamp(j.next_run);
    } else if (j.fire_at) {
      nextRunLabel = `fire at ${fireAtRelative}`;
      nextRunTitle = formatTimestamp(j.fire_at);
    }
  }

  const callLabel = item.kind === "listener" ? "call" : "run";
  const glyph = kindGlyph(chipLabel);

  return (
    <button
      type="button"
      class={clsx(styles.row, isSelected && styles.rowSelected)}
      data-testid={`unified-row-${item.kind}-${item.id}`}
      aria-pressed={isSelected}
      aria-label={`${item.name}${item.humanDescription ? ": " + item.humanDescription : ""}`}
      onClick={onSelect}
    >
      <span class={styles.status} aria-hidden="true">
        <StatusShape kind={item.statusKind} size={10} />
      </span>
      <span class={styles.kindGlyph} aria-hidden="true" data-testid="handler-row-glyph">{glyph}</span>
      <div class={styles.body}>
        <div class={styles.header}>
          <span class={styles.kindChip} aria-label={`kind: ${chipLabel}`}>
            {chipLabel}
          </span>
          <span class={styles.name}>{item.name}</span>
          {isFailing && (
            <span class="ht-badge ht-badge--danger ht-badge--xs">failing</span>
          )}
        </div>
        {/* Subline: error message (when failing) or human description (otherwise) */}
        {isFailing && lastErrorMessage ? (
          <span class={styles.sublineErr} title={lastErrorMessage} data-testid="handler-row-subline-err">
            {lastErrorMessage}
          </span>
        ) : item.humanDescription ? (
          <span class={styles.desc} data-testid="handler-row-desc">{item.humanDescription}</span>
        ) : null}
        {/* Next-run line for schedule jobs */}
        {nextRunLabel !== null && (
          <span class={styles.nextRun} title={nextRunTitle ?? undefined} data-testid="handler-row-next-run">{nextRunLabel}</span>
        )}
        <div class={styles.stats}>
          <span title={`Total ${callLabel}s`}>{pluralize(invocationsOrRuns, callLabel)}</span>
          {failed > 0 && (
            <span class={styles.statsErr}>{failed} failed</span>
          )}
          {timedOut > 0 && (
            <span class={styles.statsWarn}>{timedOut} timed out</span>
          )}
        </div>
      </div>
    </button>
  );
}
